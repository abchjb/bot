import os
import re
import time
import sqlite3
import random
import logging
import requests
from datetime import datetime
from pinterest_downloader import Pinterest

# ============ تنظیمات ============
EITAA_TOKEN = os.environ.get("EITAA_TOKEN")
EITAA_CHAT_ID = os.environ.get("EITAA_CHAT_ID")

PINTEREST_KEYWORDS = ["hijab", "حجاب", "hijab fashion", "modest fashion"]
MAX_POSTS_PER_RUN = 1  # فقط ۱ ویدیو در هر اجرا
MAX_PINS_TO_CHECK = 5
DB_PATH = "bot.db"

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
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

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
                    "video_url": pin.get("video", {}).get("url") # گرفتن لینک مستقیم از خروجی جستجو
                })
        return videos
    except Exception as e:
        log.warning(f"خطا در جستجو: {e}")
        return []

def download_direct(video_url, out_path):
    """دانلود مستقیم با requests"""
    try:
        with requests.get(video_url, headers=HEADERS, stream=True, timeout=30) as r:
            r.raise_for_status()
            size = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
                        if size > 45 * 1024 * 1024: # 45MB limit
                            f.close()
                            os.remove(out_path)
                            return False
        if size < 100 * 1024: # < 100KB
            os.remove(out_path)
            return False
        return True
    except Exception as e:
        log.warning(f"خطای دانلود مستقیم: {e}")
        if os.path.exists(out_path): os.remove(out_path)
        return False

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
            
            # بررسی اینکه آیا لینک مستقیم از جستجو به دست آمده است یا خیر
            video_url = video.get("video_url")
            if not video_url:
                log.info("لینک مستقیم پیدا نشد. رد شدن...")
                continue

            # دانلود با requests
            if not download_direct(video_url, tmp_path):
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
