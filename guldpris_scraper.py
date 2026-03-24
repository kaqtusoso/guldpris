"""
Hämtar aktuella guldpriser från 14 svenska guldtjänster.
Kör: python guldpris_scraper.py

Kräver playwright för JS-renderade sidor (Pantit, Svenska Guld, WebbGuld):
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
    """Regex-parsning av 'XK 1 234 kr/g' eller 'X karat 1 234 kr/gram'."""
    prices: dict[str, float] = {}
    for m in re.finditer(
        r"\b(24K|23K|22K|21K|20K|18K|14K|12K|10K|9K|8K)\b\s*([\d\s]+(?:[.,]\d{1,2})?)\s*kr/g",
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
            r"(\d{1,2})\s*karat\s*([\d\s]+(?:[.,]\d{1,2})?)\s*kr/gram",
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
    soup = get("https://www.guldbrev.se/guldpris/")
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
    soup = get("https://noblex.se/salja-guld/")
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
    return {k: round(p18 * (int(k[:-1]) / 18), 2) for k in KARAT_ORDER if k not in ("12K", "10K", "8K")}


# ── 9. Pantbanken ─────────────────────────────────────────────────────────────
def fetch_pantbanken() -> dict[str, float]:
    """
    Pantbanken visar sina priser på startsidan som text:
    "24K 1050 kr/g 21K 900 kr/g 18K 750 kr/g 14K 600 kr/g"
    samt på /lana/guldpris/ som tabell.
    """
    soup = get("https://www.pantbanken.se/lana/guldpris/")
    if not soup:
        # Fallback: försök startsidan
        soup = get("https://www.pantbanken.se/")
    if not soup:
        return {}

    # Försök tabell först
    prices = from_table(soup)
    if prices:
        return prices

    # Fallback: regex på fritext (matchar "24K 1050 kr/g" etc.)
    text = clean(soup.get_text(" ", strip=True))
    prices = from_text(text)
    if prices:
        return prices

    # Sista utväg: leta efter mönstret "XK NNNN kr/g" utan mellanslag runt siffran
    for m in re.finditer(
        r"\b(24K|21K|18K|14K|9K|8K)\b\s+(\d[\d\s]*)\s*kr/g",
        text, flags=re.IGNORECASE,
    ):
        key = m.group(1).upper()
        if key not in prices:
            try:
                prices[key] = to_float(m.group(2))
            except ValueError:
                pass
    return prices


# ── 10. Sefina Pantbank ───────────────────────────────────────────────────────
def fetch_sefina() -> dict[str, float]:
    """
    Sefina visar priser som "Guld 24 karat. 875 kr per gram." på /guldpriser/.
    Sidan blockerar enkla requests – använder playwright direkt.
    """
    soup = playwright_get("https://www.sefina.se/guldpriser/")
    if not soup:
        return {}

    text = clean(soup.get_text(" ", strip=True))
    prices: dict[str, float] = {}

    # Mönster 1: "Guld 24 karat. 875 kr per gram" eller "24 karat 875 kr per gram"
    for m in re.finditer(
        r"(?:guld\s+)?(\d{1,2})\s*[Kk]arat[.\s,]+([\d\s]+(?:[.,]\d{1,2})?)\s*kr\s*per\s*gram",
        text, flags=re.IGNORECASE,
    ):
        key = KARAT_ALIASES.get(m.group(1))
        if key and key not in prices:
            try:
                prices[key] = to_float(m.group(2))
            except ValueError:
                pass

    # Mönster 2: "24K 875 kr/g" (standardformat)
    if not prices:
        prices = from_text(text)
    if not prices:
        prices = from_table(soup)
    return prices


# ── 11. WebbGuld ──────────────────────────────────────────────────────────────
def fetch_webbguld() -> dict[str, float]:
    """
    WebbGuld renderar priser dynamiskt med JS (React).
    Priserna visas i format: "24K  1 188 kr/g" eller "18K  891 kr/g".
    Väntar på att priserna faktiskt laddas in (networkidle räcker inte alltid).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}

    import concurrent.futures

    def _fetch():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://webbguld.se/guldpris", timeout=30_000)
            # Vänta tills ett pris-element syns (innehåller "kr/g")
            try:
                page.wait_for_selector("text=kr/g", timeout=15_000)
            except Exception:
                pass
            html = page.content()
            browser.close()
        return html

    try:
        with __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1) as ex:
            html = ex.submit(_fetch).result(timeout=60)
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        print(f"  [FEL] Playwright webbguld: {exc}", file=sys.stderr)
        return {}

    text = clean(soup.get_text(" ", strip=True))
    prices: dict[str, float] = {}

    # Primär: standardformat "24K 1 188 kr/g"
    prices = from_text(text)

    # Fallback: "24K ... 1188 kr" (utan /g)
    if not prices:
        for m in re.finditer(
            r"\b(24K|23K|22K|21(?:\.6)?K|21K|20K|18K|14K|10K|9K|8K)\b[^\d]{0,30}?(\d[\d\s]{2,7})\s*kr\b",
            text, flags=re.IGNORECASE,
        ):
            raw = m.group(1).upper().replace(".6", "")
            key = raw if raw in KARAT_ORDER else None
            if key and key not in prices:
                try:
                    val = to_float(m.group(2))
                    if 100 < val < 10000:
                        prices[key] = val
                except ValueError:
                    pass

    return prices


