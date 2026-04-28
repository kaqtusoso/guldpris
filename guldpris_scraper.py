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
from zoneinfo import ZoneInfo

STOCKHOLM = ZoneInfo("Europe/Stockholm")

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


def playwright_get(url: str, wait_for: str | None = None, wait_ms: int = 4000) -> BeautifulSoup | None:
    """Hämtar JS-renderad sida via Playwright. Använder 'domcontentloaded' + valfri selector + väntetid."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [INFO] Playwright saknas. Kör: pip install playwright && playwright install chromium", file=sys.stderr)
        return None

    import concurrent.futures

    def _fetch():
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=12_000)
                except Exception:
                    pass
            # Ge JS alltid lite tid att rendera
            page.wait_for_timeout(wait_ms)
            html = page.content()
            browser.close()
        return html

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch)
            html = future.result(timeout=90)
        return BeautifulSoup(html, "html.parser")
    except Exception as exc:
        print(f"  [FEL] Playwright {url}: {exc}", file=sys.stderr)
        return None


def playwright_click_and_get(start_url: str, link_text_pattern: str, wait_ms: int = 4000) -> BeautifulSoup | None:
    """Navigerar till start_url, klickar på en länk som matchar link_text_pattern, returnerar HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    import concurrent.futures

    def _fetch():
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)
            try:
                page.get_by_text(link_text_pattern, exact=False).first.click(timeout=5_000)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(wait_ms)
            except Exception as e:
                print(f"  [INFO] Klick misslyckades ({e}) – använder nuvarande sida", file=sys.stderr)
            html = page.content()
            browser.close()
        return html

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch)
            html = future.result(timeout=90)
        return BeautifulSoup(html, "html.parser")
    except Exception as exc:
        print(f"  [FEL] playwright_click_and_get {start_url}: {exc}", file=sys.stderr)
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
    """
    Guldcentralen's köppriser finns på karasmussen.com (moderbolaget).
    Format: "18k Guldskrot 906,- /g" (punkt = tusensep, komma = decimal/noll).
    """
    def parse_scandinavian_prices(text: str) -> dict[str, float]:
        """Parsar 'XK Guldskrot N.NNN,- /g' och 'XK ... N.NNN,NN /g'."""
        prices: dict[str, float] = {}
        # Mönster: "18k Guldskrot 906,- /g"  eller  "22k ... 1.042,- /g"
        for m in re.finditer(
            r"\b(\d{1,2})\s*[Kk][^\d]{0,30}?([\d]{1,4}(?:[.\s]\d{3})?)"
            r"(?:,(\d{2})|,-)\s*/g",
            text, flags=re.IGNORECASE,
        ):
            key = KARAT_ALIASES.get(m.group(1))
            if not key or key in prices:
                continue
            # Bygg siffran: ta bort punkter (tusenseparator), lägg till decimal
            int_part = m.group(2).replace(".", "").replace(" ", "")
            dec_part = m.group(3) if m.group(3) else "00"
            try:
                val = float(f"{int_part}.{dec_part}")
                if 50 < val < 10000:
                    prices[key] = val
            except ValueError:
                pass
        return prices

    for url in [
        "https://karasmussen.com/se/vi-koper-guld-och-silver/",
        "https://karasmussen.com/se/vi-koper-guld-och-silver",
        "https://karasmussen.com/se/metallpriser/",
    ]:
        soup = get(url)
        if not soup:
            soup = playwright_get(url, wait_ms=5000)
        if not soup:
            continue
        text = clean(soup.get_text(" ", strip=True))
        # Primär: skandinaviskt prisformat
        prices = parse_scandinavian_prices(text)
        if prices:
            return prices
        # Fallback: standardformat
        prices = from_text(text)
        if prices:
            return prices
        prices = from_table(soup)
        if prices:
            return prices
    return {}
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
    Sefina skyddas av Cloudflare Bot Management (hårdaste skiktet).
    Testat: playwright-stealth, camoufox, nodriver, curl_cffi – alla blockeras.
    CF-challengen "löses" men origin-servern svarar aldrig.
    Kräver betald scraping-API (t.ex. Zenrows) för att komma igenom.
    """
    print("  [INFO] Sefina: Cloudflare Bot Management blockerar automatisk hämtning.", file=sys.stderr)
    return {}
# ── 11. WebbGuld ──────────────────────────────────────────────────────────────
def fetch_webbguld() -> dict[str, float]:
    """
    WebbGuld har priserna hårdkodade direkt i en JS-funktion (change(e)) på
    /salja-guld – inget API, inget Playwright behövs.

    Priset varierar med vikt (gram). Vi returnerar priset för 1-4g (lägsta
    viktintervallet) som jämförelsepris. Högre vikt ger något bättre pris.

    OBS: Sajten har ett stavfel i JS – "rice8" istället för "price8" i
    300g+-blocket. Det hanteras med en fallback-regex.
    """
    _KARATS_JS = ["8", "9", "10", "14", "18", "20", "21", "22", "23"]
    _KARAT_LABELS = {
        "8": "8K", "9": "9K", "10": "10K", "14": "14K", "18": "18K",
        "20": "20K", "21": "21K", "22": "22K", "23": "23K",
    }

    def _extract_block(body: str) -> dict[str, float]:
        prices: dict[str, float] = {}
        for k in _KARATS_JS:
            m = re.search(rf"price{k}\s*=\s*([\d.]+)", body)
            if m:
                prices[k] = float(m.group(1))
            elif k == "8":
                m2 = re.search(r"rice8\s*=\s*([\d.]+)", body)
                if m2:
                    prices[k] = float(m2.group(1))
        return prices

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get("https://webbguld.se/salja-guld", headers=headers, timeout=20)
        print(f"  [WebbGuld] HTTP {resp.status_code}, {len(resp.text)} tecken", file=sys.stderr)
        resp.raise_for_status()
        soup_wg = BeautifulSoup(resp.text, "html.parser")

        js_content = ""
        for script in soup_wg.find_all("script"):
            content = script.string or ""
            if "price24" in content and "price18" in content and "change(" in content:
                js_content = content
                break

        if not js_content:
            # Logga varför vi misslyckades
            script_contents = [s.string or "" for s in soup_wg.find_all("script")]
            has_price24 = any("price24" in c for c in script_contents)
            has_price18 = any("price18" in c for c in script_contents)
            has_change  = any("change(" in c for c in script_contents)
            print(
                f"  [WebbGuld] JS-block saknas – price24={has_price24}, "
                f"price18={has_price18}, change()={has_change}, "
                f"antal scripts={len(script_contents)}",
                file=sys.stderr,
            )
            return {}

        result: dict[str, float] = {}

        # 24K: fast pris
        m24 = re.search(r"price24\s*=\s*([\d.]+)", js_content)
        if m24:
            result["24K"] = float(m24.group(1))

        # Övriga karat: hitta det första if-blocket (e > 0 && e < 5 = "1-4g")
        block_pattern = re.compile(
            r"(?:if|else if)\s*\(e\s*>\s*(\d+)(?:\s*&&\s*e\s*<\s*(\d+))?\)\s*\{([^}]+)\}",
            re.DOTALL,
        )
        for match in block_pattern.finditer(js_content):
            lower = int(match.group(1))
            upper = int(match.group(2)) if match.group(2) else None
            if lower == 0 and upper == 5:  # 1-4g-blocket
                for k, price in _extract_block(match.group(3)).items():
                    label = _KARAT_LABELS.get(k)
                    if label:
                        result[label] = price
                break

        final = {k: v for k, v in result.items() if 50 < v < 10000}
        print(f"  [WebbGuld] Hämtade {len(final)} karat: {list(final.keys())}", file=sys.stderr)
        return final

    except Exception as exc:
        print(f"  [FEL] WebbGuld: {exc}", file=sys.stderr)
        return {}
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
    Guldfynd är en JS-renderad e-handelssajt (Viskan).
    Provar /byraladsguld/ med Playwright, sedan requests-fallback.
    """
    for url in [
        "https://www.guldfynd.se/byraladsguld/",
        "https://www.guldfynd.se/salja-guld/",
        "https://www.guldfynd.se/kop-guld/",
    ]:
        soup = playwright_get(url)
        if not soup:
            soup = get(url)
        if not soup:
            continue
        prices = from_table(soup)
        if prices:
            return prices
        text = clean(soup.get_text(" ", strip=True))
        prices = from_text(text)
        if prices:
            return prices
        # Regex: "18 karat ... 900 kr" eller "18K ... 900 kr/g"
        for m in re.finditer(
            r"\b(\d{1,2})\s*[Kk](?:arat)?[^\d]{0,15}?([\d][\d\s]*(?:[.,]\d{1,2})?)\s*kr",
            text, flags=re.IGNORECASE,
        ):
            key = KARAT_ALIASES.get(m.group(1))
            if key and key not in prices:
                try:
                    val = to_float(m.group(2))
                    if 50 < val < 10000:
                        prices[key] = val
                except ValueError:
                    pass
        if prices:
            return prices
    return {}
