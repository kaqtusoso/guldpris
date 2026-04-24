"""
diag3.py – Hittar karat-knappstruktur på WebbGuld + JSON-data
Kör: python diag3.py
"""
import sys, re, json
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright
import concurrent.futures
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        page.goto("https://webbguld.se/guldpris", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(10000)
        html = page.content()
        browser.close()
    return html

with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
    html = ex.submit(run).result(timeout=120)

soup = BeautifulSoup(html, "html.parser")

# ── 1. Leta efter __NEXT_DATA__ JSON ─────────────────────────────────────────
print("=== 1. __NEXT_DATA__ / inbäddad JSON ===")
for script in soup.find_all("script"):
    if script.get("id") == "__NEXT_DATA__" or (script.string and "pageProps" in (script.string or "")):
        text = script.string or ""
        # Leta efter karat-priser i JSON
        for m in re.finditer(r'"(?:price|pris|karat|gold)[^"]*"\s*:\s*[\d.]+', text, re.IGNORECASE):
            print(" ", m.group(0)[:100])
        if len(text) > 100:
            print(f"  (JSON-blob hittad, {len(text)} tecken)")
            # Dumpa de första 1000 tecknen
            print(text[:1000])
        break
else:
    print("  Ingen __NEXT_DATA__ hittades")

# ── 2. Hitta karat-knappar i DOM ─────────────────────────────────────────────
print("\n=== 2. Element som innehåller '18K' eller '18 K' ===")
for el in soup.find_all(string=re.compile(r'\b18\s*[Kk]\b')):
    parent = el.parent
    print(f"  Tag: <{parent.name}> class={parent.get('class')} | text='{el.strip()[:60]}'")
    # Visa hela element med attribut
    attrs = dict(parent.attrs)
    print(f"       attrs={attrs}")

# ── 3. Hitta tabeller / listor med prisdata ───────────────────────────────────
print("\n=== 3. Alla <tr> och <li> som innehåller 'kr' ===")
count = 0
for row in soup.find_all(["tr", "li"]):
    text = row.get_text(" ", strip=True)
    if "kr" in text and len(text) < 150:
        print(f"  <{row.name}>: {text[:100]}")
        count += 1
        if count > 20:
            print("  ... (fler rader)")
            break

# ── 4. Karasmussen: köpprissida ───────────────────────────────────────────────
print("\n=== 4. karasmussen.com/se/vi-koper-guld-och-silver/ ===")
import requests
from guldpris_scraper import HEADERS, clean, from_text, from_table
try:
    r = requests.get("https://karasmussen.com/se/vi-koper-guld-och-silver/", headers=HEADERS, timeout=20)
    r.raise_for_status()
    s = BeautifulSoup(r.text, "html.parser")
    text = clean(s.get_text(" ", strip=True))
    prices = from_text(text)
    print(f"  from_text: {prices}")
    prices2 = from_table(s)
    print(f"  from_table: {prices2}")
    # Dumpa text kring 'karat'/'kr'
    for m in re.finditer(r'.{0,60}(karat|18K|24K|kr/g).{0,60}', text, re.IGNORECASE):
        print(" ", m.group(0)[:120])
except Exception as e:
    print(f"  FEL: {e}")
    # Prova med Playwright
    print("  Provar Playwright...")
    def run_kara():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=UA)
            page.goto("https://karasmussen.com/se/vi-koper-guld-och-silver/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
        return html
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        khtml = ex.submit(run_kara).result(timeout=90)
    ks = BeautifulSoup(khtml, "html.parser")
    text = clean(ks.get_text(" ", strip=True))
    print(text[:800])
