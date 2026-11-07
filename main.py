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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_pins (
            pin_id TEXT PRIMARY KEY,
            sent_at TEXT
        )
    """)
    conn.commit()
    return conn

def is_sent(conn, pin_id):
    cur = conn.execute("SELECT 1 FROM sent_pins WHERE pin_id = ?", (pin_id,))
    return cur.fetchone() is not None

def mark_sent(conn, pin_id):
    conn.execute(
        "INSERT OR REPLACE INTO sent_pins (pin_id, sent_at) VALUES (?, ?)",
        (pin_id, datetime.utcnow().isoformat())
    )
    conn.commit()

# ============ جستجوی پینترست ============
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def search_pinterest(keyword, limit=20):
    """جستجوی ویدیوهای پینترست با scraping ساده"""
    url = "https://www.pinterest.com/resource/BaseSearchResource/get/"
    params = {
        "source_url": f"/search/pins/?q={keyword}",
        "data": json.dumps({
            "options": {
                "query": keyword,
                "scope": "pins",
                "page_size": limit,
                "bookmarks": [],
            },
            "context": {},
        }),
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        results = data.get("resource_response", {}).get("data", {}).get("results", [])
    except Exception as e:
        log.warning(f"خطا در جستجو '{keyword}': {e}")
        return []

    videos = []
    for pin in results:
        try:
            pin_id = str(pin.get("id", ""))
            if not pin_id:
                continue
            # فقط پین‌هایی که ویدیو دارند
            videos_info = pin.get("videos") or {}
            video_list = videos_info.get("video_list") or {}
            if not video_list:
                continue
            # بالاترین کیفیت موجود
            best = None
            for key in ("V_720P", "V_480P", "V_HLSV4", "V_HLSV3_WEB"):
                if key in video_list and video_list[key].get("url"):
                    best = video_list[key]["url"]
                    break
            if not best:
                continue
            title = pin.get("grid_title") or pin.get("title") or keyword
            videos.append({
                "pin_id": pin_id,
                "video_url": best,
                "title": title,
                "keyword": keyword,
            })
        except Exception:
            continue
    return videos

# ============ دانلود ویدیو ============
def download_video(video_url, out_path):
    try:
        with requests.get(video_url, headers=HEADERS, stream=True, timeout=60) as r:
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
                            log.info(f"ویدیو بزرگ‌تر از حد مجاز: {out_path}")
                            return False
        if size < MIN_VIDEO_SIZE:
            os.remove(out_path)
            return False
        return True
    except Exception as e:
        log.warning(f"خطا در دانلود: {e}")
        if os.path.exists(out_path):
            os.remove(out_path)
        return False

# ============ تولید کپشن با Pollinations ============
def generate_caption(title, keyword):
    prompt = (
        f"یک کپشن کوتاه و جذاب فارسی (حداکثر ۲۵۰ کاراکتر) برای یک ویدیو "
        f"با موضوع '{keyword}' و عنوان '{title}' بنویس. "
        f"در انتها ۳ هشتگ مرتبط با حجاب و مد اسلامی اضافه کن. "
        f"فقط متن کپشن را برگردان، بدون توضیح اضافه."
    )
    url = "https://text.pollinations.ai/" + requests.utils.quote(prompt)
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200 and r.text.strip():
            caption = r.text.strip()
            # پاک‌سازی
            caption = re.sub(r"[\r\n]+", "\n", caption)[:1000]
            return caption
    except Exception as e:
        log.warning(f"خطا در تولید کپشن: {e}")

    # fallback
    return (
        f"🎬 {title}\n\n"
        f"📌 منبع: Pinterest\n"
        f"#حجاب #مد_اسلامی #پینترست"
    )

# ============ ارسال به ایتا ============
def send_to_eitaa(video_path, caption):
    url = f"https://eitaayar.ir/api/{EITAA_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            files = {"file": (os.path.basename(video_path), f, "video/mp4")}
            data = {"chat_id": EITAA_CHAT_ID, "caption": caption}
            r = requests.post(url, data=data, files=files, timeout=120)
        if r.status_code == 200:
            log.info("✅ ارسال موفق")
            return True
        log.warning(f"پاسخ ایتا: {r.status_code} - {r.text[:200]}")
        return False
    except Exception as e:
        log.warning(f"خطا در ارسال: {e}")
        return False

# ============ اجرای اصلی ============
def main():
    if not EITAA_TOKEN or not EITAA_CHAT_ID:
        log.error("EITAA_TOKEN یا EITAA_CHAT_ID تنظیم نشده")
        return

    conn = init_db()
    sent_count = 0
    random.shuffle(PINTEREST_KEYWORDS)

    for keyword in PINTEREST_KEYWORDS:
        if sent_count >= MAX_POSTS_PER_RUN:
            break
        log.info(f"جستجو: {keyword}")
        videos = search_pinterest(keyword)
        log.info(f"یافت شد: {len(videos)} ویدیو")
        random.shuffle(videos)

        for v in videos:
            if sent_count >= MAX_POSTS_PER_RUN:
                break
            if is_sent(conn, v["pin_id"]):
                continue

            tmp_path = f"/tmp/{v['pin_id']}.mp4"
            log.info(f"دانلود: {v['pin_id']}")
            if not download_video(v["video_url"], tmp_path):
                continue

            caption = generate_caption(v["title"], v["keyword"])
            log.info(f"کپشن: {caption[:80]}...")

            if send_to_eitaa(tmp_path, caption):
                mark_sent(conn, v["pin_id"])
                sent_count += 1
                time.sleep(5)  # فاصله بین پست‌ها

            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    log.info(f"پایان اجرا. ارسال شده: {sent_count}")

if __name__ == "__main__":
    main()