# ── 14. Capitaurum ────────────────────────────────────────────────────────────
def fetch_capitaurum() -> dict[str, float]:
    """
    Capitaurum visar priser på /salja-guld/ i en tabell med format:
      "1 g Investeringsguld med finhalt 999/24k (ocirkulerat skick) 1,352.58kr"
      "1 g Guld med finhalt 750/18k 963.28kr"
    Karathalten anges som finhalt (999/24k, 958/23k, 917/22k,
    875/21k, 750/18k, 585/14k, 375/9k).
    OBS: priser ≥1000 har komma som tusenseparator: "1,352.58" = 1352.58 kr/g.
    """
    FINHALT_TO_KARAT = {
        "999": "24K", "958": "23K", "917": "22K",
        "875": "21K", "750": "18K", "585": "14K", "375": "9K",
    }

    soup = get("https://capitaurum.se/salja-guld/")
    if not soup:
        return {}

    text = clean(soup.get_text(" ", strip=True))
    prices: dict[str, float] = {}

    # Primär: "finhalt 999/24k ... 1,352.58kr" (komma = tusenseparator, punkt = decimal)
    for m in re.finditer(
        r"finhalt\s+(\d{3})/\d+k[^\d]{0,50}?"
        r"([\d]{1,4}(?:,\d{3})?(?:\.\d{1,2})?)\s*kr",
        text, flags=re.IGNORECASE,
    ):
        finhalt = m.group(1)
        key = FINHALT_TO_KARAT.get(finhalt)
        if not key or key in prices:
            continue
        # Ta bort tusenseparator (komma), behåll decimal (punkt)
        price_str = m.group(2).replace(",", "")
        try:
            val = float(price_str)
            if 100 < val < 10000:
                prices[key] = round(val, 2)
        except ValueError:
            pass

    # Fallback: standardformat
    if not prices:
        prices = from_text(text)
    if not prices:
        prices = from_table(soup)

    return prices


