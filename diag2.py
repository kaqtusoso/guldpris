"""
diag2.py – Diagnostik för Guldcentralen och WebbGuld
Kör: python diag2.py
"""
import sys, re
sys.path.insert(0, ".")
from guldpris_scraper import playwright_get, clean
from playwright.sync_api import sync_playwright
import concurrent.futures

# ── GULDCENTRALEN: dumpa alla navlänkar på startsidan ────────────────────────
print("=== GULDCENTRALEN: Navlänkar på startsidan ===")

def gc_links():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page.goto("https://www.guldcentralen.se/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        links = page.eval_on_selector_all("a", "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))")
        browser.close()
    return links

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
    links = ex.submit(gc_links).result(timeout=60)

for l in links:
    if l['text'] and l['href']:
        print(f"  '{l['text'][:50]}' → {l['href'][:80]}")

# ── GULDCENTRALEN: prova /salj-metaller direkt ───────────────────────────────
print("\n=== GULDCENTRALEN /salj-metaller ===")
soup = playwright_get("https://www.guldcentralen.se/salj-metaller", wait_ms=6000)
if soup:
    text = clean(soup.get_text(" ", strip=True))
    print(text[:600])
else:
    print("Ingen HTML")

# ── WEBBGULD: dumpa all text för att se alla tillgängliga karatpriser ─────────
print("\n=== WEBBGULD: Full text efter 10s väntan ===")
soup = playwright_get("https://webbguld.se/guldpris", wait_ms=10000)
if soup:
    text = clean(soup.get_text(" ", strip=True))
    # Hitta allt kring karat-ord
    for m in re.finditer(r'.{0,60}(karat|K\b|kr/g).{0,60}', text, re.IGNORECASE):
        print(m.group(0)[:120])
else:
    print("Ingen HTML")

# ── WEBBGULD: prova andra URL-varianter ──────────────────────────────────────
print("\n=== WEBBGULD: Andra URL-varianter ===")
for url in ["https://webbguld.se/priser", "https://webbguld.se/salja-guld", "https://webbguld.se/"]:
    soup = playwright_get(url, wait_ms=5000)
    if soup:
        text = clean(soup.get_text(" ", strip=True))
        if any(k in text for k in ["kr/g", "karat", "18K"]):
            print(f"\n{url}:")
            print(text[:400])
        else:
            print(f"{url}: (inga priser i texten)")
    else:
        print(f"{url}: Ingen HTML")
