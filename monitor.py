"""
MPSC Monitor - Bulletproof Version
Handles every possible error gracefully.
"""

import requests
import os
import re
import json
import hashlib
import sys
import traceback
from datetime import datetime, date
from urllib.parse import urljoin
from bs4 import BeautifulSoup


# ─── CONFIG ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "monitor_state.json"
DOWNLOAD_FOLDER = "downloaded_pdfs"

# Create folders safely
try:
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
except Exception as e:
    print(f"[WARN] Could not create folder: {e}")

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
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[WARN] Could not load state: {e}")
    
    return {
        "seen": {},
        "last_run": None,
        "first_run_complete": False,
        "stats": {"total_tracked": 0, "total_downloaded": 0}
    }

def save_state(state):
    try:
        state["last_run"] = datetime.now().isoformat()
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[WARN] Could not save state: {e}")

# ─── TELEGRAM ──────────────────────────────────────────

def send_telegram(title, message, url):
    """Send text notification - NEVER crashes"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram not configured")
        return False
    
    # Sanitize text for Telegram HTML
    def safe(text):
        if not text:
            return ""
        text = str(text)
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        return text
    
    text = f"""
🚨 <b>{safe(title[:200])}</b>

{safe(message[:500])}

🔗 <a href="{safe(url[:500])}">Open Link</a>
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}
    """.strip()
    
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            },
            timeout=15
        )
        print(f"  [TELEGRAM] Status: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        print(f"  [!] Telegram error: {e}")
        return False

# ─── PDF DOWNLOADER ─────────────────────────────────────

def download_pdf(pdf_url, title, section):
    """Download PDF - returns path or None, NEVER crashes"""
    if not pdf_url:
        return None
    
    # Check if actually PDF
    if '.pdf' not in pdf_url.lower():
        return None
    
    try:
        safe_title = re.sub(r'[<>:"/\\|?*]', '', str(title))
        safe_title = re.sub(r'\s+', '_', safe_title.strip())[:60]
        
        date_str = TODAY
        year_month = date_str[:7]
        section_folder = os.path.join(DOWNLOAD_FOLDER, section, year_month)
        os.makedirs(section_folder, exist_ok=True)
        
        url_hash = hashlib.md5(pdf_url.encode()).hexdigest()[:6]
        filename = f"{date_str}_{safe_title}_{url_hash}.pdf"
        filepath = os.path.join(section_folder, filename)
        
        if os.path.exists(filepath):
            return filepath
        
        print(f"  [DOWNLOAD] {filename[:80]}")
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0',
        })
        
        response = session.get(
            pdf_url,
            timeout=30,
            stream=True,
            allow_redirects=True,
            verify=False
        )
        response.raise_for_status()
        
        # Check content
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' in content_type and 'pdf' not in content_type:
            # Try to read first chunk
            first_chunk = next(response.iter_content(1024), b'')
            if b'%PDF' not in first_chunk:
                print(f"  [SKIP] Not a PDF file")
                return None
        
        # Save
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Verify
        file_size = os.path.getsize(filepath)
        if file_size < 1024:
            os.remove(filepath)
            return None
        
        with open(filepath, 'rb') as f:
            header = f.read(10)
            if not header.startswith(b'%PDF'):
                os.remove(filepath)
                return None
        
        print(f"  [OK] {file_size/1024:.0f} KB")
        return filepath
        
    except Exception as e:
        print(f"  [FAIL] PDF download: {str(e)[:60]}")
        return None

# ─── WEB SCRAPER ───────────────────────────────────────

def fetch_page(url):
    """Fetch page - returns HTML or None, NEVER crashes"""
    try:
        resp = requests.get(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0',
            },
            timeout=15,
            verify=False
        )
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  [!] Fetch failed: {str(e)[:60]}")
        return None

def extract_items(html, section_name):
    """Extract items from HTML - returns list, NEVER crashes"""
    if not html:
        return []
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        # Find all links
        for link in soup.find_all('a', href=True):
            try:
                href = link['href'].strip()
                if not href or href == '#' or len(href) < 2:
                    continue
                
                full_url = urljoin("https://mpsc.gov.in", href)
                title = link.get_text(strip=True) or "Document"
                
                # Skip if too short
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
                
            except Exception:
                continue  # Skip problematic links
        
        return items
        
    except Exception as e:
        print(f"  [!] Parse error: {e}")
        return []

# ─── MAIN ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("MPSC Monitor - Bulletproof")
    print(f"Date: {TODAY}")
    print("=" * 60)
    
    # Validate config
    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN not set!")
        return 1
    
    if not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_CHAT_ID not set!")
        return 1
    
    print(f"[OK] Telegram configured")
    print(f"[OK] Token length: {len(TELEGRAM_BOT_TOKEN)}")
    print(f"[OK] Chat ID: {TELEGRAM_CHAT_ID}")
    
    state = load_state()
    new_count = 0
    
    for section_name, url in MPSC_URLS.items():
        try:
            print(f"\n[CHECK] {section_name}")
            print(f"  URL: {url[:80]}")
            
            html = fetch_page(url)
            if not html:
                print(f"  [SKIP] Could not fetch")
                continue
            
            items = extract_items(html, section_name)
            print(f"  Found {len(items)} items")
            
            for item in items:
                try:
                    if item["hash"] in state.get("seen", {}):
                        print(f"  [SEEN] {item['title'][:50]}")
                        continue
                    
                    print(f"\n  [NEW] {item['title'][:60]}")
                    
                    # Track it
                    state["seen"][item["hash"]] = {
                        "title": item["title"],
                        "url": item["url"],
                        "date": item["date"],
                        "section": item["section"],
                        "first_seen": datetime.now().isoformat()
                    }
                    
                    # Download PDF if available
                    pdf_path = None
                    if item.get("is_pdf"):
                        pdf_path = download_pdf(item["url"], item["title"], item["section"])
                        if pdf_path:
                            state["seen"][item["hash"]]["pdf_path"] = pdf_path
                    
                    # Send notification
                    send_telegram(
                        f"[{item['section']}] {item['title'][:80]}",
                        f"Date: {item['date']}",
                        item["url"]
                    )
                    
                    new_count += 1
                    
                except Exception as e:
                    print(f"  [ERROR] Processing item: {e}")
                    continue
            
        except Exception as e:
            print(f"  [ERROR] Section {section_name}: {e}")
            continue
    
    # Save state
    save_state(state)
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  New items: {new_count}")
    print(f"  Total tracked: {len(state.get('seen', {}))}")
    print(f"{'='*60}")
    
    return 0

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
