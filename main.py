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
# قرار دادن کوکی شما به صورت امن
PINTEREST_COOKIE = """_routing_id="e8490a7c-845d-4e1f-a3bc-1f5ad14b3f23"; csrftoken=118bd5a653f0b89c050338af009b9a49; sessionFunnelEventLogged=1; _b="AZol+Tv0eENIzpjAUXD8R2GqygGnvmKfhiCnaXRgWJwq0cREhNo0fZW+H3OJUbrqVwo="; _auth=1; _pinterest_sess=TWc9PSZkUDcyTEFmQVFlT1FtYzlWSW5iM3dnanBnWC9XZ1hSemtGYzlRZUQ4NjNESVY2cFdoQzZLcEUrTmkzdGYrK092bEh1eUdGNFVwdjBOQmpMZ2VYUi9GWUdISTJGaHlqUEh5UE1KQnZueHEyM3g0N210SkJHZUFhVWR0TGswYmRpcUJKaDdYMy9FTFN5RjkxVnQ3Y1RxdHBjVWU5a29sT244bkR2U0dxN0ZBSFk0WHY2TTFjU21zaUR6M2FEY3AwdDdVNnlyYndHSk93Z29HM0RwZk9yb2UzanRxOWNtOGt4RXI2bjJHQ1ExN0taTE83cWxIRzl5ZjJsTnFWSUtpYUxqdzVIdno3R1JiN1o2Yjl3VWJlZUZKbjloMW5wTjJSQW8rYk1ONW5nSG4wUGhwWkxEMk16MnY1cklPVGlNckFEdjh0RmFFNzA3bHliUUxiVlJiYmlhaXlLYVZra0cyVXM4WWJIOVFkUVl5OTZIbXgzQmtrYXNudkZ1UnVhUlhCNkd5NEpmdnZ3cXlpMmdvVnlWR21MaEpYWmJNTENPOFFERWNFSUM4YVJZeHJyYUlXTithV3hCbi9wYVBZYzUwSUt2a3llTWZRUXp6WmtRNmJqMEVBTnFvTHROMkxXQzlBNExWSnVPandJdXRRKzVRQkNlMzQ0R1ozcW1SNU4ySmd0eTJFMDVhUHdPcHNrS2wrNnFxKzhXd3E3K3poMzVUenVOb0xWZHVSaGFseUZYZm9reDBQQ09hcUFoL0o1TU4yQzhUQ1VnSzd2VHN3Qm5mcEk1ZzBvbVBFMlBJbVRtTGs3R255eHZMT0JNdDdEaHVaODVSNFBhSHN2ZUsxeW53SzVlSFlDeFAzTHlYN2VyWThWTDQ2QTg4YU1zeEZXMlhJd25lMndDMTMvOUdRbDdvbkVYRForQXdGdlBOUGlWaCs1YzE3TW5ZY1dpWUxMeEZBRzVYUXc5K1U4bmt4VUFUeTNuRGRGNnI1NUk4cHRoRXZRN1Ftd25WYlg1N3NBejkycVYyaFcyWXdXZEtoZi91MVZiSC8vZjhnSExyZVB4THBkQkhPN0tVSVhnRStlTzB4ZEI4MWpKUDJnbVB6aGgzSTFkbzIzZTB5M2tZd2o5MkhTV0tpNUsycGtUdEZmS0xWcDk5SXJGb1V0eGZFUVFEelpiUDIvVUhpcnJNNmtUYTRDd0RYRW5QMGxRSVMvT3ZxaUlLUWovZGIxYnpFK0RCTGpTZ3BUa2paa2NFM0VJRG9TMzhYRlFEbXN4VjFGWlgzd0ZUNktqWXZVSDhiU3p0dkxFN1hicjBxamRmRE1Lb3RYWktYQktGV3BMNFE1SFpkc2VINUJNVmd4ZUQxTVB4RkRFZUxWd1ZGUkVvSGZXbDNUaW1mRjJ5WWZnQ1p0TkhyLzVtbFVUVkJ0UnRrYzNYVGpKZ1cxbE9STUIzMVhUWHR4N3YwQW4xVHFXTDh4WDBDN29Sd0FmODNheDJkN3Z4emZPQ2xXNkVCa0lldHFQN1JzSGhOUzhDWFVnVWtEN2I1RWRvUStmSXRoejZEM2J1WTNoOW1jTUNZaWhSS3JNUGNYeEpGN0FieEVEVFNwekl0TGZ2NzgvMXJqWFdPYmk1cndPVVhMK001RnNOeUFoMXBGeFVOc0RSSEw2WGpFOVFYVkZoZE16NkpuVHJXQ2JkR2dQVFlIOU8xa3ZxV2RHdFlwcnpGUjlmZ1Foc2RXVHJTbzBDN0JBR1ZyUGU5Ty96WFBGUFZqUGo5L1g2NzFvSHcrQXQzWFZqYWFiYWs2MkhkYWUmMTBSYkhESXptT1JUWHpyZDlWaUNFY1p1QWdRPQ==; l_o=lyqAIYAGa6TK+tXHYTkIV5c/G+X6c+CQIrWwxQ9RDlcf8Ic5bdo/iS/mkhgKX55vXrYSZ0r9/yOtORRNV6hj27nlDVRsGFlj3b45uYs7RTI8j8w0uqTUnVJBcIxLikIPfNc=; __Secure-s_a=NFhuVU55SEN1UFNkdXFkM2NNRUt0Y3lHcEdrUVl1dW9hNDZMNnpGQmptZUprTm96dEQ4VExXb2U2QStBRU01M3hKeXlIdGNPVHNqc3VKL1FLT3UzYU9FTitnOTNjMUMzdmkrWXNDTk1FVDV1THNCT3E5UkszRmV3alp3S3l6blk4eXdsSm5ZUEdjRjQzQ1lwdHdqc0h0ZWtCMldWUWZIaUcyRTgwYVdEZGxGZ2w5c0p2MzJiOGZyeXBJVDhsLzd2UGgzc3hNSjYxU3VHVXpza1F5QnFBcExKWDRvU2E5TEtsLzUxTTNvTjFscm1wb2Eza21meUtVTWxXRExRNVptbURUZ0IvckJ1SUw1YTJMVlpwOU55MHQ5SVNWdUtqKzNFTE5yeWZsSGROT0tKWUpHNkwrY2I5ZTFITGtZdXhGbjNVamY2MC9aTXdPZnRsVTJFN3ZrOFRhL1AzTXhsYjQ2OTZzeVpaYTRuUUlRamFFakhnQ1Fpa2Frclk5L2NnaWNzYUlRNUxVM01sd2QzS1ZsRDBnc09uRkhYUWpQRnFLZUFqNnVnT3ovTk9WWHBIV1JEN2FSaSsralNkYURiQjhpYkhCZFNxYlBuUVdyRXBnYjNWeVI1ZXhCT1JlZ0QzeWRrSmpyZnF5WDFuQ2ZxVkMwUnFGU2YyY0tORWlBWm5nZ0U2MCtQM1FORlhPNjdBeFpWVVB2RFMzdHkvYngrQnZxdytaT0U3eUx6WWJsdnZETE9jNWVoN3FuM1I0cmhPanFKejhYSno5bzAwNXJtTDVxS2JwYVNUOE1NMWVOaFBiUDB4d0JhdFRHRHg4bjFLcDBXbDFHNUYyQjM4MmIvR3RzUDNtd3R0dFFXYXBIbTZYalpXQmdVRzJCa2FZOEtoY1lsVG05ZDJDZnZCZkljYjVnb2cyaU5rU2k4aW9TajhVMCs3MTBiYjdDdVRwc01PZm1UMFN6ZEpjVkpYMkdaaDcwQjNORkRRb3U4VHhtcUtDbUtCWm84cUNCTlhseGZDUkVCUzBtaXJYSkFiUFBCYUd2RWZhZi9YalJJTFJvMWNJcmFQbmd4czI0VnpaM29saFRUS1ZINHJkOEUybCt4SE5oU0RBbXRrT0FXWVdKam9HbzBqdmx5MGY4RnZGMU1qeGtadDcyQll0cGxlWE0wMFBvWEJzV3MzQXZDUmJaL2hCUnBEY3FpblVNRDU1UTdDYzR5bnovSXVESVFKMnBzUGlFMm16QjlLSG9sbVNTdUdacHRPdkpTdXVscUJXSy90d2pPOTNzYU10V215aDRuMlB1QXViT2Zyak1pWU11VlZ3TmFpNE9GTThqdXpudz0mM2MvdnM5Sm9qRHAxNSt5V3RkL0lNck9qMk1VPQ==; tst=ARDuCFwdDuKCBioAtdXjvoEk-tiMe3sqBYgbU7XQtrfobr_gvECsfrjBX-8mtkYTFbWPyNmSEoIgdvzljaT8ljxjxUzOQlcWXdvyb-4jjW680k02iqjiXA6wH0PCaKU4g4SwFCC5wU4s06dedJPcJwKDcEy73kQGQh633aFv1TFxLF04NViHlrJ5m_kW_QkQS58jHVCVJuGY8rA-; g_state={"i_l":0,"i_ll":1794046108840,"i_e":{"enable_itp_optimization":24},"i_et":1794046108840,"i_b":"By3KV+NADAgndyrzIYBv5wcLCco6FRiPLG/8jXwdM5k"}"""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pinterest.com/",
    "X-Requested-With": "XMLHttpRequest",
    "Cookie": PINTEREST_COOKIE
}

def search_pinterest(keyword, limit=20):
    """جستجوی ویدیوهای پینترست با scraping"""
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
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
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
        with requests.get(video_url, headers=HEADERS, stream=True, timeout=30) as r:
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
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.text.strip():
            caption = r.text.strip()
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
    # استفاده از API خام برای جلوگیری از خطای کتابخانه
    url = f"https://eitaayar.ir/api/{EITAA_TOKEN}/sendVideo"
    try:
        with open(video_path, "rb") as f:
            files = {"file": (os.path.basename(video_path), f, "video/mp4")}
            data = {"chat_id": EITAA_CHAT_ID, "caption": caption}
            r = requests.post(url, data=data, files=files, timeout=120)
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
