"""
MPSC Monitor - Today-First Download + Continuous Monitoring
First run: Downloads ALL items from today
Then: Monitors every 15 minutes for new items
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

TODAY = date.today().strftime("%Y-%m-%d")
TODAY_PATTERNS = [
    date.today().strftime("%d-%m-%Y"),      # 20-07-2026
    date.today().strftime("%d/%m/%Y"),        # 20/07/2026
    date.today().strftime("%d.%m.%Y"),        # 20.07.2026
    date.today().strftime("%Y-%m-%d"),        # 2026-07-20
    date.today().strftime("%Y/%m/%d"),        # 2026/07/20
]


# ─── STATE ──────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "seen": {},
        "last_run": None,
        "first_run_complete": False,
        "today_downloaded": False,
        "stats": {
            "total_tracked": 0,
            "total_downloaded": 0
        }
    }

def save_state(state):
    state["last_run"] = datetime.now().isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

# ─── TELEGRAM ──────────────────────────────────────────

def send_telegram(title, message, url, pdf_path=None):
    """Send text + optional PDF"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram not configured")
        return False
    
    text = f"""
🚨 <b>{title}</b>

{message}

🔗 <a href="{url}">Open Link</a>
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}
    """.strip()
    
    try:
        # Send text
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
        
        # Send PDF if provided
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, 'rb') as f:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                    data={
                        "chat_id": TELEGRAM_CHAT_ID,
                        "caption": f"📄 {title[:80]}",
                        "parse_mode": "HTML"
                    },
                    files={"document": f},
                    timeout=60
                )
        
        return resp.status_code == 200
    except Exception as e:
        print(f"  [!] Telegram error: {e}")
        return False

# ─── DATE CHECKER ──────────────────────────────────────

def is_from_today(text, url=""):
    """Check if text or URL contains today's date"""
    combined = f"{text} {url}".lower()
    for pattern in TODAY_PATTERNS:
        if pattern.lower() in combined:
            return True
    return False

def extract_date(text):
    """Extract date from text, return None if not found"""
    patterns = [
        r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})',
        r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups[0]) == 4:
                return f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}"
            else:
                return f"{groups[2]}-{groups[1].zfill(2)}-{groups[0].zfill(2)}"
    return None

# ─── PDF DOWNLOADER ─────────────────────────────────────

