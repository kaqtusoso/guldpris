"""
Hämtar aktuella guldpriser från 8 svenska guldtjänster.
Kör: python guldpriser.py

Kräver playwright för JS-renderade sidor (Pantit, Svenska Guld):
  pip install playwright && playwright install chromium

Sparar resultatet automatiskt som:
  Guldpriser/guldpriser_YYYY-MM-DD_HH-MM.json
"""

import json
import os
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 30

KARAT_ALIASES = {
    "24": "24K", "23": "23K", "22": "22K", "21": "21K", "20": "20K",
    "18": "18K", "14": "14K", "12": "12K", "10": "10K", "9": "9K", "8": "8K",
}
KARAT_ORDER = ["24K", "23K", "22K", "21K", "20K", "18K", "14K", "12K", "10K", "9K", "8K"]


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def to_float(value: str) -> float:
    return float(value.replace("\xa0", "").replace("\u202f", "").replace(" ", "").replace(",", "."))


def norm_karat(raw: str) -> str | None:
    m = re.search(r"\d+", raw)
    return KARAT_ALIASES.get(m.group()) if m else None


def get(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except requests.RequestException as exc:
        print(f"  [FEL] {url}: {exc}", file=sys.stderr)
        return None


def playwright_get(url: str) -> BeautifulSoup | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [INFO] Playwright saknas. Kör: pip install playwright && playwright install chromium", file=sys.stderr)
        return None

    import concurrent.futures

    def _fetch():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30_000)
            html = page.content()
            browser.close()
        return html

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch)
            html = future.result(timeout=60)
        return BeautifulSoup(html, "html.parser")
    except Exception as exc:
        print(f"  [FEL] Playwright {url}: {exc}", file=sys.stderr)
        return None


def from_text(text: str) -> dict[str, float]:
    """Regex-parsning av 'XK 1 234 kr/g' eller 'X karat 1 234 kr/gram'.

    FIX: Prisgruppen använder [\d\xa0\u202f]+ istället för [\d\s]+ så att
    vanliga mellanslag (som separerar olika karat-poster) inte sväljs av
    en girig match – vilket tidigare gjorde att t.ex. 20K missades.
    """
    prices: dict[str, float] = {}
    for m in re.finditer(
        r"\b(24K|23K|22K|21K|20K|18K|14K|12K|10K|9K|8K)\b\s*"
        r"([\d]+(?:[\xa0\u202f]\d+)*(?:[.,]\d{1,2})?)\s*kr/g",
        text, flags=re.IGNORECASE,
    ):
        key = m.group(1).upper()
        if key not in prices:
            try:
                prices[key] = to_float(m.group(2))
            except ValueError:
                pass
    if not prices:
        for m in re.finditer(
            r"(\d{1,2})\s*karat\s*([\d]+(?:[\xa0\u202f]\d+)*(?:[.,]\d{1,2})?)\s*kr/gram",
            text, flags=re.IGNORECASE,
        ):
            key = KARAT_ALIASES.get(m.group(1))
            if key and key not in prices:
                try:
                    prices[key] = to_float(m.group(2))
                except ValueError:
                    pass
    return prices


def from_table(soup: BeautifulSoup) -> dict[str, float]:
    """Parsar <tr>-rader med karat i kolumn 1 och kr-pris i kolumn 2."""
    prices: dict[str, float] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = clean(cells[0].get_text())
        value = clean(cells[1].get_text())
        if "kr" not in value:
            continue
        key = norm_karat(label)
        m = re.search(r"([\d\s]+(?:[.,]\d{1,2})?)", value)
        if key and m:
            try:
                prices[key] = to_float(m.group(1))
            except ValueError:
                pass
    return prices


# ── 1. Guldbrev ───────────────────────────────────────────────────────────────
def fetch_guldbrev() -> dict[str, float]:
    soup = playwright_get("https://www.guldbrev.se/guldpris/")
    if not soup:
        return {}
    return from_text(clean(soup.get_text(" ", strip=True)))


# ── 2. Diamantbrev ────────────────────────────────────────────────────────────
def fetch_diamantbrev() -> dict[str, float]:
    soup = get("https://diamantbrev.se/pris-villkor/")
    if not soup:
        return {}
    prices = from_table(soup)
    if not prices:
        prices = from_text(clean(soup.get_text(" ", strip=True)))
    return prices


# ── 3. Pantit ─────────────────────────────────────────────────────────────────
def fetch_pantit() -> dict[str, float]:
    soup = playwright_get("https://www.pantit.se/guldpris")
    if not soup:
        return {}
    text = clean(soup.get_text(" ", strip=True))

    prices = from_text(text)
    if prices:
        return prices

    karat_block = re.search(r"Karat\s+Pris[^\d]+([\d\s]+)", text)
    if karat_block:
        nums = karat_block.group(1).split()
        i = 0
        while i + 1 < len(nums):
            key = KARAT_ALIASES.get(nums[i])
            if key:
                try:
                    if len(nums[i + 1]) <= 1 and i + 2 < len(nums):
                        prices[key] = to_float(nums[i + 1] + nums[i + 2])
                        i += 3
                    else:
                        prices[key] = to_float(nums[i + 1])
                        i += 2
                except ValueError:
                    i += 1
            else:
                i += 1
    return prices


# ── 4. Noblex ─────────────────────────────────────────────────────────────────
def fetch_noblex() -> dict[str, float]:
    soup = playwright_get("https://noblex.se/salja-guld/")
    if not soup:
        return {}
    prices = from_table(soup)
    if not prices:
        prices = from_text(clean(soup.get_text(" ", strip=True)))
    return prices