# ── 15. Tavex ────────────────────────────────────────────────────────────────────
def fetch_tavex() -> dict[str, float]:
    """
    Tavex blockerar requests (403) – kräver Playwright med riktig user-agent.
    Provar flera URL-varianter.
    """
    for url in [
        "https://tavex.se/salja-guld/",
        "https://tavex.se/guld-priser/",
        "https://tavex.se/guld-silver-prislista/",
        "https://tavex.se/",
    ]:
        soup = playwright_get(url)
        if not soup:
            continue
        prices = from_table(soup)
        if prices:
            return prices
        text = clean(soup.get_text(" ", strip=True))
        prices = from_text(text)
        if prices:
            return prices
        for m in re.finditer(
            r"\b(\d{1,2})\s*[Kk](?:arat)?[^\d]{0,15}?([\d][\d\s]*(?:[.,]\d{1,2})?)\s*kr(?:/g|/gram)?",
            text, flags=re.IGNORECASE,
        ):
            key = KARAT_ALIASES.get(m.group(1))
            if key and key not in prices:
                try:
                    val = to_float(m.group(2))
                    if 50 < val < 10000:
                        prices[key] = val
                except ValueError:
                    pass
        if prices:
            return prices

    return {}


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

    # Notifiera API:et att ladda om senaste prisfil
    try:
        r = requests.get("http://localhost:8000/reload", timeout=5)
        if r.status_code == 200:
            print("✓ API uppdaterat med nya priser.")
        else:
            print(f"⚠️  API /reload svarade med status {r.status_code}.")
    except Exception:
        pass  # API kanske inte kör – tyst fel


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
    # ("Tavex",              fetch_tavex),     # 403 överallt – blockerad
]


def main() -> None:
    now = datetime.now(tz=STOCKHOLM)
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