# ── 12. Q Pantbank ────────────────────────────────────────────────────────────
def fetch_qpantbank() -> dict[str, float]:
    """
    Q Pantbank har en enkel HTML-tabell på /guldpriser/:
    | GULD | SEK |
    | 24K  | 750kr/g |
    """
    soup = get("https://qpantbank.se/guldpriser/")
    if not soup:
        return {}

    prices = from_table(soup)
    if prices:
        return prices

    text = clean(soup.get_text(" ", strip=True))
    return from_text(text)


# ── 13. Guldfynd ──────────────────────────────────────────────────────────────
def fetch_guldfynd() -> dict[str, float]:
    """
    Guldfynd visar inköpspriser på /byraladsguld/ i en tabell med kolumner
    "Karat" och "Kontant ersättning per gram".
    Provar också /salja-guld/ som fallback om URL:en ändrats.
    """
    for url in [
        "https://www.guldfynd.se/byraladsguld/",
        "https://www.guldfynd.se/salja-guld/",
        "https://www.guldfynd.se/kop-guld/",
    ]:
        soup = get(url)
        if soup:
            break
    if not soup:
        return {}

    prices: dict[str, float] = {}

    # Försök hitta tabellrader med karat i första kolumnen
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = clean(cells[0].get_text())
        key = norm_karat(label)
        if not key:
            continue
        # Sök igenom resterande celler efter ett numeriskt pris
        for cell in cells[1:]:
            val_text = clean(cell.get_text())
            m = re.search(r"([\d][\d\s]*(?:[.,]\d{1,2})?)", val_text)
            if m:
                try:
                    val = to_float(m.group(1))
                    if 50 < val < 10000 and key not in prices:
                        prices[key] = val
                        break
                except ValueError:
                    pass

    if not prices:
        text = clean(soup.get_text(" ", strip=True))
        prices = from_text(text)

    return prices


# ── 14. Capitaurum ────────────────────────────────────────────────────────────
def fetch_capitaurum() -> dict[str, float]:
    """
    Capitaurum visar priser på /salja-guld/ i en tabell med format:
      "1 g Guld med finhalt 750/18k | 897.92kr"
    Karathalten anges som finhalt (999/24k, 958/23k, 917/22k,
    875/21k, 750/18k, 585/14k, 375/9k).
    """
    # Finhalt → karat-mappning
    FINHALT_TO_KARAT = {
        "999": "24K", "958": "23K", "917": "22K",
        "875": "21K", "750": "18K", "585": "14K", "375": "9K",
    }

    soup = get("https://capitaurum.se/salja-guld/")
    if not soup:
        return {}

    text = clean(soup.get_text(" ", strip=True))
    prices: dict[str, float] = {}

    # Primär: "finhalt 750/18k ... 897.92kr" eller "750/18k ... 897,92 kr"
    for m in re.finditer(
        r"(?:finhalt\s+)?(\d{3})/(\d{1,2})k[^\d]{0,30}?([\d][\d\s]*[.,]?\d{0,2})\s*kr",
        text, flags=re.IGNORECASE,
    ):
        finhalt = m.group(1)
        key = FINHALT_TO_KARAT.get(finhalt)
        if key and key not in prices:
            try:
                val = to_float(m.group(3))
                if 100 < val < 10000:
                    prices[key] = val
            except ValueError:
                pass

    # Fallback: standardformat
    if not prices:
        prices = from_text(text)
    if not prices:
        prices = from_table(soup)

    return prices


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
    # --- Befintliga ---
    ("Guldbrev",           fetch_guldbrev),
    ("Diamantbrev",        fetch_diamantbrev),
    ("Pantit",             fetch_pantit),
    ("Noblex",             fetch_noblex),
    ("Finguld",            fetch_finguld),
    # ("Svenska Guld",       fetch_svenska_guld),
    ("Kaplans Ädelmetall", fetch_kaplans),
    ("Guldcentralen",      fetch_guldcentralen),
    # --- Nya ---
    ("Pantbanken",         fetch_pantbanken),
    ("Sefina Pantbank",    fetch_sefina),
    ("WebbGuld",           fetch_webbguld),
    # ("Q Pantbank",         fetch_qpantbank),
    ("Guldfynd",           fetch_guldfynd),
    ("Capitaurum",         fetch_capitaurum),
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
