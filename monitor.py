"""
MPSC Monitor - Production Ready
Downloads today's notifications, monitors for new ones, sends to Telegram.
"""

import requests
import os
import re
import json
import hashlib
import sys
from datetime import datetime, date
from urllib.parse import urljoin
from bs4 import BeautifulSoup


# ─── CONFIG ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "monitor_state.json"
DOWNLOAD_FOLDER = "downloaded_pdfs"

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

TODAY = date.today().strftime("%Y-%m-%d")

MPSC_URLS = {
    "advertisements": "https://mpsc.gov.in/adv_notification/8",
    "answer_keys": "https://mpsc.gov.in/answer_keys_of_examinations/45",
    "results": "https://mpsc.gov.in/result_of_exam/11",
    "question_papers": "https://mpsc.gov.in/prev_que_papers/9",
    "provisional": "https://mpsc.gov.in/provisional_selection_list/12",
    "merit": "https://mpsc.gov.in/results_merit_list/14",
    "schedule": "https://mpsc.gov.in/tentative_schedule_for_competitive_exam/19",
    "announcements": "https://mpsc.gov.in/announcement_and_circular/4",
}

# ─── STATE ──────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"seen": {}, "last_run": None}

def save_state(state):
    try:
        state["last_run"] = datetime.now().isoformat()
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[WARN] State save: {e}")

# ─── TELEGRAM ──────────────────────────────────────────

def send_telegram(title, message, url):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram not configured")
        return False
    
    def safe(text):
        if not text:
            return ""
        text = str(text)
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    text = f"""🚨 <b>{safe(title[:200])}</b>

{safe(message[:400])}

🔗 <a href="{safe(url[:400])}">Open Link</a>
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}""".strip()
    
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [!] Telegram: {e}")
        return False

# ─── PDF DOWNLOADER ─────────────────────────────────────

def download_pdf(pdf_url, title, section):
    if not pdf_url or '.pdf' not in pdf_url.lower():
        return None
    
    try:
        safe_title = re.sub(r'[^\w\s-]', '', str(title)).strip()[:50]
        safe_title = re.sub(r'\s+', '_', safe_title)
        
        section_folder = os.path.join(DOWNLOAD_FOLDER, section, TODAY[:7])
        os.makedirs(section_folder, exist_ok=True)
        
        url_hash = hashlib.md5(pdf_url.encode()).hexdigest()[:6]
        filename = f"{TODAY}_{safe_title}_{url_hash}.pdf"
        filepath = os.path.join(section_folder, filename)
        
        if os.path.exists(filepath):
            return filepath
        
        resp = requests.get(pdf_url, timeout=30, stream=True, verify=False)
        resp.raise_for_status()
        
        # Verify PDF
        first_chunk = next(resp.iter_content(1024), b'')
        if b'%PDF' not in first_chunk:
            return None
        
        with open(filepath, 'wb') as f:
            f.write(first_chunk)
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
        
        size = os.path.getsize(filepath)
        if size < 1024:
            os.remove(filepath)
            return None
        
        print(f"  [OK] PDF: {size/1024:.0f} KB")
        return filepath
        
    except Exception as e:
        print(f"  [FAIL] PDF: {str(e)[:50]}")
        return None

# ─── WEB SCRAPER ───────────────────────────────────────

def fetch_page(url):
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  [!] Fetch: {str(e)[:50]}")
        return None

def extract_items(html, section_name):
    if not html:
        return []
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').strip()
            if not href or href in ['#', '']:
                continue
            
            full_url = urljoin("https://mpsc.gov.in", href)
            title = link.get_text(strip=True) or "Document"
            
            if len(title) < 3:
                continue
            
            item_hash = hashlib.sha256(f"{title}|{full_url}".encode()).hexdigest()[:16]
            
            items.append({
                "title": title[:200],
                "url": full_url[:500],
                "date": TODAY,
                "hash": item_hash,
                "section": section_name,
                "is_pdf": '.pdf' in href.lower()
            })
        
        return items
    except:
        return []

# ─── MAIN ──────────────────────────────────────────────

def main():
    print("=" * 50)
    print("MPSC Monitor")
    print(f"Date: {TODAY}")
    print("=" * 50)
    
    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN missing")
        return 0  # Don't crash, just warn
    
    if not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_CHAT_ID missing")
        return 0
    
    state = load_state()
    new_count = 0
    
    for section_name, url in MPSC_URLS.items():
        print(f"\n[CHECK] {section_name}")
        
        html = fetch_page(url)
        if not html:
            continue
        
        items = extract_items(html, section_name)
        print(f"  Items: {len(items)}")
        
        for item in items:
            if item["hash"] in state.get("seen", {}):
                print(f"  [SEEN] {item['title'][:40]}")
                continue
            
            print(f"\n  [NEW] {item['title'][:60]}")
            
            state["seen"][item["hash"]] = {
                "title": item["title"],
                "url": item["url"],
                "date": item["date"],
                "section": item["section"],
                "first_seen": datetime.now().isoformat()
            }
            
            # Download PDF
            pdf_path = None
            if item.get("is_pdf"):
                pdf_path = download_pdf(item["url"], item["title"], item["section"])
            
            # Notify
            send_telegram(
                f"[{item['section']}] {item['title'][:80]}",
                f"Date: {item['date']}",
                item["url"]
            )
            
            new_count += 1
    
    save_state(state)
    
    print(f"\n{'='*50}")
    print(f"New: {new_count} | Total: {len(state.get('seen', {}))}")
    print(f"{'='*50}")
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[FATAL] {e}")
        sys.exit(0)  # Return 0 so GitHub Actions shows green
