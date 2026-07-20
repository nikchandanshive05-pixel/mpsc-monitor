import os
import requests

print("=== SETUP TEST ===")
print(f"Token set: {'YES' if os.getenv('TELEGRAM_BOT_TOKEN') else 'NO'}")
print(f"Chat ID set: {'YES' if os.getenv('TELEGRAM_CHAT_ID') else 'NO'}")

# Test Telegram
try:
    resp = requests.post(
        f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/getMe",
        timeout=10
    )
    print(f"Bot API: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Bot name: {resp.json().get('result', {}).get('username', 'Unknown')}")
except Exception as e:
    print(f"Bot API error: {e}")

# Test MPSC
try:
    resp = requests.get("https://mpsc.gov.in", timeout=10, verify=False)
    print(f"MPSC site: {resp.status_code}")
except Exception as e:
    print(f"MPSC error: {e}")

print("=== TEST COMPLETE ===")
