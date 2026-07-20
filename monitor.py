"""
MPSC Monitor - GitHub Actions Optimized
Monitors MPSC website sections and sends Telegram alerts for new items.
"""

import requests
import os
import re
import json
import hashlib
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup


# ─── CONFIG ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "monitor_state.json"

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

# ─── STATE MANAGEMENT ────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"seen": {}, "last_run": None}

def save_state(state):
    state["last_run"] = datetime.now().isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

# ─── TELEGRAM ────────────────────────────────────────────

def send_telegram(title, message, url):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram not configured")
        return False
    
    text = f"""
🚨 <b>MPSC Alert</b>

<b>{title}</b>

{message}

🔗 <a href="{url}">Open Link</a>
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
            timeout=10
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [!] Telegram error: {e}")
        return False

# ─── WEB SCRAPER ─────────────────────────────────────────

def fetch_page(url):
    try:
        resp = requests.get(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            },
            timeout=20,
            verify=False
        )
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  [!] Fetch failed: {e}")
        return None

def extract_items(html, section_name):
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    
    # Strategy 1: Table rows
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            
            title = ""
            url = ""
            date_str = datetime.now().strftime("%Y-%m-%d")
            
            for cell in cells:
                text = cell.get_text(strip=True)
                if text and not title and text not in ['', 'View', 'Download']:
                    title = text
                    m = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', text)
                    if m:
                        date_str = f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
                
                link = cell.find('a', href=True)
                if link:
                    href = link['href'].strip()
                    if href and href != '#':
                        url = urljoin("https://mpsc.gov.in", href)
            
            if title and url:
                item_hash = hashlib.sha256(f"{title}|{url}".encode()).hexdigest()[:16]
                items.append({
                    "title": title,
                    "url": url,
                    "date": date_str,
                    "hash": item_hash,
                    "section": section_name
                })
    
    # Strategy 2: Direct PDF links
    for link in soup.find_all('a', href=True):
        href = link['href']
        if '.pdf' in href.lower():
            full_url = urljoin("https://mpsc.gov.in", href)
            title = link.get_text(strip=True) or "PDF"
            
            if not any(i["url"] == full_url for i in items):
                item_hash = hashlib.sha256(f"{title}|{full_url}".encode()).hexdigest()[:16]
                items.append({
                    "title": title,
                    "url": full_url,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "hash": item_hash,
                    "section": section_name
                })
    
    return items

# ─── MAIN ────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("MPSC Monitor - GitHub Actions")
    print("=" * 60)
    
    state = load_state()
    new_items = []
    total_checked = 0
    
    for section_name, url in MPSC_URLS.items():
        print(f"\n[CHECK] {section_name}")
        print(f"  URL: {url}")
        
        html = fetch_page(url)
        items = extract_items(html, section_name)
        total_checked += len(items)
        
        for item in items:
            if item["hash"] not in state["seen"]:
                print(f"  [NEW] {item['title'][:60]}")
                state["seen"][item["hash"]] = {
                    "title": item["title"],
                    "url": item["url"],
                    "date": item["date"],
                    "section": section_name,
                    "first_seen": datetime.now().isoformat()
                }
                new_items.append(item)
                
                send_telegram(
                    f"[{section_name}] {item['title'][:80]}",
                    f"Date: {item['date']}\nSection: {section_name}",
                    item["url"]
                )
            else:
                print(f"  [SEEN] {item['title'][:60]}")
    
    save_state(state)
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Total checked: {total_checked}")
    print(f"  New items: {len(new_items)}")
    print(f"  Total tracked: {len(state['seen'])}")
    print(f"{'='*60}")
    
    if new_items:
        print(f"\nFound {len(new_items)} new items!")

if __name__ == "__main__":
    main()
