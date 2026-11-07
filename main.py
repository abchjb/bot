import os
import re
import json
import time
import sqlite3
import random
import logging
import requests
from datetime import datetime

# ============ تنظیمات ============
EITAA_TOKEN = os.environ.get("EITAA_TOKEN")
EITAA_CHAT_ID = os.environ.get("EITAA_CHAT_ID")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

PINTEREST_KEYWORDS = ["hijab", "حجاب", "hijab fashion", "modest fashion"]
MAX_POSTS_PER_RUN = 2
MIN_VIDEO_SIZE = 100 * 1024       # 100 KB
MAX_VIDEO_SIZE = 45 * 1024 * 1024  # 45 MB
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

# ============ توابع API ============

def get_pin_links(keyword):
    """مرحله ۱: جستجوی پین‌ها با استفاده از API اول"""
    # این API همان است که در تصویر اول فرستادید (Pinterest Scraper توسط oanor)
    url = "https://pinterest-scraper-api1.p.rapidapi.com/search"
    querystring = {"query": keyword, "limit": "20"}
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "pinterest-scraper-api1.p.rapidapi.com"
    }
    try:
        r = requests.get(url, headers=headers, params=querystring, timeout=15)
        r.raise_for_status()
        data = r.json()
        # استخراج لینک پین‌ها
        pins = data.get("data", []) or data.get("pins", [])
        links = []
        for pin in pins:
            link = pin.get("link") or pin.get("url")
            if link and "pinterest.com/pin/" in link:
                links.append({
                    "pin_id": pin.get("id"),
                    "url": link,
                    "title": pin.get("title", keyword)
                })
        return links
    except Exception as e:
        log.warning(f"خطا در جستجوی اولیه '{keyword}': {e}")
        return []

def get_video_url_from_pin(pin_url):
    """مرحله ۲: گرفتن لینک ویدیو از API دوم"""
    # این API همان است که در تصویر دوم فرستادید (Pinterest Video And Image Downloader توسط vikas5914)
    url = "https://pinterest-video-and-image-downloader.p.rapidapi.com/get_video"
    querystring = {"url": pin_url}
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "pinterest-video-and-image-downloader.p.rapidapi.com"
    }
    try:
        r = requests.get(url, headers=headers, params=querystring, timeout=15)
        r.raise_for_status()
        data = r.json()
        # معمولاً لینک ویدیو در این فیلدها برمی‌گردد
        video_url = data.get("video_url") or data.get("url") or data.get("download_url")
        return video_url
    except Exception as e:
        log.warning(f"خطا در استخراج ویدیو: {e}")
        return None

# ============ دانلود و ارسال ============

def download_video(video_url, out_path):
    try:
        with requests.get(video_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            size = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        size += len(chunk)
                        if size > MAX_VIDEO_SIZE:
                            f.close()
                            os.remove(out_path)
                            return False
        if size < MIN_VIDEO_SIZE:
            os.remove(out_path)
            return False
        return True
    except Exception as e:
        log.warning(f"خطا در دانلود: {e}")
        if os.path.exists(out_path): os.remove(out_path)
        return False

def generate_caption(title, keyword):
    prompt = f"یک کپشن کوتاه و جذاب فارسی (حداکثر ۲۵۰ کاراکتر) برای یک ویدیو با موضوع '{keyword}' و عنوان '{title}' بنویس. در انتها ۳ هشتگ مرتبط با حجاب و مد اسلامی اضافه کن. فقط متن کپشن را برگردان."
    url = "https://text.pollinations.ai/" + requests.utils.quote(prompt)
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200 and r.text.strip():
            return re.sub(r"[\r\n]+", "\n", r.text.strip())[:1000]
    except Exception:
        pass
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
    if not all([EITAA_TOKEN, EITAA_CHAT_ID, RAPIDAPI_KEY]):
        log.error("تنظیمات (توکن‌ها) کامل نیست.")
        return

    conn = init_db()
    sent_count = 0
    random.shuffle(PINTEREST_KEYWORDS)

    for keyword in PINTEREST_KEYWORDS:
        if sent_count >= MAX_POSTS_PER_RUN: break
        log.info(f"جستجو: {keyword}")
        
        # ۱. گرفتن لیست پین‌ها
        pins = get_pin_links(keyword)
        log.info(f"یافت شد: {len(pins)} پین")
        random.shuffle(pins)

        for pin in pins:
            if sent_count >= MAX_POSTS_PER_RUN: break
            
            pin_id = str(pin["pin_id"])
            if is_sent(conn, pin_id): continue

            # ۲. گرفتن لینک ویدیو از پین
            log.info(f"بررسی ویدیو برای پین {pin_id}...")
            video_url = get_video_url_from_pin(pin["url"])
            if not video_url:
                continue # اگر ویدیو نبود، برو بعدی

            # ۳. دانلود و ارسال
            tmp_path = f"/tmp/{pin_id}.mp4"
            if not download_video(video_url, tmp_path): continue

            caption = generate_caption(pin["title"], keyword)
            if send_to_eitaa(tmp_path, caption):
                mark_sent(conn, pin_id)
                sent_count += 1
                time.sleep(5)

            if os.path.exists(tmp_path): os.remove(tmp_path)

    log.info(f"پایان اجرا. ارسال شده: {sent_count}")

if __name__ == "__main__":
    main()
