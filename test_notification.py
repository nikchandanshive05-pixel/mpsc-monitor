"""
Test notification - sends a test message to Telegram
"""

import requests
import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_test():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Missing Telegram credentials!")
        print("Make sure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set")
        return False
    
    message = """
🚨 <b>TEST NOTIFICATION</b>

Your MPSC Monitor is working correctly!

✅ Telegram bot is connected
✅ GitHub Actions can send messages
✅ You will receive alerts for new MPSC updates

⏰ Test sent at: Now
    """.strip()
    
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            print("✅ SUCCESS! Check your Telegram now.")
            print(f"   Message ID: {response.json()['result']['message_id']}")
            return True
        else:
            print(f"❌ FAILED: HTTP {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("MPSC MONITOR - TEST NOTIFICATION")
    print("=" * 50)
    print(f"Bot Token: {TELEGRAM_BOT_TOKEN[:20]}...")
    print(f"Chat ID: {TELEGRAM_CHAT_ID}")
    print("-" * 50)
    send_test()
