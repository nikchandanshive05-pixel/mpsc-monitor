"""
MPSC Monitor - Playwright Browser Version
Uses real Chrome browser to bypass blocking.
"""

import asyncio
import json
import os
import hashlib
import re
from datetime import datetime, date
from playwright.async_api import async_playwright
import requests


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "monitor_state.json"
DOWNLOAD_FOLDER = "downloaded_pdfs"
TODAY = date.today().strftime("%Y-%m-%d")

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


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"seen": {}, "last_run": None}

def save_state(state):
    state["last_run"] = datetime.now().isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

def send_telegram(title, message, url):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [!] Telegram not configured")
        return False
    
    text = f"""🚨 <b>{title[:200]}</b>

{message[:400]}

🔗 <a href="{url[:400]}">Open Link</a>
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


async def scrape_page(browser, section_name, url):
    """Scrape a single page with Playwright"""
    print(f"\n[CHECK] {section_name}")
    print(f"  URL: {url}")
    
    items = []
    context = None
    
    try:
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.0',
            viewport={'width': 1920, 'height': 1080},
            java_script_enabled=True,
        )
        
        page = await context.new_page()
        
        # Navigate with longer timeout
        print(f"  [BROWSER] Loading page...")
        response = await page.goto(url, wait_until='networkidle', timeout=60000)
        
        if not response:
            print(f"  [ERROR] No response from page")
            return items
        
        print(f"  [BROWSER] HTTP {response.status}")
        print(f"  [BROWSER] Waiting for content...")
        
        # Wait for page to fully render
        await page.wait_for_timeout(5000)
        
        # Get page content
        content = await page.content()
        print(f"  [BROWSER] Content length: {len(content)} bytes")
        
        # Extract all links using page.evaluate (JavaScript execution)
        print(f"  [BROWSER] Extracting links via JavaScript...")
        
        links = await page.evaluate("""
            () => {
                const results = [];
                const allLinks = document.querySelectorAll('a');
                allLinks.forEach(link => {
                    const href = link.href || link.getAttribute('href') || '';
                    const text = link.innerText || link.textContent || '';
                    if (href && href.length > 1 && href !== '#') {
                        results.push({
                            href: href,
                            text: text.trim().substring(0, 200),
                            isPDF: href.toLowerCase().includes('.pdf')
                        });
                    }
                });
                return results;
            }
        """)
        
        print(f"  [BROWSER] Found {len(links)} links via JS")
        
        # Also extract from onclick handlers
        onclick_links = await page.evaluate("""
            () => {
                const results = [];
                const allElements = document.querySelectorAll('*');
                allElements.forEach(el => {
                    const onclick = el.getAttribute('onclick');
                    if (onclick) {
                        const matches = onclick.match(/["'](https?:\\/\\/[^"']+)["']/g);
                        if (matches) {
                            matches.forEach(m => {
                                const url = m.replace(/["']/g, '');
                                results.push({
                                    href: url,
                                    text: el.innerText || 'Onclick link',
                                    isPDF: url.toLowerCase().includes('.pdf')
                                });
                            });
                        }
                    }
                });
                return results;
            }
        """)
        
        print(f"  [BROWSER] Found {len(onclick_links)} onclick links")
        
        all_links = links + onclick_links
        
        # Process links
        for link in all_links:
            try:
                href = link.get('href', '') or link.get('url', '')
                text = link.get('text', '') or link.get('title', 'Document')
                
                if not href or href in ['#', '', 'javascript:void(0)']:
                    continue
                
                # Skip navigation links
                skip_patterns = ['home', 'about', 'contact', 'login', 'logout', 'facebook', 'twitter', 'youtube']
                if any(p in href.lower() for p in skip_patterns):
                    continue
                
                if len(text) < 2:
                    continue
                
                item_hash = hashlib.sha256(f"{text}|{href}".encode()).hexdigest()[:16]
                
                items.append({
                    "title": text[:200],
                    "url": href[:500],
                    "date": TODAY,
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": link.get('isPDF', False) or '.pdf' in href.lower()
                })
                
            except Exception as e:
                continue
        
        # Deduplicate
        seen = set()
        unique_items = []
        for item in items:
            if item['hash'] not in seen:
                seen.add(item['hash'])
                unique_items.append(item)
        
        print(f"  [BROWSER] Unique items: {len(unique_items)}")
        
        # Show sample
        if unique_items:
            print(f"  [SAMPLE] First 3:")
            for i, item in enumerate(unique_items[:3], 1):
                print(f"    {i}. {item['title'][:50]}...")
                print(f"       PDF: {item['is_pdf']} | {item['url'][:60]}...")
        
        await context.close()
        return unique_items
        
    except Exception as e:
        print(f"  [ERROR] {str(e)[:100]}")
        if context:
            try:
                await context.close()
            except:
                pass
        return []


async def main():
    print("=" * 60)
    print("MPSC Monitor - Playwright Browser")
    print(f"Date: {TODAY}")
    print("=" * 60)
    
    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN missing")
        return 0
    if not TELEGRAM_CHAT_ID:
        print("[ERROR] TELEGRAM_CHAT_ID missing")
        return 0
    
    print(f"[OK] Telegram configured")
    
    state = load_state()
    total_new = 0
    
    async with async_playwright() as p:
        print("[BROWSER] Launching Chromium...")
        
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
            ]
        )
        
        print(f"[BROWSER] Browser launched")
        
        for section_name, url in MPSC_URLS.items():
            items = await scrape_page(browser, section_name, url)
            
            section_new = 0
            for item in items:
                if item["hash"] in state.get("seen", {}):
                    print(f"  [SEEN] {item['title'][:40]}")
                    continue
                
                print(f"\n  [NEW] {item['title'][:60]}")
                print(f"       URL: {item['url'][:80]}")
                
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
                    print(f"  [PDF] Downloading...")
                    pdf_path = download_pdf(item["url"], item["title"], item["section"])
                
                # Notify
                send_telegram(
                    f"[{item['section']}] {item['title'][:80]}",
                    f"Date: {item['date']}",
                    item["url"]
                )
                
                section_new += 1
                total_new += 1
            
            print(f"  [SECTION] New: {section_new}")
        
        await browser.close()
        print("[BROWSER] Browser closed")
    
    save_state(state)
    
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  New items: {total_new}")
    print(f"  Total tracked: {len(state.get('seen', {}))}")
    print(f"{'='*60}")
    
    return 0


if __name__ == "__main__":
    asyncio.run(main())
