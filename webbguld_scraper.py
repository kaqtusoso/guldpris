"""
WebbGuld Price Scraper
Scrapes gold prices (kr/g) for all karats from webbguld.se/salja-guld.
Prices are embedded as JS constants in the page, not from an API.

Karats available: 8K, 9K, 10K, 14K, 18K, 20K, 21K, 21.6K, 22K, 23K, 24K
Weight brackets: prices vary by weight (grams) you're selling.
24K has a single fixed price regardless of weight.

Note: The site's JS has a typo ("rice8" instead of "price8") in the 300g+
block. We handle this with a fallback regex that also matches "rice8".
"""

import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime


URL = "https://webbguld.se/salja-guld"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Weight brackets as defined in the site's JS: (lower_exclusive, upper_exclusive, label)
WEIGHT_BRACKETS = [
    (0,   5,   "1-4g"),
    (4,   10,  "5-9g"),
    (9,   20,  "10-19g"),
    (19,  30,  "20-29g"),
    (29,  40,  "30-39g"),
    (39,  50,  "40-49g"),
    (49,  100, "50-99g"),
    (99,  150, "100-149g"),
    (149, 200, "150-199g"),
    (199, 250, "200-249g"),
    (249, 275, "250-274g"),
    (274, 300, "275-299g"),
    (299, None, "300g+"),
]

# Internal karat keys used in the JS (note: "216" = 21.6K)
KARATS = ["8", "9", "10", "14", "18", "20", "21", "216", "22", "23"]

KARAT_LABELS = {
    "8":   "8K",
    "9":   "9K",
    "10":  "10K",
    "14":  "14K",
    "18":  "18K",
    "20":  "20K",
    "21":  "21K",
    "216": "21.6K",
    "22":  "22K",
    "23":  "23K",
    "24":  "24K",
}

# Display order for output table
DISPLAY_ORDER = ["8K", "9K", "10K", "14K", "18K", "20K", "21K", "21.6K", "22K", "23K", "24K"]


def fetch_js(url: str) -> str:
    """Fetch page and return the relevant pricing script content."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for script in soup.find_all("script"):
        content = script.string or ""
        if "price24" in content and "price18" in content and "change(" in content:
            return content
    raise ValueError("Could not find the pricing script on the page.")


def extract_prices_from_block(body: str) -> dict:
    """Extract all karat prices from a JS if-block body."""
    prices = {}
    for karat in KARATS:
        # Normal match: price8 = 123.45
        pm = re.search(rf"price{karat}\s*=\s*([\d.]+)", body)
        if pm:
            prices[karat] = float(pm.group(1))
        elif karat == "8":
            # Fallback: handle the site's typo "rice8" in the 300g+ block
            pm2 = re.search(r"rice8\s*=\s*([\d.]+)", body)
            if pm2:
                prices[karat] = float(pm2.group(1))
    return prices


def parse_prices(js: str) -> dict:
    """
    Parse the change(e) JS function to extract prices for all karats
    across all weight brackets.

    Returns:
        {
            "scraped_at": "2024-...",
            "currency": "SEK",
            "unit": "kr/g",
            "source": "...",
            "24K": {"fixed": 1311.87},
            "18K": {
                "1-4g":    880.11,
                "5-9g":    880.11,
                ...
                "300g+":   942.98,
            },
            ...
        }
    """
    result = {
        "scraped_at": datetime.now().isoformat(),
        "currency": "SEK",
        "unit": "kr/g",
        "source": URL,
    }

    # --- 24K: single fixed price ---
    m24 = re.search(r"price24\s*=\s*([\d.]+)", js)
    if m24:
        result["24K"] = {"fixed": float(m24.group(1))}

    # --- Parse all if/else-if blocks ---
    block_pattern = re.compile(
        r"(?:if|else if)\s*\(e\s*>\s*(\d+)(?:\s*&&\s*e\s*<\s*(\d+))?\)\s*\{([^}]+)\}",
        re.DOTALL,
    )

    bracket_prices: list[dict] = []
    for match in block_pattern.finditer(js):
        lower = int(match.group(1))
        upper = int(match.group(2)) if match.group(2) else None
        body = match.group(3)
        prices = extract_prices_from_block(body)
        if prices:
            bracket_prices.append({"lower": lower, "upper": upper, "prices": prices})

    # --- Map to named weight brackets ---
    for (lower_e, upper_e, label) in WEIGHT_BRACKETS:
        for bp in bracket_prices:
            if bp["lower"] == lower_e and bp["upper"] == upper_e:
                for karat, price in bp["prices"].items():
                    key = KARAT_LABELS.get(karat, karat + "K")
                    if key not in result:
                        result[key] = {}
                    result[key][label] = price
                break

    return result


def scrape() -> dict:
    js = fetch_js(URL)
    return parse_prices(js)


def main():
    print("Fetching prices from WebbGuld...")
    data = scrape()

    print(f"\nScraped at: {data['scraped_at']}")
    print(f"Source:     {data['source']}")
    print(f"Unit:       {data['unit']}\n")

    # Build list of all bracket labels (in order) across all karats
    all_brackets: list[str] = []
    for _, _, label in WEIGHT_BRACKETS:
        if label not in all_brackets:
            all_brackets.append(label)

    # Karats to show (only those present in data, in display order)
    weight_karats = [k for k in DISPLAY_ORDER if k in data and k != "24K"]

    # --- Print 24K first ---
    if "24K" in data:
        val = data["24K"].get("fixed", "–")
        print(f"  24K: {val:.0f} kr/g  (fast pris, oberoende av vikt)")

    # --- Print weight-dependent karats as a table ---
    if weight_karats:
        col_w = 8
        header = f"{'Bracket':>10}  " + "  ".join(f"{k:>{col_w}}" for k in weight_karats)
        print("\n" + header)
        print("─" * len(header))
        for bracket in all_brackets:
            row = f"{bracket:>10}  "
            cells = []
            for k in weight_karats:
                val = data.get(k, {}).get(bracket)
                cells.append(f"{val:>{col_w}.0f}" if val is not None else f"{'—':>{col_w}}")
            row += "  ".join(cells)
            print(row)

    # --- Save JSON ---
    out_path = "webbguld_prices.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nData saved to {out_path}")

    return data


if __name__ == "__main__":
    main()
