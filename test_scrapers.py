"""
test_scrapers.py – Testar enbart de scrapers som gett problem.
Kör: python test_scrapers.py

Visar vad varje scraper hittar (eller inte hittar) utan att
påverka den vanliga driften.
"""

import sys
sys.path.insert(0, ".")

from guldpris_scraper import (
    fetch_guldcentralen,
    fetch_webbguld,
    fetch_sefina,
    fetch_tavex,
    fetch_capitaurum,
    KARAT_ORDER,
)

SCRAPERS = [
    ("Capitaurum",    fetch_capitaurum),
    ("Sefina",        fetch_sefina),
    ("Guldcentralen", fetch_guldcentralen),
    ("WebbGuld",      fetch_webbguld),
    ("Tavex",         fetch_tavex),
]

for name, fn in SCRAPERS:
    print(f"\n{'─'*40}")
    print(f"  {name}")
    print(f"{'─'*40}")
    try:
        prices = fn()
    except Exception as e:
        print(f"  KRASCH: {e}")
        continue

    if not prices:
        print("  ❌  Inga priser hittades")
    else:
        for k in KARAT_ORDER:
            if k in prices:
                print(f"  ✅  {k}: {prices[k]:>8.2f} kr/g")

print()
