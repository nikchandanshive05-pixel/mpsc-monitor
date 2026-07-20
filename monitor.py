"""
MPSC Monitor - Aggressive Scraper
Tries every possible method to extract links from MPSC website.
"""

import requests
import os
import re
import json
import hashlib
import sys
from datetime import datetime, date
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Comment


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
        
        print(f"  [DOWNLOAD] {filename[:80]}")
        
        resp = requests.get(pdf_url, timeout=30, stream=True, verify=False)
        resp.raise_for_status()
        
        # Check if actually PDF
        content_type = resp.headers.get('Content-Type', '').lower()
        if 'pdf' not in content_type and 'octet-stream' not in content_type:
            first = next(resp.iter_content(1024), b'')
            if b'%PDF' not in first:
                print(f"  [SKIP] Not PDF (content-type: {content_type})")
                return None
        
        with open(filepath, 'wb') as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
        
        size = os.path.getsize(filepath)
        if size < 1024:
            os.remove(filepath)
            return None
        
        print(f"  [OK] {size/1024:.0f} KB")
        return filepath
        
    except Exception as e:
        print(f"  [FAIL] {str(e)[:60]}")
        return None

# ─── AGGRESSIVE WEB SCRAPER ─────────────────────────────

def fetch_page(url):
    """Fetch with multiple strategies"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }
    
    strategies = [
        lambda: requests.get(url, headers=headers, timeout=20, verify=False),
        lambda: requests.get(url, headers=headers, timeout=20, verify=False, allow_redirects=True),
        lambda: requests.get(url, timeout=20, verify=False),
    ]
    
    for i, strategy in enumerate(strategies):
        try:
            resp = strategy()
            print(f"  [TRY {i+1}] HTTP {resp.status_code}")
            if resp.status_code == 200:
                print(f"  [OK] Content length: {len(resp.text)} bytes")
                return resp.text
        except Exception as e:
            print(f"  [TRY {i+1}] Failed: {str(e)[:50]}")
    
    return None

def extract_all_possible_items(html, section_name):
    """
    Try EVERY possible extraction strategy.
    Returns list of items.
    """
    if not html:
        print("  [ERROR] No HTML content")
        return []
    
    items = []
    soup = BeautifulSoup(html, 'html.parser')
    
    print(f"  [PARSE] HTML length: {len(html)}")
    print(f"  [PARSE] Tags found: {len(soup.find_all())}")
    
    # ─── STRATEGY 1: All <a> tags with href ─────────────────
    all_links = soup.find_all('a', href=True)
    print(f"  [S1] Found {len(all_links)} <a> tags")
    
    for link in all_links:
        try:
            href = link.get('href', '').strip()
            if not href or href in ['#', '', 'javascript:void(0)']:
                continue
            
            full_url = urljoin("https://mpsc.gov.in", href)
            title = link.get_text(strip=True) or link.get('title', '') or "Document"
            
            # Skip navigation/menu links
            if any(x in href.lower() for x in ['home', 'about', 'contact', 'login', 'logout', '#']):
                continue
            
            if len(title) < 2:
                continue
            
            item_hash = hashlib.sha256(f"{title}|{full_url}".encode()).hexdigest()[:16]
            
            items.append({
                "title": title[:200],
                "url": full_url[:500],
                "date": TODAY,
                "hash": item_hash,
                "section": section_name,
                "is_pdf": '.pdf' in href.lower(),
                "source": "a_tag"
            })
            
        except Exception:
            continue
    
    # ─── STRATEGY 2: onclick handlers ───────────────────────
    onclick_tags = soup.find_all(onclick=True)
    print(f"  [S2] Found {len(onclick_tags)} onclick tags")
    
    for tag in onclick_tags:
        try:
            onclick = tag['onclick']
            # Extract URLs from onclick
            urls = re.findall(r'["\'](https?://[^"\']+)["\']', onclick)
            for u in urls:
                title = tag.get_text(strip=True) or "Onclick link"
                item_hash = hashlib.sha256(f"{title}|{u}".encode()).hexdigest()[:16]
                items.append({
                    "title": title[:200],
                    "url": u[:500],
                    "date": TODAY,
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": '.pdf' in u.lower(),
                    "source": "onclick"
                })
        except:
            continue
    
    # ─── STRATEGY 3: data-* attributes ──────────────────────
    for tag in soup.find_all(attrs={'data-url': True}):
        try:
            u = urljoin("https://mpsc.gov.in", tag['data-url'])
            title = tag.get_text(strip=True) or "Data link"
            item_hash = hashlib.sha256(f"{title}|{u}".encode()).hexdigest()[:16]
            items.append({
                "title": title[:200],
                "url": u[:500],
                "date": TODAY,
                "hash": item_hash,
                "section": section_name,
                "is_pdf": '.pdf' in u.lower(),
                "source": "data_attr"
            })
        except:
            continue
    
    # ─── STRATEGY 4: iframe/embed src ───────────────────────
    for tag in soup.find_all(['iframe', 'embed'], src=True):
        try:
            u = urljoin("https://mpsc.gov.in", tag['src'])
            title = "Embedded content"
            item_hash = hashlib.sha256(f"embed|{u}".encode()).hexdigest()[:16]
            items.append({
                "title": title,
                "url": u[:500],
                "date": TODAY,
                "hash": item_hash,
                "section": section_name,
                "is_pdf": '.pdf' in u.lower(),
                "source": "embed"
            })
        except:
            continue
    
    # ─── STRATEGY 5: JavaScript variables ───────────────────
    scripts = soup.find_all('script')
    print(f"  [S3] Found {len(scripts)} script tags")
    
    for script in scripts:
        try:
            if script.string:
                # Find PDF URLs in JS
                pdf_urls = re.findall(r'["\']([^"\']*\.pdf[^"\']*)["\']', script.string, re.IGNORECASE)
                for u in pdf_urls:
                    full = urljoin("https://mpsc.gov.in", u)
                    item_hash = hashlib.sha256(f"js|{full}".encode()).hexdigest()[:16]
                    items.append({
                        "title": "PDF from JS",
                        "url": full[:500],
                        "date": TODAY,
                        "hash": item_hash,
                        "section": section_name,
                        "is_pdf": True,
                        "source": "javascript"
                    })
                
                # Find any URLs with "download" or "file"
                dl_urls = re.findall(r'["\']([^"\']*download[^"\']*)["\']', script.string, re.IGNORECASE)
                for u in dl_urls:
                    full = urljoin("https://mpsc.gov.in", u)
                    item_hash = hashlib.sha256(f"jsdl|{full}".encode()).hexdigest()[:16]
                    items.append({
                        "title": "Download from JS",
                        "url": full[:500],
                        "date": TODAY,
                        "hash": item_hash,
                        "section": section_name,
                        "is_pdf": '.pdf' in u.lower(),
                        "source": "javascript_dl"
                    })
        except:
            continue
    
    # ─── STRATEGY 6: Raw text URL extraction ────────────────
    text_urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', html)
    print(f"  [S4] Found {len(text_urls)} URLs in raw text")
    
    for u in text_urls:
        try:
            if '.pdf' in u.lower():
                item_hash = hashlib.sha256(f"raw|{u}".encode()).hexdigest()[:16]
                if not any(i['hash'] == item_hash for i in items):
                    items.append({
                        "title": "Raw PDF URL",
                        "url": u[:500],
                        "date": TODAY,
                        "hash": item_hash,
                        "section": section_name,
                        "is_pdf": True,
                        "source": "raw_text"
                    })
        except:
            continue
    
    # ─── STRATEGY 7: Form actions ───────────────────────────
    for form in soup.find_all('form'):
        try:
            action = form.get('action', '')
            if action:
                u = urljoin("https://mpsc.gov.in", action)
                title = "Form action"
                item_hash = hashlib.sha256(f"form|{u}".encode()).hexdigest()[:16]
                items.append({
                    "title": title,
                    "url": u[:500],
                    "date": TODAY,
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": False,
                    "source": "form"
                })
        except:
            continue
    
    # ─── DEDUPLICATE ─────────────────────────────────────────
    seen_hashes = set()
    unique_items = []
    for item in items:
        if item['hash'] not in seen_hashes:
            seen_hashes.add(item['hash'])
            unique_items.append(item)
    
    print(f"  [TOTAL] Unique items found: {len(unique_items)}")
    
    # Show sample
    if unique_items:
        print(f"  [SAMPLE] First 3 items:")
        for i, item in enumerate(unique_items[:3], 1):
            print(f"    {i}. [{item['source']}] {item['title'][:50]}...")
            print(f"       URL: {item['url'][:60]}...")
    
    return unique_items

# ─── MAIN ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("MPSC Monitor - Aggressive Scraper")
    print(f"Date: {TODAY}")
    print("=" * 60)
    
    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN missing")
        return 0
    if not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_CHAT_ID missing")
        return 0
    
    print(f"[OK] Telegram configured")
    print(f"[OK] Token: {TELEGRAM_BOT_TOKEN[:20]}...")
    print(f"[OK] Chat ID: {TELEGRAM_CHAT_ID}")
    
    state = load_state()
    total_new = 0
    
    for section_name, url in MPSC_URLS.items():
        print(f"\n{'='*60}")
        print(f"[SECTION] {section_name}")
        print(f"URL: {url}")
        print(f"{'='*60}")
        
        html = fetch_page(url)
        if not html:
            print(f"  [SKIP] Could not fetch page")
            continue
        
        items = extract_all_possible_items(html, section_name)
        
        section_new = 0
        for item in items:
            if item["hash"] in state.get("seen", {}):
                print(f"  [SEEN] {item['title'][:40]}")
                continue
            
            print(f"\n  [NEW] {item['title'][:60]}")
            print(f"       Source: {item['source']}")
            print(f"       URL: {item['url'][:80]}")
            
            state["seen"][item["hash"]] = {
                "title": item["title"],
                "url": item["url"],
                "date": item["date"],
                "section": item["section"],
                "first_seen": datetime.now().isoformat(),
                "source": item.get("source", "unknown")
            }
            
            # Download PDF
            pdf_path = None
            if item.get("is_pdf"):
                print(f"  [PDF] Attempting download...")
                pdf_path = download_pdf(item["url"], item["title"], item["section"])
                if pdf_path:
                    state["seen"][item["hash"]]["pdf_path"] = pdf_path
            
            # Notify
            send_telegram(
                f"[{item['section']}] {item['title'][:80]}",
                f"Date: {item['date']}\nSource: {item.get('source', 'unknown')}",
                item["url"]
            )
            
            section_new += 1
            total_new += 1
        
        print(f"\n  [SECTION SUMMARY] New: {section_new}")
    
    save_state(state)
    
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  Total new items: {total_new}")
    print(f"  Total tracked: {len(state.get('seen', {}))}")
    print(f"{'='*60}")
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[FATAL] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(0)