def download_pdf(pdf_url, title, section):
    """Download PDF and return filepath"""
    if not pdf_url or '.pdf' not in pdf_url.lower():
        return None
    
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
    safe_title = re.sub(r'\s+', '_', safe_title.strip())[:80]
    
    date_match = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', title + pdf_url)
    if date_match:
        date_str = f"{date_match.group(3)}-{date_match.group(2).zfill(2)}-{date_match.group(1).zfill(2)}"
    else:
        date_str = TODAY
    
    year_month = date_str[:7]
    section_folder = os.path.join(DOWNLOAD_FOLDER, section, year_month)
    os.makedirs(section_folder, exist_ok=True)
    
    url_hash = hashlib.md5(pdf_url.encode()).hexdigest()[:6]
    filename = f"{date_str}_{safe_title}_{url_hash}.pdf"
    filepath = os.path.join(section_folder, filename)
    
    if os.path.exists(filepath):
        return filepath
    
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/pdf,*/*;q=0.8',
        })
        
        response = session.get(pdf_url, timeout=45, stream=True, allow_redirects=True, verify=False)
        response.raise_for_status()
        
        # Check for HTML masquerading
        if 'text/html' in response.headers.get('Content-Type', ''):
            first_chunk = next(response.iter_content(1024))
            if b'%PDF' not in first_chunk:
                return None
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        file_size = os.path.getsize(filepath)
        if file_size < 1024:
            os.remove(filepath)
            return None
        
        with open(filepath, 'rb') as f:
            if not f.read(10).startswith(b'%PDF'):
                os.remove(filepath)
                return None
        
        print(f"  [OK] Downloaded: {filename} ({file_size/1024:.1f} KB)")
        return filepath
        
    except Exception as e:
        print(f"  [FAIL] Download error: {str(e)[:60]}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None

def resolve_pdf_url(url):
    """Resolve to actual PDF URL"""
    if '.pdf' in url.lower():
        return url
    
    try:
        session = requests.Session()
        response = session.get(url, timeout=15, verify=False, allow_redirects=True)
        
        if '.pdf' in response.url.lower():
            return response.url
        
        if 'text/html' in response.headers.get('Content-Type', ''):
            soup = BeautifulSoup(response.text, 'html.parser')
            
            meta = soup.find('meta', attrs={'http-equiv': 'refresh'})
            if meta:
                content = meta.get('content', '')
                match = re.search(r'url=(.+)', content, re.IGNORECASE)
                if match:
                    return resolve_pdf_url(urljoin(url, match.group(1).strip()))
            
            for link in soup.find_all('a', href=True):
                if '.pdf' in link['href'].lower():
                    return urljoin(url, link['href'])
        
        return response.url
    except:
        return url

# ─── WEB SCRAPER ───────────────────────────────────────

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
            date_str = TODAY
            is_pdf = False
            
            for cell in cells:
                text = cell.get_text(strip=True)
                if text and not title and text not in ['', 'View', 'Download', 'PDF']:
                    title = text
                    extracted = extract_date(text)
                    if extracted:
                        date_str = extracted
                
                link = cell.find('a', href=True)
                if link:
                    href = link['href'].strip()
                    if href and href != '#':
                        url = urljoin("https://mpsc.gov.in", href)
                        if '.pdf' in href.lower():
                            is_pdf = True
            
            if title and url:
                item_hash = hashlib.sha256(f"{title}|{url}".encode()).hexdigest()[:16]
                items.append({
                    "title": title,
                    "url": url,
                    "date": date_str,
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": is_pdf,
                    "is_from_today": is_from_today(title, url)
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
                    "date": TODAY,
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": True,
                    "is_from_today": is_from_today(title, full_url)
                })
    
    return items

# ─── MAIN LOGIC ────────────────────────────────────────

def process_item(item, state, is_first_run=False):
    """Process a single item - download, notify, track"""
    if item["hash"] in state["seen"]:
        print(f"  [SEEN] {item['title'][:60]}")
        return False
    
    print(f"\n  [NEW] {item['title'][:60]}")
    print(f"      Date: {item['date']} | Today: {item.get('is_from_today', False)}")
    
    # Track it
    state["seen"][item["hash"]] = {
        "title": item["title"],
        "url": item["url"],
        "date": item["date"],
        "section": item["section"],
        "first_seen": datetime.now().isoformat(),
        "pdf_downloaded": False
    }
    
    # Resolve PDF URL
    pdf_url = resolve_pdf_url(item["url"])
    filepath = None
    
    if '.pdf' in pdf_url.lower():
        print(f"  [PDF] Downloading...")
        filepath = download_pdf(pdf_url, item["title"], item["section"])
        if filepath:
            state["seen"][item["hash"]]["pdf_downloaded"] = True
            state["stats"]["total_downloaded"] += 1
    
    # Send notification
    notify_title = f"[{item['section']}] {item['title'][:80]}"
    notify_body = f"Date: {item['date']}\nSection: {item['section']}"
    
    if is_first_run:
        notify_title = f"📥 TODAY'S ITEM: {notify_title}"
    else:
        notify_title = f"🚨 NEW: {notify_title}"
    
    send_telegram(notify_title, notify_body, item["url"], filepath)
    
    return True

def run_first_time(state):
    """First run: Download ALL items from today"""
    print("=" * 60)
    print("FIRST RUN - DOWNLOADING ALL TODAY'S ITEMS")
    print(f"Date: {TODAY}")
    print("=" * 60)
    
    today_items = []
    all_items = []
    
    for section_name, url in MPSC_URLS.items():
        print(f"\n[CHECK] {section_name}")
        print(f"  URL: {url}")
        
        html = fetch_page(url)
        items = extract_items(html, section_name)
        all_items.extend(items)
        
        # Filter today's items
        section_today = [i for i in items if i.get("is_from_today", False)]
        today_items.extend(section_today)
        
        print(f"  Total items: {len(items)}")
        print(f"  Today's items: {len(section_today)}")
    
    print(f"\n{'='*60}")
    print(f"FOUND {len(today_items)} ITEMS FROM TODAY")
    print(f"Total items on all pages: {len(all_items)}")
    print(f"{'='*60}")
    
    # Process today's items
    new_count = 0
    for item in today_items:
        if process_item(item, state, is_first_run=True):
            new_count += 1
    
    # Also process non-today items (mark as seen, don't notify)
    print(f"\n[MARKING] {len(all_items) - len(today_items)} older items as seen...")
    for item in all_items:
        if item["hash"] not in state["seen"]:
            state["seen"][item["hash"]] = {
                "title": item["title"],
                "url": item["url"],
                "date": item["date"],
                "section": item["section"],
                "first_seen": datetime.now().isoformat(),
                "pdf_downloaded": False,
                "skipped": True
            }
    
    state["first_run_complete"] = True
    state["today_downloaded"] = True
    
    print(f"\n{'='*60}")
    print("FIRST RUN COMPLETE")
    print(f"{'='*60}")
    print(f"  Today's items downloaded: {new_count}")
    print(f"  Total items now tracked: {len(state['seen'])}")
    print(f"  Next run will only alert for NEW items")
    print(f"{'='*60}")
    
    return new_count

def run_monitor(state):
    """Regular run: Only check for new items"""
    print("=" * 60)
    print("MONITOR RUN - CHECKING FOR NEW ITEMS")
    print(f"Last run: {state.get('last_run', 'Never')}")
    print("=" * 60)
    
    new_count = 0
    
    for section_name, url in MPSC_URLS.items():
        print(f"\n[CHECK] {section_name}")
        
        html = fetch_page(url)
        items = extract_items(html, section_name)
        
        for item in items:
            if process_item(item, state, is_first_run=False):
                new_count += 1
    
    return new_count

def main():
    print("=" * 60)
    print("MPSC Monitor - Today-First + Continuous")
    print("=" * 60)
    
    state = load_state()
    
    # Determine mode
    if not state.get("first_run_complete", False):
        # First run - download all today's items
        run_first_time(state)
    else:
        # Regular monitoring run
        new_count = run_monitor(state)
        
        if new_count > 0:
            print(f"\n🎉 Found {new_count} NEW items!")
        else:
            print("\n✅ No new items since last check.")
    
    # Save state
    save_state(state)
    
    # Final stats
    print(f"\n{'='*60}")
    print("STATS")
    print(f"{'='*60}")
    print(f"  Total tracked: {len(state['seen'])}")
    print(f"  Total PDFs downloaded: {state['stats'].get('total_downloaded', 0)}")
    print(f"  First run complete: {state.get('first_run_complete', False)}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
