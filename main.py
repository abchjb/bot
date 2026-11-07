import os
import re
import time
import sqlite3
import random
import logging
import requests
from datetime import datetime
from pinterest_dl import PinterestDL  # کتابخانه جدید

# ============ تنظیمات ============
EITAA_TOKEN = os.environ.get("EITAA_TOKEN")
EITAA_CHAT_ID = os.environ.get("EITAA_CHAT_ID")

PINTEREST_KEYWORDS = ["hijab", "حجاب", "hijab fashion", "modest fashion"]
MAX_POSTS_PER_RUN = 1
MAX_PINS_TO_CHECK = 5
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
# ایجاد یک نمونه از API
p_api = PinterestDL.with_api()

def search_videos(keyword, num=10):
    """جستجوی ویدیوها با کتابخانه pinterest-dl"""
    try:
        # این کتابخانه متد جستجو دارد که می‌تواند ویدیوها را فیلتر کند
        results = p_api.search(keyword, num=num, video_only=True)
        videos = []
        for pin in results:
            videos.append({
                "pin_id": str(pin.id),
                "title": pin.title or keyword,
                "keyword": keyword,
                "url": pin.url
            })
        return videos
    except Exception as e:
        log.warning(f"خطا در جستجو: {e}")
        return []

def download_video_with_cookie(pin_url, out_path):
    """دانلود ویدیو با استفاده از کوکی (برای دور زدن محدودیت IP)"""
    try:
        # نکته مهم: برای استفاده از کوکی، باید کوکی مرورگر خود را در گیت‌هاب تنظیم کنید
        # یا از یک فایل کوکی استفاده کنید. فعلاً سعی می‌کنیم بدون کوکی کار کنیم.
        result = p_api.scrape_and_download(pin_url, output_dir=os.path.dirname(out_path))
        
        if result and os.path.exists(result[0]):
            # انتقال فایل به مسیر مورد نظر
            os.rename(result[0], out_path)
            return True
        return False
    except Exception as e:
        log.warning(f"خطا در دانلود ویدیو: {e}")
        return False

# ============ کپشن و ارسال ============
def generate_caption(title, keyword):
    prompt = f"یک کپشن کوتاه و جذاب فارسی (حداکثر ۲۵۰ کاراکتر) برای یک ویدیو با موضوع '{keyword}' و عنوان '{title}' بنویس. در انتها ۳ هشتگ مرتبط با حجاب و مد اسلامی اضافه کن. فقط متن کپشن را برگردان."
    url = "https://text.pollinations.ai/" + requests.utils.quote(prompt)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.text.strip():
            return re.sub(r"[\r\n]+", "\n", r.text.strip())[:1000]
    except Exception: pass
    return f"🎬 {title}\n\n📌 منبع: Pinterest\n#حجاب #مد_اسلامی #پینترست"

def send_video_to_eitaa(video_path, caption):
    url = f"https://eitaayar.ir/api/{EITAA_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            files = {"file": (os.path.basename(video_path), f, "video/mp4")}
            data = {"chat_id": EITAA_CHAT_ID, "caption": caption}
            r = requests.post(url, data=data, files=files, timeout=120)
        if r.status_code == 200:
            log.info("✅ ارسال ویدیو موفق بود!")
            return True
        log.warning(f"پاسخ ایتا: {r.status_code} - {r.text[:200]}")
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
        
        videos = search_videos(keyword)
        log.info(f"یافت شد: {len(videos)} ویدیو")
        random.shuffle(videos)
        videos = videos[:MAX_PINS_TO_CHECK]

        for video in videos:
            if sent_count >= MAX_POSTS_PER_RUN: break
            
            pin_id = video["pin_id"]
            if is_sent(conn, pin_id): continue

            log.info(f"تلاش برای دانلود ویدیو {pin_id[:15]}...")
            tmp_path = f"/tmp/{pin_id}.mp4"
            
            if not download_video_with_cookie(video["url"], tmp_path):
                log.info("دانلود ویدیو ناموفق بود (احتمالاً به دلیل محدودیت IP گیت‌هاب).")
                continue

            # بررسی حجم
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 100 * 1024:
                if os.path.exists(tmp_path): os.remove(tmp_path)
                continue

            log.info("دانلود موفق! در حال ساخت کپشن...")
            caption = generate_caption(video["title"], keyword)
            
            log.info("در حال ارسال به ایتا...")
            if send_video_to_eitaa(tmp_path, caption):
                mark_sent(conn, pin_id)
                sent_count += 1
                time.sleep(10)

            if os.path.exists(tmp_path): os.remove(tmp_path)

    log.info(f"پایان اجرا. ارسال شده: {sent_count}")

if __name__ == "__main__":
    main()
