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

# کلمات کلیدی (می‌توانید بعداً از Variables بخوانید)
PINTEREST_KEYWORDS = ["hijab", "حجاب", "hijab fashion", "modest fashion"]
MAX_POSTS_PER_RUN = 3  # تعداد ارسال در هر اجرا
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

# کلمات کلیدی برای فیلتر کردن نتایج نامرتبط
RELATED_WORDS = ["hijab", "حجاب", "veil", "scarf", "modest", "abaya", "chador", "پوشش", "مانتو", "روسری", "شال", "خمار", "مقنعه"]

def get_and_filter_images(keyword, num=20):
    """جستجو و فیلتر کردن عکس‌های مرتبط"""
    try:
        # استفاده از search_and_download که در مستندات کتابخانه موجود است
        os.makedirs(TEMP_DIR, exist_ok=True)
        downloaded_files = p_api.search_and_download(
            query=keyword,
            output_dir=TEMP_DIR,
            num=num
        )
        
        if not downloaded_files:
            log.warning(f"هیچ فایلی برای '{keyword}' دانلود نشد.")
            return []

        valid_images = []
        for file_info in downloaded_files:
            # file_info معمولاً یک دیکشنری یا آبجکت با اطلاعات فایل است
            # بسته به نسخه کتابخانه، ممکن است مسیر فایل یا اطلاعات کامل را داشته باشد
            file_path = None
            title = keyword
            
            if isinstance(file_info, dict):
                file_path = file_info.get("path") or file_info.get("file_path")
                title = file_info.get("title") or file_info.get("alt") or keyword
            elif isinstance(file_info, str):
                file_path = file_info
            elif hasattr(file_info, "path"):
                file_path = file_info.path
                title = getattr(file_info, "title", keyword)
            
            if not file_path or not os.path.exists(file_path):
                continue

            # فیلتر بر اساس نام فایل یا عنوان (چون ممکن است عنوان دقیق در دسترس نباشد)
            # در این روش ساده، ما به دانلود کتابخانه اعتماد می‌کنیم و همه را نگه می‌داریم
            # اما برای کیفیت بهتر، می‌توانیم بعداً فیلتر دقیق‌تری اضافه کنیم
            
            # بررسی حجم فایل (حداقل ۵۰ کیلوبایت برای اطمینان از عکس بودن)
            if os.path.getsize(file_path) < 50 * 1024:
                continue
                
            valid_images.append({
                "path": file_path,
                "title": title,
                "keyword": keyword
            })
        
        return valid_images

    except Exception as e:
        log.warning(f"خطا در جستجو و دانلود '{keyword}': {e}")
        return []

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
        # تشخیص پسوند فایل برای MIME type
        ext = os.path.splitext(img_path)[1].lower()
        mime = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
        
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
        if sent_count >= MAX_POSTS_PER_RUN: 
            break
        
        log.info(f"--- شروع جستجو برای: {keyword} ---")
        
        # دریافت لیست عکس‌های دانلود شده
        images = get_and_filter_images(keyword)
        log.info(f"تعداد عکس‌های معتبر پیدا شده: {len(images)}")
        
        if not images:
            continue

        random.shuffle(images)

        for img in images:
            if sent_count >= MAX_POSTS_PER_RUN: 
                break
            
            # جلوگیری از ارسال تکراری (با استفاده از مسیر فایل به عنوان شناسه)
            # بهتر است از هش یا شناسه پین استفاده کنیم، اما فعلاً ساده نگه می‌داریم
            # در کد قبلی از pin_id استفاده می‌کردیم، اینجا از مسیر فایل استفاده می‌کنیم
            # برای جلوگیری از تکرار، یک شناسه ساده از نام فایل می‌سازیم
            file_name = os.path.basename(img["path"])
            # اگر قبلاً ارسال شده، رد شو
            if is_sent(conn, file_name):
                continue

            log.info(f"در حال ارسال عکس: {file_name}")
            
            caption = generate_caption(img["title"], keyword)
            if send_to_eitaa(img["path"], caption):
                mark_sent(conn, file_name)
                sent_count += 1
                time.sleep(5)  # فاصله بین ارسال‌ها

            # پاک کردن فایل بعد از ارسال برای صرفه‌جویی در فضا
            try:
                os.remove(img["path"])
            except:
                pass

    log.info(f"پایان اجرا. ارسال شده: {sent_count}")

if __name__ == "__main__":
    main()
