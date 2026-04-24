"""
diag_sefina.py – Dumpar Sefinas sida via Playwright för att se prisformat
Kör: python diag_sefina.py
"""
import sys, re
sys.path.insert(0, ".")
from guldpris_scraper import playwright_get, clean, from_text, from_table

print("=== Sefina /guldpriser/ ===")
soup = playwright_get("https://www.sefina.se/guldpriser/", wait_ms=8000)

if not soup:
    print("Ingen HTML – Cloudflare blockade fortfarande")
    sys.exit(0)

text = clean(soup.get_text(" ", strip=True))

print(f"\nFull textstorlek: {len(text)} tecken")
print("\n--- from_text ---")
print(from_text(text))

print("\n--- from_table ---")
print(from_table(soup))

print("\n--- Text kring 'karat' / 'kr' (första 40 träffar) ---")
count = 0
for m in re.finditer(r'.{0,80}(?:karat|kr/g|kr/gram|\d+[Kk]\b).{0,80}', text, re.IGNORECASE):
    print(" ", m.group(0)[:160])
    count += 1
    if count >= 40:
        break

print("\n--- Alla <tr> med siffror ---")
for row in soup.find_all("tr"):
    t = clean(row.get_text(" ", strip=True))
    if re.search(r'\d', t) and len(t) < 200:
        print(" ", t[:150])

print("\n--- Alla <li> med siffror ---")
for li in soup.find_all("li"):
    t = clean(li.get_text(" ", strip=True))
    if re.search(r'\d', t) and len(t) < 150:
        print(" ", t[:120])
