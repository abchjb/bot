import os
import re
import time
import sqlite3
import random
import logging
import requests
import shutil
from datetime import datetime
from pinterest_downloader import Pinterest

# ============ تنظیمات ============
EITAA_TOKEN = os.environ.get("EITAA_TOKEN")
EITAA_CHAT_ID = os.environ.get("EITAA_CHAT_ID")

PINTEREST_KEYWORDS = ["hijab", "حجاب", "hijab fashion", "modest fashion"]
MAX_POSTS_PER_RUN = 1
MAX_PINS_TO_CHECK = 5
DB_PATH = "bot.db"
TEMP_DIR = "/tmp/pinterest_downloads"

# ============ لاگ ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
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

# ============ جستجو با pinterest-downloader ============
p = Pinterest()

def search_videos(keyword, limit=10):
    try:
        result = p.search(keyword, page_size=limit, scope="videos")
        if not result.get("ok"): return []
        
        videos = []
        for pin in result.get("pins", []):
            if pin.get("media_type") == "video" and pin.get("id"):
                videos.append({
                    "pin_id": str(pin["id"]),
                    "title": pin.get("title") or keyword,
                    "keyword": keyword,
                })
        return videos
    except Exception as e:
        log.warning(f"خطا در جستجو: {e}")
        return []

def download_with_library(pin_id, final_path):
    """دانلود با استفاده از خود کتابخانه و انتقال فایل به مسیر نهایی"""
    try:
        # پوشه موقت را خالی می‌کنیم
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)
        os.makedirs(TEMP_DIR, exist_ok=True)

        # از کتابخانه می‌خواهیم در این پوشه دانلود کند
        result = p.download_pin(pin_id, path=TEMP_DIR)
        
        if not result.get("ok"):
            log.info("کتابخانه نتوانست دانلود کند.")
            return False

        # حالا ببینیم چه فایلی در پوشه موقت ساخته شده است
        files = os.listdir(TEMP_DIR)
        if not files:
            log.info("هیچ فایلی دانلود نشد.")
            return False

        # اولین فایل (که ویدیو است) را برمی‌داریم
        downloaded_file = os.path.join(TEMP_DIR, files[0])
        
        # بررسی حجم (حداقل ۱۰۰ کیلوبایت)
        if os.path.getsize(downloaded_file) < 100 * 1024:
            log.info("فایل خیلی کوچک است (احتمالاً عکس است).")
            return False

        # انتقال به مسیر نهایی
        shutil.move(downloaded_file, final_path)
        return True

    except Exception as e:
        log.warning(f"خطا در دانلود با کتابخانه: {e}")
        return False
    finally:
        # پاکسازی پوشه موقت
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR, ignore_errors=True)

# ============ تولید کپشن و ارسال ============
def generate_caption(title, keyword):
    prompt = f"یک کپشن کوتاه و جذاب فارسی (حداکثر ۲۵۰ کاراکتر) برای یک ویدیو با موضوع '{keyword}' و عنوان '{title}' بنویس. در انتها ۳ هشتگ مرتبط با حجاب و مد اسلامی اضافه کن. فقط متن کپشن را برگردان."
    url = "https://text.pollinations.ai/" + requests.utils.quote(prompt)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.text.strip():
            return re.sub(r"[\r\n]+", "\n", r.text.strip())[:1000]
    except Exception: pass
    return f"🎬 {title}\n\n📌 منبع: Pinterest\n#حجاب #مد_اسلامی #پینترست"

def send_to_eitaa(video_path, caption):
    url = f"https://eitaayar.ir/api/{EITAA_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            files = {"file": (os.path.basename(video_path), f, "video/mp4")}
            data = {"chat_id": EITAA_CHAT_ID, "caption": caption}
            r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code == 200:
            log.info("✅ ارسال موفق به ایتا")
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
            
            # دانلود با کتابخانه
            if not download_with_library(pin_id, tmp_path):
                log.info("دانلود ناموفق بود. رد شدن...")
                continue

            log.info("دانلود موفق! در حال ساخت کپشن...")
            caption = generate_caption(video["title"], keyword)
            
            log.info("در حال ارسال به ایتا...")
            if send_to_eitaa(tmp_path, caption):
                mark_sent(conn, pin_id)
                sent_count += 1
                time.sleep(10)

            if os.path.exists(tmp_path): os.remove(tmp_path)

    log.info(f"پایان اجرا. ارسال شده: {sent_count}")

if __name__ == "__main__":
    main()
