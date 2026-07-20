import os
import sys

print("Python version:", sys.version)
print("Working directory:", os.getcwd())
print("Files in directory:", os.listdir())

# Check if monitor.py exists
if os.path.exists("monitor.py"):
    print("monitor.py: FOUND")
else:
    print("monitor.py: NOT FOUND")
    print("Looking for similar files...")
    for f in os.listdir():
        if "monitor" in f.lower():
            print(f"  Found: {f}")

# Check secrets
token = os.getenv("TELEGRAM_BOT_TOKEN", "")
chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
print(f"Token set: {'YES' if token else 'NO'} (length: {len(token)})")
print(f"Chat ID set: {'YES' if chat_id else 'NO'}")
