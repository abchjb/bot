import os
import re
import time
import sqlite3
import random
import logging
import requests
from datetime import datetime
from pinterest_dl import PinterestDL

# ============ تنظیمات ============
EITAA_TOKEN = os.environ.get("EITAA_TOKEN")
EITAA_CHAT_ID = os.environ.get("EITAA_CHAT_ID")

PINTEREST_KEYWORDS = ["hijab", "حجاب", "hijab fashion", "modest fashion"]
MAX_POSTS_PER_RUN = 1
MAX_PINS_TO_CHECK = 10
DB_PATH = "bot.db"

# ============ لاگ ============
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ============ دیتابیس ضدتکرار ============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS sent_pins (pin_id TEXT PRIMARY KEY, sent_at TEXT)")
    conn.commit()
    return conn

def is_sent(conn, pin_id):
    cur = conn.execute("SELECT 1 FROM sent_pins WHERE pin_id = ?", (pin_id,))
    return cur.fetchone() is not None

def mark_sent(conn, pin_id):
    conn.execute("INSERT OR REPLACE INTO sent_pins (pin_id, sent_at) VALUES (?, ?)", (pin_id, datetime.utcnow().isoformat()))
    conn.commit()

# ============ جستجو با pinterest-dl ============
p_api = PinterestDL.with_api()

# کلمات کلیدی برای فیلتر کردن عکس‌های مرتبط
RELATED_WORDS = ["hijab", "حجاب", "veil", "scarf", "modest", "abaya", "chador", "پوشش", "مانتو", "روسری", "شال"]

def search_images(keyword, limit=10):
    try:
        results = p_api.search(keyword, num=limit, video_only=False)
        images = []
        for pin in results:
            # استخراج عنوان و توضیحات برای فیلتر کردن
            title = (getattr(pin, 'title', '') or '').lower()
            description = (getattr(pin, 'description', '') or '').lower()
            
            # بررسی اینکه آیا کلمه کلیدی در عنوان یا توضیحات وجود دارد
            if not any(word in title or word in description for word in RELATED_WORDS):
                continue  # اگر مرتبط نیست، رد شو

            # گرفتن لینک عکس
            img_url = getattr(pin, 'image_url', None)
            if not img_url:
                pin_id = str(getattr(pin, 'id', ''))
                img_url = f"https://i.pinimg.com/originals/{pin_id[:2]}/{pin_id[2:4]}/{pin_id[4:6]}/{pin_id}.jpg"

            images.append({
                "pin_id": str(getattr(pin, 'id', '')),
                "title": getattr(pin, 'title', keyword) or keyword,
                "keyword": keyword,
                "img_url": img_url
            })
        return images
    except Exception as e:
        log.warning(f"خطا در جستجو: {e}")
        return []

def download_image(img_url, out_path):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        with requests.get(img_url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            size = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
                        if size > 10 * 1024 * 1024: # 10MB
                            f.close()
                            os.remove(out_path)
                            return False
        if size < 10 * 1024:
            os.remove(out_path)
            return False
        return True
    except Exception as e:
        log.warning(f"خطا در دانلود: {e}")
        if os.path.exists(out_path): os.remove(out_path)
        return False

# ============ کپشن و ارسال ============
def generate_caption(title, keyword):
    prompt = f"یک کپشن کوتاه و جذاب فارسی (حداکثر ۲۵۰ کاراکتر) برای یک عکس با موضوع '{keyword}' و عنوان '{title}' بنویس. در انتها ۳ هشتگ مرتبط با حجاب و مد اسلامی اضافه کن. فقط متن کپشن را برگردان."
    url = "https://text.pollinations.ai/" + requests.utils.quote(prompt)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.text.strip():
            return re.sub(r"[\r\n]+", "\n", r.text.strip())[:1000]
    except Exception: pass
    return f"🖼 {title}\n\n📌 منبع: Pinterest\n#حجاب #مد_اسلامی #پینترست"

def send_to_eitaa(img_path, caption):
    url = f"https://eitaayar.ir/api/{EITAA_TOKEN}/sendPhoto"
    try:
        with open(img_path, "rb") as f:
            files = {"file": (os.path.basename(img_path), f, "image/png")}
            data = {"chat_id": EITAA_CHAT_ID, "caption": caption}
            r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code == 200:
            log.info("✅ ارسال موفق")
            return True
        return False
    except Exception as e:
        log.warning(f"خطا در ارسال: {e}")
        return False

# ============ اجرای اصلی ============
def main():
    if not all([EITAA_TOKEN, EITAA_CHAT_ID]):
        log.error("تنظیمات کامل نیست.")
        return

    conn = init_db()
    sent_count = 0
    random.shuffle(PINTEREST_KEYWORDS)

    for keyword in PINTEREST_KEYWORDS:
        if sent_count >= MAX_POSTS_PER_RUN: break
        log.info(f"جستجو: {keyword}")
        
        items = search_images(keyword)
        log.info(f"یافت شد: {len(items)} عکس مرتبط")
        random.shuffle(items)
        items = items[:MAX_PINS_TO_CHECK]

        for item in items:
            if sent_count >= MAX_POSTS_PER_RUN: break
            
            pin_id = item["pin_id"]
            if is_sent(conn, pin_id): continue

            log.info(f"دانلود عکس {pin_id[:15]}...")
            tmp_path = f"/tmp/{pin_id}.png"
            
            if not download_image(item["img_url"], tmp_path):
                continue

            caption = generate_caption(item["title"], keyword)
            if send_to_eitaa(tmp_path, caption):
                mark_sent(conn, pin_id)
                sent_count += 1
                time.sleep(5)

            if os.path.exists(tmp_path): os.remove(tmp_path)

    log.info(f"پایان اجرا. ارسال شده: {sent_count}")

if __name__ == "__main__":
    main()
