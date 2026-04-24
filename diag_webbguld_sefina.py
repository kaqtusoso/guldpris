"""
diag_webbguld_sefina.py – Dumpar rå HTML från WebbGuld och Sefina
Kör: python diag_webbguld_sefina.py
"""
import sys, re
sys.path.insert(0, ".")
from guldpris_scraper import playwright_get, clean

# ── WebbGuld ─────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("WEBBGULD")
print("="*60)
soup = playwright_get("https://webbguld.se/guldpris", wait_ms=10000)
if not soup:
    print("Ingen HTML – Playwright misslyckades helt")
else:
    text = clean(soup.get_text(" ", strip=True))
    print(f"Textstorlek: {len(text)} tecken")

    # Kolla om tab-IDs finns
    print("\n--- Tab-IDs (tab18, tab24 etc.) ---")
    for num in ["8", "9", "10", "14", "18", "20", "21", "22", "23", "24"]:
        tag = soup.find(id=f"tab{num}")
        print(f"  id='tab{num}': {'HITTADES → ' + clean(tag.get_text(' ', strip=True))[:80] if tag else 'saknas'}")

    # Visa text kring kr/g
    print("\n--- Text kring 'kr' / karat (första 30 träffar) ---")
    count = 0
    for m in re.finditer(r'.{0,60}(?:karat|\d+[Kk]\b|kr/g|kr/gram|\d+\s*kr).{0,60}', text, re.IGNORECASE):
        print(" ", m.group(0)[:140])
        count += 1
        if count >= 30:
            break

    # Visa alla element med id som innehåller "tab"
    print("\n--- Alla element med 'tab' i id ---")
    for el in soup.find_all(id=re.compile(r'tab', re.IGNORECASE)):
        t = clean(el.get_text(" ", strip=True))[:80]
        print(f"  id='{el.get('id')}' tag=<{el.name}>: {t}")

    # Visa tabeller
    print("\n--- Tabellrader med siffror ---")
    for row in soup.find_all("tr"):
        t = clean(row.get_text(" ", strip=True))
        if re.search(r'\d', t) and len(t) < 200:
            print(" ", t[:150])


# ── Sefina ────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("SEFINA")
print("="*60)
soup = playwright_get("https://www.sefina.se/guldpriser/", wait_ms=10000)
if not soup:
    print("Ingen HTML – Playwright misslyckades helt (Cloudflare?)")
else:
    text = clean(soup.get_text(" ", strip=True))
    print(f"Textstorlek: {len(text)} tecken")

    # Kolla om sidan är en Cloudflare-sida
    if "cloudflare" in text.lower() or "just a moment" in text.lower():
        print("⚠️  CLOUDFLARE-SIDA – sidan blockeras fortfarande!")

    print("\n--- Text kring 'karat' / 'kr' (första 30 träffar) ---")
    count = 0
    for m in re.finditer(r'.{0,60}(?:karat|\d+[Kk]\b|kr/g|kr/gram|\d+\s*kr).{0,60}', text, re.IGNORECASE):
        print(" ", m.group(0)[:140])
        count += 1
        if count >= 30:
            break

    print("\n--- Alla <li> med siffror ---")
    for li in soup.find_all("li"):
        t = clean(li.get_text(" ", strip=True))
        if re.search(r'\d', t) and len(t) < 150:
            print(" ", t[:120])

    print("\n--- Tabellrader ---")
    for row in soup.find_all("tr"):
        t = clean(row.get_text(" ", strip=True))
        if re.search(r'\d', t) and len(t) < 200:
            print(" ", t[:150])

    # Visa titel på sidan
    title = soup.find("title")
    print(f"\n--- Sidtitel: {title.get_text() if title else 'ingen'} ---")