# ── 5. Finguld ────────────────────────────────────────────────────────────────
def fetch_finguld() -> dict[str, float]:
    soup = get("https://finguld.se/guldpris/")
    if not soup:
        return {}
    text = clean(soup.get_text(" ", strip=True))
    prices: dict[str, float] = {}
    for m in re.finditer(
        r"\b(24K|23K|22K|21K|20K|18K|14K|12K|10K|9K|8K)\b\s*[–\-]\s*([\d\s]+(?:[.,]\d{1,2})?)\s*kr/g",
        text, flags=re.IGNORECASE,
    ):
        key = m.group(1).upper()
        if key not in prices:
            try:
                prices[key] = to_float(m.group(2))
            except ValueError:
                pass
    if not prices:
        prices = from_table(soup)
    return prices


# ── 6. Svenska Guld ───────────────────────────────────────────────────────────
def fetch_svenska_guld() -> dict[str, float]:
    soup = playwright_get("https://www.svenskaguld.se/salja-guld")
    if not soup:
        return {}
    text = clean(soup.get_text(" ", strip=True))

    block = re.search(
        r"((?:[\d  ,]+kr/g\s*){2,})((?:(?:24|23|22|21|20|18|14|9)k\s*){2,})",
        text, flags=re.IGNORECASE,
    )
    if block:
        price_strs = re.findall(r"([\d  ]+(?:[.,]\d{1,2})?)\s*kr/g", block.group(1), re.IGNORECASE)
        karat_nums = re.findall(r"(\d+)k", block.group(2), re.IGNORECASE)
        prices: dict[str, float] = {}
        for ps, kn in zip(price_strs, karat_nums):
            key = KARAT_ALIASES.get(kn)
            if key:
                try:
                    prices[key] = to_float(ps)
                except ValueError:
                    pass
        if prices:
            return prices

    return from_text(text)


# ── 7. Kaplans Ädelmetall ─────────────────────────────────────────────────────
def fetch_kaplans() -> dict[str, float]:
    soup = get("https://www.kaplansadelmetall.se/guldpriser/dagspris")
    if not soup:
        return {}
    prices: dict[str, float] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = clean(cells[0].get_text())
        if "guld" not in label.lower():
            continue
        value = clean(cells[1].get_text())
        key = norm_karat(label)
        m = re.search(r"([\d\s]+(?:[.,]\d{1,2})?)", value)
        if key and m and key not in prices:
            try:
                prices[key] = to_float(m.group(1))
            except ValueError:
                pass
    return prices


# ── 8. Guldcentralen ──────────────────────────────────────────────────────────
def fetch_guldcentralen() -> dict[str, float]:
    soup = get("https://www.guldcentralen.se/salj-guld")
    if not soup:
        return {}
    text = clean(soup.get_text(" ", strip=True))
    m = re.search(r"Pris f[oö]r 18k[^=]+=\s*(\d+)\s*sek/gram", text, re.IGNORECASE)
    if not m:
        return {}
    p18 = float(m.group(1))
    return {k: round(p18 * (int(k[:-1]) / 18), 2) for k in KARAT_ORDER if k != "12K" and k != "10K" and k != "8K"}


# ── Utskrift ──────────────────────────────────────────────────────────────────

def print_prices(name: str, prices: dict[str, float]) -> None:
    print(f"\n{'─' * 32}")
    print(f"  {name}")
    print(f"{'─' * 32}")
    if not prices:
        print("  Inga priser hittades.")
        return
    for karat in KARAT_ORDER:
        if karat in prices:
            print(f"  {karat}: {prices[karat]:>8.2f} kr/g")


# ── JSON-export ───────────────────────────────────────────────────────────────

def save_json(all_prices: dict[str, dict[str, float]], timestamp: datetime) -> None:
    """Sparar alla priser till Guldpriser/guldpriser_YYYY-MM-DD_HH-MM.json"""
    folder = "Guldpriser"
    os.makedirs(folder, exist_ok=True)

    filename = f"guldpriser_{timestamp.strftime('%Y-%m-%d_%H-%M')}.json"
    filepath = os.path.join(folder, filename)

    output = {
        "hämtad": timestamp.strftime("%Y-%m-%d %H:%M"),
        "priser": {
            aktör: {
                karat: priser[karat]
                for karat in KARAT_ORDER
                if karat in priser
            }
            for aktör, priser in all_prices.items()
        },
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Sparad: {filepath}")


# ── Aktörer ───────────────────────────────────────────────────────────────────

AKTÖRER = [
    ("Guldbrev",           fetch_guldbrev),
    ("Diamantbrev",        fetch_diamantbrev),
    ("Pantit",             fetch_pantit),
    ("Noblex",             fetch_noblex),
    ("Finguld",            fetch_finguld),
    # ("Svenska Guld",       fetch_svenska_guld),  # Pausad – beställningar stängda tillfälligt
    ("Kaplans Ädelmetall", fetch_kaplans),
    ("Guldcentralen",      fetch_guldcentralen),
]


def main() -> None:
    now = datetime.now()
    print(f"Guldpriser  –  {now.strftime('%Y-%m-%d %H:%M')}")

    all_prices: dict[str, dict[str, float]] = {}
    for name, fetcher in AKTÖRER:
        prices = fetcher()
        all_prices[name] = prices
        print_prices(name, prices)

    print()
    save_json(all_prices, now)


if __name__ == "__main__":
    main()
