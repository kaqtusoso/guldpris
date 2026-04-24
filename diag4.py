"""
diag4.py – Dumpar innehållet i WebbGulds dolda karat-tabbar
Kör: python diag4.py
"""
import sys, re
sys.path.insert(0, ".")
from guldpris_scraper import playwright_get, clean

soup = playwright_get("https://webbguld.se/guldpris", wait_ms=10000)
if not soup:
    print("Ingen HTML")
    sys.exit(1)

print("=== Karat-tabbar (id='tabXX') ===")
for karat_num in ["24", "23", "22", "21", "20", "18", "14", "10", "9", "8"]:
    for id_fmt in [f"tab{karat_num}", f"{karat_num}kinfo", f"tab{karat_num}K"]:
        el = soup.find(id=id_fmt)
        if el:
            text = clean(el.get_text(" ", strip=True))
            print(f"\n  id='{id_fmt}' ({karat_num}K):")
            print(f"  {text[:300]}")
            break
    else:
        print(f"\n  {karat_num}K: (hittades inte)")

print("\n=== Alla element med id som börjar på 'tab' ===")
for el in soup.find_all(id=re.compile(r'^tab')):
    text = clean(el.get_text(" ", strip=True))
    if text:
        print(f"  id='{el.get('id')}': {text[:150]}")
