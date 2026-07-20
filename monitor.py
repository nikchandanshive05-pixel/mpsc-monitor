"""
MPSC Monitor + Auto PDF Downloader
Monitors MPSC website, downloads new PDFs, sends to Telegram.
"""

import requests
import os
import re
import json
import hashlib
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup


# ─── CONFIG ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "monitor_state.json"
DOWNLOAD_FOLDER = "downloaded_pdfs"

# Ensure download folder exists
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

# ─── STATE MANAGEMENT ────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"seen": {}, "last_run": None, "downloaded_pdfs": {}}

def save_state(state):
    state["last_run"] = datetime.now().isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

# ─── TELEGRAM ──────────────────────────────────────────

def send_telegram_text(title, message, url):
    """Send text notification to Telegram"""
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
        print(f"  [!] Telegram text error: {e}")
        return False


def send_telegram_pdf(filepath, caption, url):
    """Send PDF file to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram not configured")
        return False
    
    if not os.path.exists(filepath):
        print(f"  [!] File not found: {filepath}")
        return False
    
    try:
        with open(filepath, 'rb') as f:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML"
                },
                files={"document": f},
                timeout=60
            )
        
        if resp.status_code == 200:
            print(f"  [OK] PDF sent to Telegram")
            return True
        else:
            print(f"  [!] Telegram PDF error: {resp.status_code}")
            print(f"      {resp.text[:200]}")
            return False
            
    except Exception as e:
        print(f"  [!] Telegram PDF error: {e}")
        return False


def send_telegram_photo(image_path, caption):
    """Send image/screenshot to Telegram"""
    if not os.path.exists(image_path):
        return False
    
    try:
        with open(image_path, 'rb') as f:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML"
                },
                files={"photo": f},
                timeout=30
            )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [!] Photo send error: {e}")
        return False

# ─── PDF DOWNLOADER ─────────────────────────────────────

def download_pdf(pdf_url, title, section):
    """Download PDF and save to organized folder"""
    if not pdf_url or '.pdf' not in pdf_url.lower():
        print(f"  [SKIP] Not a PDF URL: {pdf_url[:60]}")
        return None
    
    # Create safe filename
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
    safe_title = re.sub(r'\s+', '_', safe_title.strip())[:80]
    
    # Parse date from URL or title
    date_match = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', title + pdf_url)
    if date_match:
        date_str = f"{date_match.group(3)}-{date_match.group(2).zfill(2)}-{date_match.group(1).zfill(2)}"
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Organized path: downloaded_pdfs/section/YYYY-MM/filename.pdf
    year_month = date_str[:7]  # YYYY-MM
    section_folder = os.path.join(DOWNLOAD_FOLDER, section, year_month)
    os.makedirs(section_folder, exist_ok=True)
    
    # Unique filename
    url_hash = hashlib.md5(pdf_url.encode()).hexdigest()[:6]
    filename = f"{date_str}_{safe_title}_{url_hash}.pdf"
    filepath = os.path.join(section_folder, filename)
    
    # Skip if already downloaded
    if os.path.exists(filepath):
        print(f"  [SKIP] Already downloaded: {filename}")
        return filepath
    
    print(f"  [DOWNLOAD] {filename}")
    print(f"      From: {pdf_url[:80]}...")
    
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/pdf,*/*;q=0.8',
        })
        
        # Follow redirects, handle SSL
        response = session.get(
            pdf_url,
            timeout=45,
            stream=True,
            allow_redirects=True,
            verify=False
        )
        response.raise_for_status()
        
        # Verify it's actually a PDF
        content_type = response.headers.get('Content-Type', '').lower()
        content_length = response.headers.get('Content-Length', '0')
        
        # Check if HTML masquerading as PDF
        if 'text/html' in content_type:
            # Try to find actual PDF in response
            first_chunk = next(response.iter_content(1024))
            if b'%PDF' not in first_chunk and b'<html' in first_chunk:
                print(f"  [WARN] Got HTML instead of PDF, trying to resolve...")
                
                # Re-fetch as normal GET
                response = session.get(pdf_url, timeout=30, verify=False)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Look for actual PDF link
                for link in soup.find_all('a', href=True):
                    if '.pdf' in link['href'].lower():
                        actual_url = urljoin(pdf_url, link['href'])
                        print(f"  [RETRY] Found actual PDF: {actual_url[:80]}")
                        return download_pdf(actual_url, title, section)
                
                print(f"  [FAIL] Could not resolve PDF")
                return None
        
        # Stream download
        with open(filepath, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        
        # Verify file
        file_size = os.path.getsize(filepath)
        if file_size < 1024:
            print(f"  [FAIL] File too small ({file_size} bytes)")
            os.remove(filepath)
            return None
        
        # Verify PDF header
        with open(filepath, 'rb') as f:
            header = f.read(10)
            if not header.startswith(b'%PDF'):
                print(f"  [FAIL] Not a valid PDF (header: {header[:5]})")
                os.remove(filepath)
                return None
        
        print(f"  [OK] Downloaded: {filename} ({file_size/1024:.1f} KB)")
        return filepath
        
    except Exception as e:
        print(f"  [FAIL] Download error: {str(e)[:80]}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None


def resolve_pdf_url(url):
    """Resolve intermediate pages to get actual PDF URL"""
    if '.pdf' in url.lower():
        return url
    
    try:
        session = requests.Session()
        response = session.get(url, timeout=15, verify=False, allow_redirects=True)
        
        # If redirect landed on PDF
        if '.pdf' in response.url.lower():
            return response.url
        
        # If HTML page, parse for PDF
        if 'text/html' in response.headers.get('Content-Type', ''):
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Meta refresh
            meta = soup.find('meta', attrs={'http-equiv': 'refresh'})
            if meta:
                content = meta.get('content', '')
                url_match = re.search(r'url=(.+)', content, re.IGNORECASE)
                if url_match:
                    redirect = url_match.group(1).strip()
                    return resolve_pdf_url(urljoin(url, redirect))
            
            # Find PDF link
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href.lower():
                    return urljoin(url, href)
            
            # iframe/embed
            for embed in soup.find_all(['iframe', 'embed'], src=True):
                if '.pdf' in embed['src'].lower():
                    return urljoin(url, embed['src'])
        
        return response.url
        
    except Exception as e:
        print(f"  [WARN] Could not resolve URL: {e}")
        return url

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
            is_pdf = False
            
            for cell in cells:
                text = cell.get_text(strip=True)
                if text and not title and text not in ['', 'View', 'Download', 'PDF']:
                    title = text
                    m = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', text)
                    if m:
                        date_str = f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
                
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
                    "is_pdf": is_pdf
                })
    
    # Strategy 2: Direct PDF links
    for link in soup.find_all('a', href=True):
        href = link['href']
        if '.pdf' in href.lower():
            full_url = urljoin("https://mpsc.gov.in", href)
            title = link.get_text(strip=True) or "PDF Document"
            
            if not any(i["url"] == full_url for i in items):
                item_hash = hashlib.sha256(f"{title}|{full_url}".encode()).hexdigest()[:16]
                items.append({
                    "title": title,
                    "url": full_url,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": True
                })
    
    # Strategy 3: Links that might lead to PDFs
    for link in soup.find_all('a', href=True):
        href = link['href']
        text = link.get_text(strip=True).lower()
        if 'download' in text or 'view' in text:
            full_url = urljoin("https://mpsc.gov.in", href)
            if not any(i["url"] == full_url for i in items):
                title = link.get_text(strip=True) or "Document"
                item_hash = hashlib.sha256(f"{title}|{full_url}".encode()).hexdigest()[:16]
                items.append({
                    "title": title,
                    "url": full_url,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": False  # Will be resolved later
                })
    
    return items

# ─── MAIN ────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("MPSC Monitor + Auto PDF Downloader")
    print("=" * 60)
    
    state = load_state()
    new_items = []
    total_checked = 0
    pdfs_downloaded = 0
    
    for section_name, url in MPSC_URLS.items():
        print(f"\n[CHECK] {section_name}")
        print(f"  URL: {url}")
        
        html = fetch_page(url)
        items = extract_items(html, section_name)
        total_checked += len(items)
        
        for item in items:
            if item["hash"] not in state["seen"]:
                print(f"\n  [NEW] {item['title'][:60]}")
                state["seen"][item["hash"]] = {
                    "title": item["title"],
                    "url": item["url"],
                    "date": item["date"],
                    "section": section_name,
                    "first_seen": datetime.now().isoformat(),
                    "pdf_downloaded": False
                }
                new_items.append(item)
                
                # Send text notification
                send_telegram_text(
                    f"[{section_name}] {item['title'][:80]}",
                    f"Date: {item['date']}\nSection: {section_name}",
                    item["url"]
                )
                
                # If PDF, download and send
                if item.get("is_pdf") or True:  # Try all links
                    pdf_url = resolve_pdf_url(item["url"])
                    
                    if pdf_url and '.pdf' in pdf_url.lower():
                        print(f"  [PDF] Resolving: {pdf_url[:80]}...")
                        filepath = download_pdf(pdf_url, item["title"], section_name)
                        
                        if filepath:
                            # Send PDF to Telegram
                            caption = f"""
📄 <b>{item['title'][:100]}</b>

Section: {section_name}
Date: {item['date']}

✅ Auto-downloaded and sent
                            """.strip()
                            
                            send_telegram_pdf(filepath, caption, item["url"])
                            state["seen"][item["hash"]]["pdf_downloaded"] = True
                            pdfs_downloaded += 1
                    else:
                        print(f"  [INFO] Not a PDF link, skipping download")
                
            else:
                print(f"  [SEEN] {item['title'][:60]}")
    
    save_state(state)
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Total checked: {total_checked}")
    print(f"  New items: {len(new_items)}")
    print(f"  PDFs downloaded: {pdfs_downloaded}")
    print(f"  Total tracked: {len(state['seen'])}")
    print(f"{'='*60}")
    
    if new_items:
        print(f"\nFound {len(new_items)} new items!")
        if pdfs_downloaded > 0:
            print(f"Downloaded and sent {pdfs_downloaded} PDFs to Telegram")

if __name__ == "__main__":
    main()
