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
def fetch_guldbrev() -> dict:
    """
    Guldbrev har volymbaserad prissättning med 24 viktnivåer.
    Vi hämtar hela matrisen via deras interna PriceService API.

    Returnerar:
      - Vanliga karatnyckar (18K, 14K etc.) med basvärdet från gram 0 (ärligt minimipris)
      - _tiers: lista med alla viktnivåer så frontend kan visa rätt pris
        för den vikt användaren faktiskt skickar in.

    Transparensprincip: visa alltid priset för den vikt användaren anger,
    aldrig ett annonserat toppris som kräver 200-300g.
    Exempel 18K: 0g=206 kr/g, 50g=324 kr/g, 150g=483 kr/g, 300g=596 kr/g.
    """
    import requests as _req
    url = (
        "https://www.guldbrev.se/wp-content/themes/guldbrevgulp"
        "/WebServices/PriceService/mypages-pricematrix.php?r=f"
    )
    try:
        resp = _req.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    # priceUnitsPerWeight: lista med 2 grupper
    #   index 0 = utan snabbhetsbonus  ← vi använder denna
    #   index 1 = med snabbhetsbonus (+15%)
    groups = data.get("priceUnitsPerWeight", [])
    if not groups:
        return {}

    raw_tiers = groups[0].get("priceUnitsPerWeight", [])
    # Sortera på minimumWeight så vi kan göra stegvis lookup
    raw_tiers_sorted = sorted(raw_tiers, key=lambda t: t.get("minimumWeight", 0))

    # Bygg _tiers: [{"min_vikt": 0, "18K": 206, "14K": 160, ...}, ...]
    tiers_list = []
    for t in raw_tiers_sorted:
        tier_entry: dict = {"min_vikt": t.get("minimumWeight", 0)}
        for pu in t.get("priceUnits", {}).get("priceUnits", []):
            label = KARAT_ALIASES.get(str(pu.get("karat", "")))
            if label and pu.get("price"):
                tier_entry[label] = float(pu["price"])
        tiers_list.append(tier_entry)

    # Baspriser = priset vid min_vikt=0 (ärligt minimipris från gram 1)
    prices: dict = {}
    if tiers_list:
        base = tiers_list[0]
        for k, v in base.items():
            if k != "min_vikt":
                prices[k] = v

    # Lägg med hela tier-matrisen så frontend kan slå upp rätt pris per vikt
    prices["_tiers"] = tiers_list
    return prices


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
    """
    Pantit exponerar ett öppet JSON-API på /prices (ingen auth).
    Returnerar realtidspriser för 10 guldkarat, flat prissättning oavsett vikt.
    Format: {"success":true,"prices":{"Guld":{"8":333.07,"14":680.95,"18":926.44,...}}}
    Playwright behövs ej — requests räcker.
    """
    try:
        r = requests.get("https://www.pantit.se/prices", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [ERROR] Pantit API: {e}", file=sys.stderr)
        return {}

    if not data.get("success"):
        return {}

    guld = data.get("prices", {}).get("Guld", {})
    prices: dict[str, float] = {}
    for karat_num, pris in guld.items():
        key = KARAT_ALIASES.get(str(karat_num))
        if key:
            prices[key] = round(float(pris), 2)
    return prices


# ── 4. Noblex ─────────────────────────────────────────────────────────────────
def fetch_noblex() -> dict[str, float]:
    soup = get("https://noblex.se/salja-guld/")
    if not soup:
        return {}
    prices = from_table(soup)
    if not prices:
        prices = from_text(clean(soup.get_text(" ", strip=True)))
    # 24K-priset gäller enbart "Guldtackor & Guldmynt" — ej vanligt skrotguld/smycken.
    # Noblex saknar ett publicerat skrotguldspris för 24K. Tas bort för att undvika
    # att visa ett missvisande toppris för en säljare med t.ex. ett 24K smycke.
    prices.pop("24K", None)
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
        if "tacka" in label.lower():
            continue  # Skip Guldtacka — kräver certifierade investeringstackor, ej vanligt skrotguld
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
def fetch_webbguld() -> dict:
    """
    WebbGuld har volymbaserad prissättning med 6 viktbaserade prisnivåer.
    Priser hämtas från JS-funktion change(e) på /salja-guld (inline script, ingen extern API).

    6 unika prisnivåer (gram):
      1–99g   → basispris (exponeras som standardvärde)
      100–199g → ca +1.2%
      200–249g → ca +2.4%
      250–274g → ca +3.6%
      275–299g → ca +4.8%
      300g+    → ca +7.2%

    24K: fast pris oavsett vikt.
    21.6K stöds via JS-nyckel price216.
    OBS: stavfel 'rice8' (istället för 'price8') i 300g+-blocket för 8K – hanteras.

    Transparensprincip: baspriser visar alltid priset vid lägsta viktnivå (1g),
    aldrig det bättre priset som bara fås vid 300g+.
    """
    _KARAT_JS_KEYS = ["8", "9", "10", "14", "18", "20", "21", "216", "22", "23"]
    _KARAT_LABELS = {
        "8":   "8K",   "9":   "9K",   "10":  "10K",  "14":  "14K",
        "18":  "18K",  "20":  "20K",  "21":  "21K",  "216": "21.6K",
        "22":  "22K",  "23":  "23K",
    }

    def _extract_block_prices(body: str) -> dict[str, float]:
        """Extraherar prisvariabler ur ett JS-block. Hanterar stavfelet 'rice8'."""
        prices: dict[str, float] = {}
        for k in _KARAT_JS_KEYS:
            # \b säkerställer att rice21 inte råkar matcha price216
            m = re.search(rf"(?:p)?rice{k}\b\s*=\s*([\d.]+)", body)
            if m:
                prices[k] = float(m.group(1))
        return prices

    def _parse_tiers(js_text: str) -> list[dict]:
        """
        Parsar change(e)-funktionen och returnerar vikttier-lista.
        13 JS-block → 6 unika prisnivåer efter deduplicering.
        """
        block_pattern = re.compile(
            r"(?:if|else\s+if)\s*\(\s*e\s*>\s*(\d+)(?:\s*&&\s*e\s*<\s*\d+)?\s*\)\s*\{([^}]+)\}",
            re.DOTALL,
        )
        tiers: list[dict] = []
        last_prices: dict[str, float] = {}
        for match in block_pattern.finditer(js_text):
            lower = int(match.group(1))
            min_vikt = lower + 1  # e > 0 → min_vikt=1; e > 99 → min_vikt=100
            block_prices = _extract_block_prices(match.group(2))
            if not block_prices or block_prices == last_prices:
                continue  # Hoppa över identiska eller tomma block
            tier: dict = {"min_vikt": min_vikt}
            tier.update(block_prices)
            tiers.append(tier)
            last_prices = block_prices
        return tiers

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    js_text = ""

    # ── Försök 1–3: requests ──────────────────────────────────────────────────
    for attempt in range(1, 4):
        try:
            resp = requests.get("https://webbguld.se/salja-guld", headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            soup_wg = BeautifulSoup(resp.text, "html.parser")
            # Kombinera ALLA inline-scripts – change()-funktionen kan vara uppdelad
            combined = "\n".join(s.string or "" for s in soup_wg.find_all("script"))
            if "price18" in combined and "change(" in combined:
                js_text = combined
                print(f"  [WebbGuld] JS hittades via requests (försök {attempt})", file=sys.stderr)
                break
            print(
                f"  [WebbGuld] Försök {attempt}: JS saknas "
                f"(price18={'price18' in combined}, change={'change(' in combined}, "
                f"scripts={len(soup_wg.find_all('script'))})",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"  [FEL] WebbGuld requests försök {attempt}: {exc}", file=sys.stderr)
        if attempt < 3:
            import time; time.sleep(5)

    # ── Playwright-fallback (om requests misslyckas på Railway) ───────────────
    if not js_text:
        print("  [WebbGuld] Försöker Playwright som fallback…", file=sys.stderr)
        soup_wg = playwright_get("https://webbguld.se/salja-guld", wait_ms=3000)
        if soup_wg:
            combined = "\n".join(s.string or "" for s in soup_wg.find_all("script"))
            if "price18" in combined and "change(" in combined:
                js_text = combined
                print("  [WebbGuld] JS hittades via Playwright", file=sys.stderr)

    if not js_text:
        print("  [FEL] WebbGuld: Kunde inte hitta JS (varken requests eller Playwright)", file=sys.stderr)
        return {}

    try:
        # 24K: fast pris oavsett vikt
        m24 = re.search(r"\bprice24\s*=\s*([\d.]+)", js_text)
        price24 = float(m24.group(1)) if m24 else None

        # Bygg unika vikttier (råformat med JS-nycklar, utan 24K)
        raw_tiers = _parse_tiers(js_text)
        if not raw_tiers:
            print("  [FEL] WebbGuld: Inga vikttier hittades i JS-texten", file=sys.stderr)
            return {}

        # Konvertera JS-nycklar → karat-labels, filtrera orimliga värden, lägg till 24K
        label_tiers: list[dict] = []
        for raw in raw_tiers:
            tier: dict = {"min_vikt": raw["min_vikt"]}
            for k, v in raw.items():
                if k == "min_vikt":
                    continue
                label = _KARAT_LABELS.get(k)
                if label and 50 < v < 10000:
                    tier[label] = v
            if price24 and 50 < price24 < 10000:
                tier["24K"] = price24
            if len(tier) > 1:  # minst ett karat utöver min_vikt
                label_tiers.append(tier)

        if not label_tiers:
            return {}

        # Baspriser = lägsta viktnivå (min_vikt=1, ärligt minimipris)
        prices: dict = {}
        first = min(label_tiers, key=lambda t: t["min_vikt"])
        for k, v in first.items():
            if k != "min_vikt":
                prices[k] = v

        prices["_tiers"] = label_tiers
        min_vikter = [t["min_vikt"] for t in label_tiers]
        print(
            f"  [WebbGuld] {len(prices) - 1} karat, {len(label_tiers)} viktnivåer: {min_vikter}g",
            file=sys.stderr,
        )
        return prices

    except Exception as exc:
        print(f"  [FEL] WebbGuld parse: {exc}", file=sys.stderr)
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


# ── 15. SMSGuld ───────────────────────────────────────────────────────────────
def fetch_smsguld() -> dict:
    """
    SMSGuld har volymbaserad prissättning via en inverterad Bézier-kurva.
    Baspriser hämtas från JS på /prissattning (serverrenderade, uppdateras dagligen).

    Betalningslogik (verifierad mot deras kalkylator-JS, maj 2026):
      24K:    basePrice × 0.90  (utan certifikat — ärlig miniminivå)
              basePrice × 0.95  (med certifikat — bonus för certifierade guldtackor)
      Övriga: basePrice × calculatePayout(vikt)  (Bézier-kurva, se nedan)
              Valfri snabbhetsbonus: ×1.10 om guldet postas nästa vardag

    Bézier-kurvan (3 kontrollpunkter, utan snabbhetsbonus):
      p1: 1g  → 85%  (startpunkt)
      p2: 60g → 60%  (SÄMSTA punkten — mellanvolymer straffas)
      p3: 200g→ 85%  (återhämtning vid stor volym)

    Transparensprincip: vi visar ALLTID priset utan bonusar.
    _tiers ger frontend möjlighet att visa rätt pris för angiven vikt.
    Notera: SMSGuld sätter slutpriset vid mottagning — detta är en uppskattning.
    """
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    # Hämta /prissattning — den har den fullständiga kalkylatorn med korrekt formel
    try:
        resp = requests.get("https://smsguld.se/prissattning", headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [FEL] SMSGuld: {exc}", file=sys.stderr)
        return {}

    # Extrahera karatPrices från JS: const karatPrices = { '24': 1447.35, ... }
    block = re.search(r"const\s+karatPrices\s*=\s*\{([^}]+)\}", resp.text)
    if not block:
        print("  [FEL] SMSGuld: karatPrices-blocket hittades inte.", file=sys.stderr)
        return {}

    base_prices: dict[str, float] = {}
    for entry in re.finditer(r"'(\d+)'\s*:\s*([\d.]+)", block.group(1)):
        karat_num = entry.group(1)
        label = KARAT_ALIASES.get(karat_num)
        if label:
            base_prices[label] = float(entry.group(2))

    if not base_prices:
        return {}

    # ── Bézier-utbetalningskurva (utan snabbhetsbonus) ────────────────────────
    def _payout(weight: float) -> float:
        """Returnerar utbetalningsprocent för icke-24K baserat på vikten i gram."""
        p1x, p1y = 1.0,   0.85
        p2x, p2y = 60.0,  0.60
        p3x, p3y = 200.0, 0.85
        if weight <= p2x:
            t = (weight - p1x) / (p2x - p1x)
            return p1y * (1-t)**2 + p2y * 2*(1-t)*t + p2y * t**2
        elif weight <= p3x:
            t = (weight - p2x) / (p3x - p2x)
            return p2y * (1-t)**2 + p2y * 2*(1-t)*t + p3y * t**2
        return p3y

    # Sampla varje gram 1–300 för exakt precision (Bézier är kontinuerlig —
    # glesa punkter ger upp till 71 kr/g fel vid steglookup i frontend)
    _VIKTER = list(range(1, 301)) + [500, 1000]

    # Bygg _tiers — samma format som Guldbrev
    tiers_list = []
    for v in _VIKTER:
        tier: dict = {"min_vikt": v}
        for label, base in base_prices.items():
            if label == "24K":
                tier[label] = round(base * 0.90, 2)   # utan certifikat
            else:
                tier[label] = round(base * _payout(v), 2)
        tiers_list.append(tier)

    # Baspriser = priset vid 1g (ärlig miniminivå utan bonusar)
    prices: dict = {}
    for label, base in base_prices.items():
        if label == "24K":
            val = round(base * 0.90, 2)
        else:
            val = round(base * _payout(1.0), 2)
        if 50 < val < 10000:
            prices[label] = val

    prices["_tiers"] = tiers_list
    print(f"  [SMSGuld] Hämtade {len(base_prices)} karat: {list(base_prices.keys())}", file=sys.stderr)
    return prices


# ── 16. Tavex ────────────────────────────────────────────────────────────────────
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

# Snabba aktörer: vanliga requests, körs var 5:e minut
AKTÖRER_SNABB = [
    ("Guldbrev",           fetch_guldbrev),
    ("Diamantbrev",        fetch_diamantbrev),
    ("Noblex",             fetch_noblex),
    ("Finguld",            fetch_finguld),
    ("Kaplans Ädelmetall", fetch_kaplans),
    ("Pantbanken",         fetch_pantbanken),
    ("Sefina Pantbank",    fetch_sefina),
    ("WebbGuld",           fetch_webbguld),
    ("Capitaurum",         fetch_capitaurum),
    ("SMSGuld",            fetch_smsguld),
]

# Playwright-aktörer: tyngre, körs var 30:e minut
AKTÖRER_PLAYWRIGHT = [
    ("Pantit",             fetch_pantit),
    ("Guldcentralen",      fetch_guldcentralen),
    ("Guldfynd",           fetch_guldfynd),
    # ("Svenska Guld",       fetch_svenska_guld),
    # ("Tavex",              fetch_tavex),     # 403 överallt – blockerad
]

# Kombinerad lista (används vid manuell körning och lokal skriptanvändning)
AKTÖRER = AKTÖRER_SNABB + AKTÖRER_PLAYWRIGHT


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
