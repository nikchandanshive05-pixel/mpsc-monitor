"""
MPSC Monitor - Smart Filter
Only captures actual notification/content links, ignores navigation.
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
    "schedule": "https://mpsc.gov.in/tentative_schedule_for_competitive_exam/19",
    "announcements": "https://mpsc.gov.in/announcement_and_circular/4",
}


# ─── BLOCKED KEYWORDS ───────────────────────────────────

# Skip these — they are navigation, not content
BLOCKED_TEXT = [
    'home', 'next', 'previous', 'prev', 'disclaimer', 'copyright',
    'privacy policy', 'terms', 'contact us', 'about us', 'sitemap',
    'skip to content', 'screen reader', 'accessibility', 'login',
    'logout', 'register', 'search', 'submit', 'reset', 'back',
    'click here', 'read more', 'learn more', 'details', 'view all',
    'archive', 'older posts', 'newer posts', 'first', 'last',
    'print', 'share', 'bookmark', 'rss', 'subscribe', 'follow',
    'facebook', 'twitter', 'youtube', 'instagram', 'linkedin',
    'whatsapp', 'telegram', 'email', 'phone', 'fax',
    'rti', 'site map', 'hyperlinking policy', 'terms of use',
    'website policies', 'help', 'faq', 'feedback', 'complaint',
    'tender', 'recruitment', 'career', 'vacancy', 'apply',
]

BLOCKED_URL_PATTERNS = [
    r'javascript:',
    r'mailto:',
    r'tel:',
    r'facebook\.com',
    r'twitter\.com',
    r'youtube\.com',
    r'instagram\.com',
    r'linkedin\.com',
    r'whatsapp\.com',
    r't\.me',
    r'/#',
    r'#$',
    r'\?page=\d+',  # pagination like ?page=2
    r'/page/\d+',   # pagination like /page/2
]

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

# ─── SMART FILTER ───────────────────────────────────────

def is_valid_content(text, url):
    """Check if this is actual content, not navigation"""
    if not text or not url:
        return False
    
    text_lower = text.lower().strip()
    url_lower = url.lower().strip()
    
    # Must have meaningful text
    if len(text) < 10:
        return False
    
    # Skip blocked text
    for blocked in BLOCKED_TEXT:
        if blocked in text_lower:
            print(f"    [FILTER] Blocked text: '{blocked}' in '{text[:40]}'")
            return False
    
    # Skip blocked URL patterns
    for pattern in BLOCKED_URL_PATTERNS:
        if re.search(pattern, url_lower):
            print(f"    [FILTER] Blocked URL pattern: {pattern}")
            return False
    
    # Must look like a document/notification
    # Should have some meaningful content indicators
    content_indicators = [
        'notification', 'advertisement', 'result', 'answer key',
        'question paper', 'schedule', 'syllabus', 'exam', 'recruitment',
        'pdf', 'download', 'circular', 'order', 'letter', 'memo',
        '2024', '2025', '2026', 'march', 'april', 'may', 'june', 'july',
        'august', 'september', 'october', 'november', 'december',
        'january', 'february', 'group', 'post', 'vacancy',
        'preliminary', 'mains', 'interview', 'selection', 'merit',
        'list', 'final', 'provisional', 'tentative', 'scheme',
    ]
    
    has_indicator = any(ind in text_lower for ind in content_indicators)
    
    if not has_indicator:
        print(f"    [FILTER] No content indicator in: '{text[:50]}'")
        return False
    
    # Must be from mpsc.gov.in domain (or resolved to it)
    if 'mpsc.gov.in' not in url_lower and not url_lower.startswith('/'):
        # Could be relative URL, allow it
        pass
    
    return True

# ─── MAIN SCRAPER ───────────────────────────────────────

async def scrape_page(browser, section_name, url):
    print(f"\n[CHECK] {section_name}")
    print(f"  URL: {url}")
    
    items = []
    context = None
    
    try:
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080},
        )
        
        page = await context.new_page()
        
        print(f"  [BROWSER] Loading...")
        response = await page.goto(url, wait_until='networkidle', timeout=60000)
        
        if not response:
            print(f"  [ERROR] No response")
            return items
        
        print(f"  [BROWSER] HTTP {response.status}")
        await page.wait_for_timeout(5000)
        
        # Extract links with smart filtering
        print(f"  [BROWSER] Extracting content links...")
        
        links = await page.evaluate("""
            () => {
                const results = [];
                const allLinks = document.querySelectorAll('a');
                
                allLinks.forEach(link => {
                    const href = link.href || link.getAttribute('href') || '';
                    const text = (link.innerText || link.textContent || '').trim();
                    
                    // Skip empty or hash-only links
                    if (!href || href === '#' || href === 'javascript:void(0)') {
                        return;
                    }
                    
                    // Skip navigation elements
                    const parent = link.closest('nav, header, footer, .pagination, .menu, .sidebar');
                    if (parent) {
                        return; // Skip nav/header/footer links
                    }
                    
                    // Skip if inside pagination
                    if (link.closest('.pagination, .pager, .page-nav, nav[role="navigation"]')) {
                        return;
                    }
                    
                    results.push({
                        href: href,
                        text: text.substring(0, 300),
                        isPDF: href.toLowerCase().includes('.pdf'),
                        hasDate: /\\d{1,2}[-/.]\\d{1,2}[-/.]\\d{2,4}/.test(text)
                    });
                });
                
                return results;
            }
        """)
        
        print(f"  [BROWSER] Raw links: {len(links)}")
        
        # Apply smart filter
        valid_items = []
        for link in links:
            text = link.get('text', '')
            href = link.get('href', '')
            
            if is_valid_content(text, href):
                item_hash = hashlib.sha256(f"{text}|{href}".encode()).hexdigest()[:16]
                
                valid_items.append({
                    "title": text[:200],
                    "url": href[:500],
                    "date": TODAY,
                    "hash": item_hash,
                    "section": section_name,
                    "is_pdf": link.get('isPDF', False),
                    "has_date": link.get('hasDate', False)
                })
        
        print(f"  [BROWSER] Valid content items: {len(valid_items)}")
        
        if valid_items:
            print(f"  [SAMPLE] First 3 valid items:")
            for i, item in enumerate(valid_items[:3], 1):
                print(f"    {i}. {item['title'][:60]}")
                print(f"       PDF: {item['is_pdf']} | Date: {item['has_date']}")
        
        await context.close()
        return valid_items
        
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
    print("MPSC Monitor - Smart Filter")
    print(f"Date: {TODAY}")
    print("=" * 60)
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Telegram not configured")
        return 0
    
    state = load_state()
    total_new = 0
    
    async with async_playwright() as p:
        print("[BROWSER] Launching...")
        
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ]
        )
        
        print("[BROWSER] Ready")
        
        for section_name, url in MPSC_URLS.items():
            items = await scrape_page(browser, section_name, url)
            
            section_new = 0
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
                
                send_telegram(
                    f"[{item['section']}] {item['title'][:80]}",
                    f"Date: {item['date']}",
                    item["url"]
                )
                
                section_new += 1
                total_new += 1
            
            print(f"  [SECTION] New: {section_new}")
        
        await browser.close()
    
    save_state(state)
    
    print(f"\n{'='*60}")
    print(f"New: {total_new} | Total: {len(state.get('seen', {}))}")
    print(f"{'='*60}")
    
    return 0


if __name__ == "__main__":
    asyncio.run(main())
