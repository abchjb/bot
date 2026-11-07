import os
import requests

EITAA_TOKEN = os.environ.get("EITAA_TOKEN")
EITAA_CHAT_ID = os.environ.get("EITAA_CHAT_ID")

print(f"Token: {EITAA_TOKEN[:10]}...")
print(f"Chat ID: {EITAA_CHAT_ID}")

url = f"https://eitaayar.ir/api/{EITAA_TOKEN}/sendMessage"
data = {
    "chat_id": EITAA_CHAT_ID,
    "text": "🤖 تست ربات: اگر این پیام را می‌بینید، یعنی تنظیمات ایتایار درست است."
}

try:
    r = requests.post(url, data=data, timeout=30)
    print(f"Status Code: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")
