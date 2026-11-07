import os
import re
import time
import sqlite3
import random
import logging
import requests
import shutil
from datetime import datetime
from pinterest_dl import PinterestDL

# ============ تنظیمات ============
EITAA_TOKEN = os.environ.get("EITAA_TOKEN")
EITAA_CHAT_ID = os.environ.get("EITAA_CHAT_ID")

PINTEREST_KEYWORDS = ["hijab", "حجاب", "hijab fashion", "modest fashion"]
MAX_POSTS_PER_RUN = 3
DB_PATH = "bot.db"
TEMP_DIR = "/tmp/pinterest_images"

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

# ============ جستجو و دانلود با pinterest-dl ============
p_api = PinterestDL.with_api()

def get_downloaded_files(keyword):
    """اجرای جستجو و سپس خواندن مستقیم فایل‌های دانلود شده از پوشه"""
    try:
        # پوشه را خالی می‌کنیم
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)
        os.makedirs(TEMP_DIR, exist_ok=True)

        log.info(f"در حال جستجو و دانلود برای: {keyword}")
        p_api.search_and_download(query=keyword, output_dir=TEMP_DIR, num=15)
        
        # حالا هر فایلی که در پوشه است را برمی‌داریم
        files = []
        if os.path.exists(TEMP_DIR):
            for f in os.listdir(TEMP_DIR):
                full_path = os.path.join(TEMP_DIR, f)
                # فقط فایل‌های عکس را در نظر می‌گیریم
                if os.path.isfile(full_path) and f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    # بررسی حجم (حداقل ۲۰ کیلوبایت)
                    if os.path.getsize(full_path) > 20 * 1024:
                        files.append(full_path)
        
        return files
    except Exception as e:
        log.warning(f"خطا در دانلود: {e}")
        return []

# ============ کپشن و ارسال ============
def generate_caption(title, keyword):
    prompt = f"یک کپشن کوتاه و جذاب فارسی (حداکثر ۲۵۰ کاراکتر) برای یک عکس با موضوع '{keyword}' بنویس. در انتها ۳ هشتگ مرتبط با حجاب و مد اسلامی اضافه کن. فقط متن کپشن را برگردان."
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
        # تشخیص MIME type بر اساس پسوند فایل
        ext = os.path.splitext(img_path)[1].lower()
        if ext in ['.jpg', '.jpeg']:
            mime = "image/jpeg"
        elif ext == '.png':
            mime = "image/png"
        else:
            mime = "image/jpeg" # پیش‌فرض

        with open(img_path, "rb") as f:
            files = {"file": (os.path.basename(img_path), f, mime)}
            data = {"chat_id": EITAA_CHAT_ID, "caption": caption}
            r = requests.post(url, data=data, files=files, timeout=60)
        
        if r.status_code == 200:
            log.info("✅ ارسال موفق")
            return True
        log.warning(f"پاسخ ایتا: {r.status_code} - {r.text[:100]}")
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
        
        log.info(f"--- شروع جستجو برای: {keyword} ---")
        
        files = get_downloaded_files(keyword)
        log.info(f"تعداد فایل‌های آماده ارسال: {len(files)}")
        
        if not files:
            continue

        random.shuffle(files)

        for file_path in files:
            if sent_count >= MAX_POSTS_PER_RUN: break
            
            # استفاده از نام فایل به عنوان شناسه یکتا برای جلوگیری از تکرار
            file_name = os.path.basename(file_path)
            if is_sent(conn, file_name):
                continue

            log.info(f"در حال ارسال عکس: {file_name}")
            
            # ساخت کپشن (چون عنوان دقیق را نداریم، از کلمه کلیدی استفاده می‌کنیم)
            caption = generate_caption(keyword, keyword)
            
            if send_to_eitaa(file_path, caption):
                mark_sent(conn, file_name)
                sent_count += 1
                time.sleep(5)

            # پاک کردن فایل بعد از ارسال
            try:
                os.remove(file_path)
            except:
                pass

        # پاک کردن پوشه موقت در پایان هر کلمه کلیدی
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR, ignore_errors=True)

    log.info(f"پایان اجرا. ارسال شده: {sent_count}")

if __name__ == "__main__":
    main()
