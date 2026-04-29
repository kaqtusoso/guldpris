# api.py  –  Fungerar både lokalt och på Railway
#
# Lokalt:  bash run_api.sh   (läser .env-filen)
# Railway: sätts upp via environment variables i Railway-dashboarden

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel, EmailStr
import sys, os, uuid, json, glob
from datetime import datetime
from zoneinfo import ZoneInfo

STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Ladda .env-fil om den finns (för lokal körning)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from guldpris_scraper import AKTÖRER, AKTÖRER_SNABB, AKTÖRER_PLAYWRIGHT, KARAT_ORDER, save_json

import sendgrid
from sendgrid.helpers.mail import Mail
import anthropic

import gspread
from google.oauth2.service_account import Credentials

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

latest_prices: dict = {}

SENDGRID_API_KEY  = os.environ.get("SENDGRID_API_KEY", "")
MAIL_FROM         = os.environ.get("MAIL_FROM", "noreply@saljguldet.se")
GOOGLE_SHEET_ID   = os.environ.get("GOOGLE_SHEET_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PUBLISH_TOKEN     = os.environ.get("PUBLISH_TOKEN", "guldkollen2026")

# ── Nyckelord för automatisk artikelgenerering (ett per vecka) ────────────────
ARTIKEL_KEYWORDS = [
    # Redan genererade – rör inte
    {"nyckelord": "sälja guld tips bästa pris",                                        "slug": "salja-guld-basta-pris"},
    {"nyckelord": "guldbrev recension 2026",                                           "slug": "guldbrev-recension"},
    # Köparrecensioner
    {"nyckelord": "noblex omdöme guld",                                                "slug": "noblex-omdome"},
    {"nyckelord": "hur säljer man guld säkert",                                        "slug": "hur-saljer-man-guld"},
    {"nyckelord": "bästa guldköpare sverige 2026",                                     "slug": "basta-guldkopare-sverige"},
    {"nyckelord": "kaplans ädelmetall recension",                                      "slug": "kaplans-recension"},
    {"nyckelord": "pantit guld recension",                                             "slug": "pantit-recension"},
    {"nyckelord": "finguld recension 2026",                                            "slug": "finguld-recension"},
    {"nyckelord": "guldcentralen omdöme och recension",                                "slug": "guldcentralen-recension"},
    {"nyckelord": "webbguld recension 2026",                                           "slug": "webbguld-recension"},
    {"nyckelord": "diamantbrev recension guld",                                        "slug": "diamantbrev-recension"},
    {"nyckelord": "pantbanken guld recension",                                         "slug": "pantbanken-recension"},
    {"nyckelord": "capitaurum recension 2026",                                         "slug": "capitaurum-recension"},
    {"nyckelord": "guldfynd recension 2026",                                           "slug": "guldfynd-recension"},
    # Kontroversiella frågor med hög sökintention
    {"nyckelord": "måste jag betala skatt när jag säljer guld i Sverige",              "slug": "skatt-salja-guld"},
    {"nyckelord": "kan guldköpare lura dig – vad du ska se upp med",                  "slug": "guldkopare-lura-dig"},
    {"nyckelord": "varför betalar guldköpare så olika mycket för samma guld",          "slug": "varfor-olika-pris-guld"},
    {"nyckelord": "är det lagligt att sälja guld anonymt i Sverige",                   "slug": "salja-guld-anonymt"},
    {"nyckelord": "kan guldköpare neka att betala efter värdering",                    "slug": "neka-betala-efter-vardering"},
    {"nyckelord": "hur vet jag att guldköparen inte fuskar med vikten",                "slug": "guldkopare-fuskar-vikt"},
    {"nyckelord": "vad är rimlig marginal hos en guldköpare",                          "slug": "rimlig-marginal-guldkopare"},
    {"nyckelord": "varför får jag så lite betalt för mitt guld",                       "slug": "varfor-lite-betalt-guld"},
    {"nyckelord": "kan jag ångra mig efter att ha sålt guld",                          "slug": "angra-salja-guld"},
    {"nyckelord": "sälja guld utan kvitto – är det lagligt",                           "slug": "salja-guld-utan-kvitto"},
    {"nyckelord": "sälja guld efter dödsfall och bouppteckning",                       "slug": "salja-guld-dodsfall"},
]

# Absolut sökväg till mappen där JSON-filer sparas
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
GULDPRISER_DIR  = os.path.join(BASE_DIR, "Guldpriser")


# ── JSON-cache: ladda senaste sparade priser ──────────────────────────────────

def ladda_senaste_json() -> bool:
    """Laddar senaste sparade JSON-filen som latest_prices. Returnerar True om det lyckas."""
    global latest_prices
    pattern = os.path.join(GULDPRISER_DIR, "guldpriser_*.json")
    filer = sorted(glob.glob(pattern))
    if not filer:
        return False
    senaste = filer[-1]
    try:
        with open(senaste, encoding="utf-8") as f:
            latest_prices = json.load(f)
        print(f"[STARTUP] Laddade priser från: {os.path.basename(senaste)}")
        return True
    except Exception as e:
        print(f"[FEL] Kunde inte läsa {senaste}: {e}")
        return False


# ── Scraper ───────────────────────────────────────────────────────────────────

def _kör_aktörer(aktörer: list, label: str) -> None:
    """Kör en delmängd aktörer, mergar in resultaten i latest_prices och sparar JSON."""
    global latest_prices
    now = datetime.now(tz=STOCKHOLM)
    print(f"[SCRAPER-{label}] Kör kl {now.strftime('%H:%M')}...")

    cached = latest_prices.get("priser", {})

    # Starta med alla befintliga priser så att oberörda aktörer behålls
    all_prices = dict(cached)

    for name, fetcher in aktörer:
        try:
            result = fetcher()
            if result:
                all_prices[name] = result
            else:
                fallback = cached.get(name, {})
                if fallback:
                    print(f"[FALLBACK] {name}: använder senaste kända priser ({list(fallback.keys())})", flush=True)
                    all_prices[name] = fallback
                else:
                    all_prices[name] = {}
        except Exception as e:
            print(f"[FEL] {name}: {e}")
            fallback = cached.get(name, {})
            if fallback:
                print(f"[FALLBACK] {name}: använder senaste kända priser efter fel", flush=True)
                all_prices[name] = fallback
            else:
                all_prices[name] = {}

    latest_prices = {
        "hämtad": now.strftime("%Y-%m-%d %H:%M"),
        "priser": {
            aktör: {karat: priser[karat] for karat in KARAT_ORDER if karat in priser}
            for aktör, priser in all_prices.items()
        },
    }
    save_json(all_prices, now)
    print(f"[SCRAPER-{label}] Klar!")


def kör_scraper():
    """Kör alla aktörer (används vid manuell /scrape och lokal körning)."""
    _kör_aktörer(AKTÖRER, "FULL")


def kör_scraper_snabb():
    """Kör requests-baserade aktörer – var 5:e minut."""
    _kör_aktörer(AKTÖRER_SNABB, "SNABB")


def kör_scraper_playwright():
    """Kör Playwright-aktörer – var 30:e minut."""
    _kör_aktörer(AKTÖRER_PLAYWRIGHT, "PLAYWRIGHT")


# Vid start: ladda senaste sparade data (snabbt).
# Om ingen fil finns, kör snabb-scrapern direkt (Playwright körs sedan vid nästa 30-minutersintervall).
if not ladda_senaste_json():
    print("[STARTUP] Ingen sparad data hittades – kör snabb-scraper nu...")
    kör_scraper_snabb()

# Kör scraper varje timme automatiskt (fungerar både lokalt och på Railway)
scheduler = BackgroundScheduler()
scheduler.add_job(kör_scraper_snabb,      "cron", minute="*/5")   # var 5:e minut
scheduler.add_job(kör_scraper_playwright, "cron", minute="0,30")  # var 30:e minut
scheduler.start()


# ── Datamodell för order ──────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    # Fält som Lovable faktiskt skickar
    fornamn: str | None = None
    efternamn: str | None = None
    epost: str | None = None          # Lovable använder "epost"
    telefon: str | None = None
    karat: int | str | None = None    # Lovable skickar int (21), inte "21K"
    gram: float | None = None         # Lovable använder "gram"
    kopare: str | None = None         # vald köpare
    totalPris: float | None = None
    leveranssatt: str | None = None
    personnummer: str | None = None
    gata: str | None = None
    postnummer: str | None = None
    ort: str | None = None
    kommentar: str | None = None
    skapadAt: str | None = None

    @property
    def resolved_namn(self) -> str:
        delar = [self.fornamn or "", self.efternamn or ""]
        return " ".join(d for d in delar if d).strip() or "Okänd"

    @property
    def resolved_email(self) -> str:
        return self.epost or ""

    @property
    def resolved_telefon(self) -> str | None:
        return self.telefon

    @property
    def resolved_karat(self) -> str:
        if isinstance(self.karat, int):
            return f"{self.karat}K"
        return str(self.karat) if self.karat else "okänt"

    @property
    def resolved_vikt(self) -> float:
        return self.gram or 0.0

    @property
    def resolved_meddelande(self) -> str | None:
        return self.kommentar


# ── HTML-mailmall ─────────────────────────────────────────────────────────────

def bygg_mail_html(order_id: str, order: OrderRequest, pris_per_gram: float | None) -> str:
    pris_rad = ""
    if pris_per_gram:
        uppskattat = round(pris_per_gram * order.resolved_vikt, 2)
        pris_rad = f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Dagspris ({order.karat})</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;font-weight:600;">{pris_per_gram:,.2f} kr/g</td>
        </tr>
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Uppskattat värde</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;font-weight:600;color:#b8860b;">{uppskattat:,.2f} kr</td>
        </tr>
        """

    meddelande_rad = ""
    if order.resolved_meddelande:
        meddelande_rad = f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Ditt meddelande</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;font-style:italic;">{order.resolved_meddelande}</td>
        </tr>
        """

    telefon_rad = ""
    if order.resolved_telefon:
        telefon_rad = f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Telefon</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.resolved_telefon}</td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Orderbekräftelse</title>
</head>
<body style="margin:0;padding:0;background:#faf7f0;font-family:'Helvetica Neue',Arial,sans-serif;">

  <!-- Wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#faf7f0;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#b8860b,#d4a017);padding:36px 40px;text-align:center;">
            <p style="margin:0;font-size:28px;letter-spacing:4px;color:#fff;font-weight:300;">✦ GULD</p>
            <p style="margin:8px 0 0;color:rgba(255,255,255,0.85);font-size:13px;letter-spacing:2px;text-transform:uppercase;">Orderbekräftelse</p>
          </td>
        </tr>

        <!-- Intro -->
        <tr>
          <td style="padding:36px 40px 20px;">
            <p style="margin:0 0 8px;font-size:22px;color:#2c2c2c;">Tack, {order.resolved_namn}!</p>
            <p style="margin:0;font-size:15px;color:#555;line-height:1.6;">
              Vi har tagit emot din förfrågan och återkommer inom <strong>1 arbetsdag</strong> med ett slutgiltigt erbjudande.
              Nedan ser du en sammanfattning av din order.
            </p>
          </td>
        </tr>

        <!-- Orderdetaljer -->
        <tr>
          <td style="padding:0 40px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #f0e6c8;border-radius:6px;overflow:hidden;font-size:14px;">
              <tr style="background:#fdf8ee;">
                <td colspan="2" style="padding:10px 12px;font-weight:700;color:#b8860b;font-size:12px;letter-spacing:1px;text-transform:uppercase;">
                  Orderdetaljer · #{order_id}
                </td>
              </tr>
              <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Namn</td>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.resolved_namn}</td>
              </tr>
              <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">E-post</td>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.resolved_email}</td>
              </tr>
              {telefon_rad}
              <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Karat</td>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.resolved_karat}</td>
              </tr>
              <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Uppgiven vikt</td>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.resolved_vikt} gram</td>
              </tr>
              {pris_rad}
              {meddelande_rad}
            </table>
          </td>
        </tr>

        <!-- Nästa steg -->
        <tr>
          <td style="padding:0 40px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#fdf8ee;border-left:3px solid #b8860b;border-radius:0 6px 6px 0;padding:20px 24px;">
              <tr>
                <td>
                  <p style="margin:0 0 12px;font-weight:700;color:#b8860b;font-size:13px;letter-spacing:1px;text-transform:uppercase;">Vad händer nu?</p>
                  <p style="margin:0 0 8px;font-size:14px;color:#444;line-height:1.7;">
                    ① &nbsp;Vi granskar din förfrågan och värderar guldet baserat på aktuellt dagspris.<br>
                    ② &nbsp;Du får ett bindande erbjudande via e-post inom 1 arbetsdag.<br>
                    ③ &nbsp;Om du accepterar skickar du guldet fritt via vår förbetalta fraktetikett.<br>
                    ④ &nbsp;Betalning sker inom 24 timmar efter att vi mottagit och kontrollerat guldet.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Kontakt -->
        <tr>
          <td style="padding:0 40px 36px;font-size:13px;color:#888;line-height:1.8;">
            <strong style="color:#555;">Frågor?</strong> Kontakta oss på
            <a href="mailto:brjanssonp@gmail.com" style="color:#b8860b;">info@saljguldet.se</a>
            eller ring <a href="tel:+46702320615" style="color:#b8860b;">070-232 06 15</a>.
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#2c2c2c;padding:20px 40px;text-align:center;">
            <p style="margin:0;font-size:12px;color:#888;">
              © {datetime.now().year} Säljguldet AB &nbsp;·&nbsp;
              <a href="#" style="color:#b8860b;text-decoration:none;">Integritetspolicy</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Hjälp: hämta dagspris för ett karat ──────────────────────────────────────

def hämta_dagspris(karat: str) -> float | None:
    """Plockar genomsnittspriset för ett karat från latest_prices."""
    priser = latest_prices.get("priser", {})
    värden = [
        p[karat]
        for p in priser.values()
        if karat in p
    ]
    if not värden:
        return None
    return round(sum(värden) / len(värden), 2)


# ── Google Sheets: logga order ───────────────────────────────────────────────

_SHEET_SCOPES    = ["https://www.googleapis.com/auth/spreadsheets"]
_CREDENTIALS_FILE = os.path.join(BASE_DIR, "saljguldet-9b2b64a5ba8a.json")
_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")  # Railway: hela JSON-strängen
_SHEET_HEADER    = [
    "Datum", "Order-ID", "Namn", "E-post", "Telefon",
    "Karat", "Vikt (g)", "Dagspris (kr/g)", "Uppskattat värde (kr)",
    "Köpare", "Personnummer", "Leveranssätt", "Gata", "Postnummer", "Ort",
    "Kommentar", "Status"
]

def _get_worksheet():
    """Öppnar första fliken i det konfigurerade Google Kalkylark.
    Läser credentials från env var GOOGLE_CREDENTIALS_JSON (Railway)
    eller från lokal fil (lokal körning)."""
    if _CREDENTIALS_JSON:
        # Railway: credentials som JSON-sträng i miljövariabel
        import io
        creds = Credentials.from_service_account_info(
            json.loads(_CREDENTIALS_JSON), scopes=_SHEET_SCOPES
        )
    else:
        # Lokalt: credentials från fil
        creds = Credentials.from_service_account_file(_CREDENTIALS_FILE, scopes=_SHEET_SCOPES)
    klient = gspread.Client(auth=creds)
    return klient.open_by_key(GOOGLE_SHEET_ID).sheet1

def logga_order_i_sheet(order_id: str, order: OrderRequest, dagspris: float | None) -> None:
    """Lägger till en ny rad i Google Kalkylark. Skapar rubrikrad om arket är tomt."""
    if not GOOGLE_SHEET_ID:
        print("[SHEETS] GOOGLE_SHEET_ID saknas – hoppar över loggning.")
        return
    try:
        ws = _get_worksheet()
        # Skapa rubrikrad om rad 1 kolumn A är tom
        if not ws.acell("A1").value:
            ws.update(values=[_SHEET_HEADER], range_name="A1")
            ws.freeze(rows=1)

        uppskattat = round(dagspris * order.resolved_vikt, 2) if dagspris else ""
        rad = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            order_id,
            order.resolved_namn,
            order.resolved_email,
            order.resolved_telefon or "",
            order.resolved_karat,
            order.resolved_vikt,
            dagspris or "",
            uppskattat,
            order.kopare or "",
            order.personnummer or "",
            order.leveranssatt or "",
            order.gata or "",
            order.postnummer or "",
            order.ort or "",
            order.resolved_meddelande or "",
            "Ny",
        ]
        ws.append_row(rad, value_input_option="USER_ENTERED")
        print(f"[SHEETS] Order #{order_id} loggad i kalkylark.")
    except Exception as e:
        print(f"[SHEETS] Fel vid loggning av order: {e}")


# ── Skicka mail via SendGrid ──────────────────────────────────────────────────

def skicka_mail(till: str, namn: str, html: str, order_id: str) -> None:
    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY saknas i miljövariablerna.")

    message = Mail(
        from_email=MAIL_FROM,
        to_emails=till,
        subject=f"Orderbekräftelse #{order_id} – vi har tagit emot din förfrågan",
        html_content=html,
    )
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    response = sg.send(message)

    if response.status_code not in (200, 202):
        raise RuntimeError(f"SendGrid returnerade status {response.status_code}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/priser")
def get_priser():
    if not latest_prices:
        return {"error": "Inga priser hittades ännu."}
    return latest_prices


@app.post("/order/debug")
async def debug_order(request: Request):
    """Temporär debug-endpoint – loggar exakt vad Lovable skickar."""
    body = await request.body()
    print(f"[DEBUG /order/debug] Raw body: {body.decode('utf-8', errors='replace')}")
    return {"raw": body.decode("utf-8", errors="replace")}


@app.post("/order")
async def skicka_orderbekräftelse(request: Request):
    # Logga råa bodyn för felsökning
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8", errors="replace")
    print(f"[ORDER] Raw body: {body_str}")

    try:
        data = json.loads(body_str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Ogiltig JSON: {e}")

    print(f"[ORDER] Parsed fields: {list(data.keys())}")

    try:
        order = OrderRequest(**data)
    except Exception as e:
        print(f"[ORDER] Valideringsfel: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    order_id = str(uuid.uuid4())[:8].upper()
    dagspris = hämta_dagspris(order.resolved_karat)
    html     = bygg_mail_html(order_id, order, dagspris)

    # Skicka mail – fel här stoppar inte orderflödet
    try:
        skicka_mail(order.resolved_email, order.resolved_namn, html, order_id)
    except Exception as e:
        print(f"[MAIL] Kunde inte skicka mail: {e}")

    # Logga order i Google Kalkylark
    logga_order_i_sheet(order_id, order, dagspris)

    return {
        "status":    "skickat",
        "order_id":  order_id,
        "dagspris":  dagspris,
        "mottagare": order.resolved_email,
    }


@app.get("/scrape")
def trigger_scraper():
    """Kör scrapern manuellt och uppdaterar priserna direkt."""
    import threading
    threading.Thread(target=kör_scraper, daemon=True).start()
    return {"status": "started", "meddelande": "Scrapern körs i bakgrunden. Priserna uppdateras inom ~2 minuter."}


@app.get("/debug/webbguld")
def debug_webbguld():
    """Diagnostik: hämtar rådata från WebbGuld och visar vad Railway faktiskt ser."""
    import requests as _req
    from bs4 import BeautifulSoup as _BS
    url = "https://webbguld.se/salja-guld"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        import re as _re
        resp = _req.get(url, headers=headers, timeout=20)
        soup = _BS(resp.text, "html.parser")
        scripts = [s.string or "" for s in soup.find_all("script")]
        js_block = next((c for c in scripts if "price24" in c and "price18" in c and "change(" in c), None)

        # Extrahera faktiska priser direkt ur JS-blocket
        råpriser = {}
        if js_block:
            for karat in ["8", "9", "10", "14", "18", "20", "21", "22", "23", "24"]:
                m = _re.search(rf"price{karat}\s*=\s*([\d.]+)", js_block)
                if m:
                    råpriser[f"{karat}K"] = float(m.group(1))

        return {
            "status_code": resp.status_code,
            "svar_längd": len(resp.text),
            "js_block_hittat": js_block is not None,
            "js_block_längd": len(js_block) if js_block else 0,
            "råpriser_från_js": råpriser,
            "priser_efter_filter": {k: v for k, v in råpriser.items() if 50 < v < 10000},
            "title": soup.find("title").get_text("") if soup.find("title") else None,
        }
    except Exception as e:
        return {"fel": str(e)}


@app.get("/reload")
def reload_priser():
    """Läser in senaste sparade JSON-filen utan att starta om API:et."""
    if ladda_senaste_json():
        hämtad = latest_prices.get("hämtad", "okänd")
        return {"status": "ok", "meddelande": f"Priser laddade om. Senaste: {hämtad}"}
    raise HTTPException(status_code=404, detail="Ingen sparad prisfil hittades.")


# ── Artikelhantering – Google Sheets ─────────────────────────────────────────

def _sätt_status_dropdown(spreadsheet, ws) -> None:
    """Dropdown + färgkodning på Status-kolumnen (F). Tar även bort kolumn H om den finns."""
    headers = ws.row_values(1)

    requests = []

    # Ta bort kolumn H ("Publicerad") om den fortfarande finns
    if len(headers) >= 8 and headers[7] == "Publicerad":
        requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 7,
                    "endIndex": 8
                }
            }
        })

    # Dropdown-validering på kolumn F
    requests.append({
        "setDataValidation": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": 1,
                "startColumnIndex": 5,
                "endColumnIndex": 6
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [
                        {"userEnteredValue": "Utkast"},
                        {"userEnteredValue": "Granskas"},
                        {"userEnteredValue": "Publicerad"},
                        {"userEnteredValue": "Avvisad"}
                    ]
                },
                "showCustomUi": True,
                "strict": True
            }
        }
    })

    # Färgkodning: grön = Publicerad, röd = Utkast, gul = övriga värden
    STATUS_RANGE = {"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 5, "endColumnIndex": 6}
    requests += [
        {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [STATUS_RANGE],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "Publicerad"}]},
                "format": {"backgroundColor": {"red": 0.72, "green": 0.88, "blue": 0.56}}
            }
        }}},
        {"addConditionalFormatRule": {"index": 1, "rule": {
            "ranges": [STATUS_RANGE],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "Utkast"}]},
                "format": {"backgroundColor": {"red": 0.96, "green": 0.60, "blue": 0.60}}
            }
        }}},
        {"addConditionalFormatRule": {"index": 2, "rule": {
            "ranges": [STATUS_RANGE],
            "booleanRule": {
                "condition": {"type": "NOT_BLANK"},
                "format": {"backgroundColor": {"red": 1.0, "green": 0.90, "blue": 0.45}}
            }
        }}},
    ]

    spreadsheet.batch_update({"requests": requests})


def _get_artiklar_sheet():
    """Öppnar eller skapar Artiklar-fliken i Google Kalkylark."""
    if _CREDENTIALS_JSON:
        creds = Credentials.from_service_account_info(json.loads(_CREDENTIALS_JSON), scopes=_SHEET_SCOPES)
    else:
        creds = Credentials.from_service_account_file(_CREDENTIALS_FILE, scopes=_SHEET_SCOPES)
    klient = gspread.Client(auth=creds)
    spreadsheet = klient.open_by_key(GOOGLE_SHEET_ID)
    try:
        return spreadsheet.worksheet("Artiklar")
    except Exception:
        ws = spreadsheet.add_worksheet(title="Artiklar", rows=1000, cols=8)
        ws.update(values=[["Slug","Titel","Meta-beskrivning","Nyckelord","Innehåll","Status","Skapad"]], range_name="A1")
        ws.freeze(rows=1)
        _sätt_status_dropdown(spreadsheet, ws)
        return ws


def generera_artikel(nyckelord: str) -> dict:
    """Genererar en SEO-artikel på svenska med Claude API."""
    if not ANTHROPIC_API_KEY:
        print("[ARTIKEL] ANTHROPIC_API_KEY saknas – hoppar över generering.")
        return {}
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Du är en erfaren SEO-redaktör för Guldkollen.se – en svensk prisjämförelsetjänst för guldförsäljning.

Skriv en SEO-optimerad artikel på korrekt svenska om: "{nyckelord}"

VIKTIGT – UNDVIK ÖVERLAPP MED BEFINTLIGA ARTIKLAR:
Följande ämnen finns redan på sajten – skriv INTE om dessa, och undvik att upprepa deras kärninnehåll:
- Sälja guld: tips för att få bästa pris (allmänna säljtips)
- Vad är mitt guld värt? (beräkna värdet själv, formel för karat × vikt × pris)
- Är det säkert att skicka guld med posten? (säkerhetspåse, försäkring, frakt)
- Skillnaden mellan 9K, 14K, 18K och 24K guld (karatförklaring)
- Sälja ärvda smycken (juridik, värdering, känslomässiga aspekter)
- Sälja guldmynt och guldtackor (samlingsvärde vs metallvärde)
- Hur värderar en guldköpare ditt guld? (värderingsprocessen)
- Guldpris idag – hur du läser och förstår guldpriset (spotpris, svängningar)
- 7 vanliga misstag när du säljer guld
- Sälja guldtänder och tandguld

SPRÅK OCH KVALITET (kritiskt):
- Felfritt, naturligt och flytande svenska – inga stavfel, inga syftningsfel
- Använd korrekt terminologi: "finhalt" (inte "finkärt"), rätt karatstandarder i Sverige: 9K (375‰), 14K (585‰), 18K (750‰), 24K (999‰)
- Hjälpsam och informativ ton – inte säljig

FORMATERING (kritiskt):
- Använd alltid HTML-listor: <ul><li>punkt</li></ul> – aldrig •-tecken i löptext
- Separata <ul>-listor för fördelar respektive nackdelar – aldrig ihopblandade
- Rubrikstruktur: en <h1>, sedan <h2> för varje avsnitt
- Stycken med <p>-taggar

CTA (kritiskt):
- Läsaren befinner sig redan på Guldkollen.se – skriv ALDRIG "Besök Guldkollen.se" eller en URL
- Hänvisa istället till verktyget på sidan, t.ex: "Använd jämförelseverktyget här på Guldkollen för att se vad just ditt guld är värt" eller "Scrolla upp och ange vikt och karat – du ser direkt vem som betalar mest"
- CTA ska kännas naturlig och hjälpsam, inte som en annons

INNEHÅLL:
- 700–900 ord
- Korrekt fakta om guldpriser och guldförsäljning i Sverige
- Gör inte påståenden om specifika företags rykte eller recensioner som inte kan verifieras

Returnera ENDAST giltig JSON utan markdown-kodblock, med exakt denna struktur:
{{"titel": "H1-rubrik (60–70 tecken)", "meta_beskrivning": "Beskrivning för Google (max 155 tecken)", "innehall": "Hela artikeln som korrekt HTML"}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def spara_artikel(slug: str, nyckelord: str, artikel: dict) -> None:
    """Sparar genererad artikel i Google Sheets som Utkast."""
    try:
        ws = _get_artiklar_sheet()
        if slug in ws.col_values(1)[1:]:
            print(f"[ARTIKEL] '{slug}' finns redan – hoppar över.")
            return
        nu = datetime.now(tz=STOCKHOLM).strftime("%Y-%m-%d %H:%M")
        ws.append_row([slug, artikel.get("titel",""), artikel.get("meta_beskrivning",""),
                       nyckelord, artikel.get("innehall",""), "Utkast", nu],
                      value_input_option="USER_ENTERED")
        print(f"[ARTIKEL] Sparat som utkast: {artikel.get('titel', slug)}")
    except Exception as e:
        print(f"[ARTIKEL] Fel vid sparande: {e}")


def generera_veckans_artikel() -> None:
    """Väljer nästa nyckelord och genererar en artikel automatiskt."""
    try:
        ws = _get_artiklar_sheet()
        befintliga = ws.col_values(1)[1:]
        nästa = next((kw for kw in ARTIKEL_KEYWORDS if kw["slug"] not in befintliga), None)
        if not nästa:
            print("[ARTIKEL] Alla nyckelord är genererade.")
            return
        print(f"[ARTIKEL] Genererar artikel: {nästa['nyckelord']}")
        artikel = generera_artikel(nästa["nyckelord"])
        if artikel:
            spara_artikel(nästa["slug"], nästa["nyckelord"], artikel)
    except Exception as e:
        print(f"[ARTIKEL] Fel vid veckogenerering: {e}")


# Schemalägg artikelgenerering varje måndag kl 08:00 (definieras här, efter att funktionen finns)
scheduler.add_job(generera_veckans_artikel, "cron", day_of_week="mon,thu", hour=8, minute=0)


# ── Artikel-endpoints ─────────────────────────────────────────────────────────

@app.get("/api/artiklar/setup")
def setup_artiklar_sheet():
    """Applicerar dropdown-validering på befintligt Artiklar-blad."""
    try:
        if _CREDENTIALS_JSON:
            creds = Credentials.from_service_account_info(json.loads(_CREDENTIALS_JSON), scopes=_SHEET_SCOPES)
        else:
            creds = Credentials.from_service_account_file(_CREDENTIALS_FILE, scopes=_SHEET_SCOPES)
        klient = gspread.Client(auth=creds)
        spreadsheet = klient.open_by_key(GOOGLE_SHEET_ID)
        ws = spreadsheet.worksheet("Artiklar")
        _sätt_status_dropdown(spreadsheet, ws)
        return {"status": "ok", "meddelande": "Dropdown för Status-kolumnen är nu aktiv i Artiklar-bladet."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/artiklar/generera")
def trigga_artikelgenerering():
    """Genererar nästa artikel manuellt. Samma logik som måndagsjobbet."""
    import threading
    threading.Thread(target=generera_veckans_artikel, daemon=True).start()
    return {"status": "started", "meddelande": "Artikelgenerering körs i bakgrunden. Kolla Google Sheets om ~30 sekunder."}


@app.get("/api/artiklar")
def get_artiklar():
    """Returnerar alla publicerade artiklar."""
    try:
        ws = _get_artiklar_sheet()
        rows = ws.get_all_records()
        return {"artiklar": [
            {"slug": r["Slug"], "titel": r["Titel"],
             "meta_beskrivning": r["Meta-beskrivning"], "skapad": r.get("Skapad", "")}
            for r in rows if r.get("Status") == "Publicerad"
        ]}
    except Exception as e:
        return {"artiklar": [], "fel": str(e)}


@app.get("/api/artiklar/{slug}")
def get_artikel(slug: str):
    """Returnerar en specifik publicerad artikel."""
    try:
        ws = _get_artiklar_sheet()
        for r in ws.get_all_records():
            if r["Slug"] == slug and r.get("Status") == "Publicerad":
                return {"slug": r["Slug"], "titel": r["Titel"],
                        "meta_beskrivning": r["Meta-beskrivning"],
                        "innehall": r["Innehåll"], "skapad": r.get("Skapad", "")}
        raise HTTPException(status_code=404, detail="Artikel ej hittad")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/robots.txt", response_class=Response)
def robots():
    content = """User-agent: *
Allow: /
Sitemap: https://guldkollen.se/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml", response_class=Response)
def sitemap():
    aktörer_slugs = [
        ("guldbrev",        "Guldbrev"),
        ("diamantbrev",     "Diamantbrev"),
        ("pantit",          "Pantit"),
        ("noblex",          "Noblex"),
        ("finguld",         "Finguld"),
        ("kaplans",         "Kaplans Ädelmetall"),
        ("guldcentralen",   "Guldcentralen"),
        ("pantbanken",      "Pantbanken"),
        ("webbguld",        "WebbGuld"),
        ("guldfynd",        "Guldfynd"),
        ("capitaurum",      "Capitaurum"),
        ("smsguld",         "SMSGuld"),
    ]
    idag = datetime.now(tz=STOCKHOLM).strftime("%Y-%m-%d")
    urls = [
        f"""  <url>
    <loc>https://guldkollen.se/</loc>
    <lastmod>{idag}</lastmod>
    <changefreq>hourly</changefreq>
    <priority>1.0</priority>
  </url>""",
        f"""  <url>
    <loc>https://guldkollen.se/guldpris-idag</loc>
    <lastmod>{idag}</lastmod>
    <changefreq>hourly</changefreq>
    <priority>0.9</priority>
  </url>""",
    ]
    for slug, _ in aktörer_slugs:
        urls.append(f"""  <url>
    <loc>https://guldkollen.se/{slug}</loc>
    <lastmod>{idag}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>""")

    # Lägg till publicerade artiklar dynamiskt från Google Sheets
    try:
        ws = _get_artiklar_sheet()
        for r in ws.get_all_records():
            if r.get("Status") == "Publicerad":
                pub = r.get("Publicerad", idag)[:10] if r.get("Publicerad") else idag
                urls.append(f"""  <url>
    <loc>https://guldkollen.se/artikel/{r['Slug']}</loc>
    <lastmod>{pub}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>""")
    except Exception as e:
        print(f"[SITEMAP] Kunde inte hämta artiklar: {e}")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "\n".join(urls)
    xml += "\n</urlset>"
    return Response(content=xml, media_type="application/xml")


@app.get("/")
def root():
    hämtad = latest_prices.get("hämtad", "okänd")
    return {
        "status": "ok",
        "priser_hämtade": hämtad,
        "endpoints": {
            "GET /priser": "Aktuella guldpriser",
            "GET /reload": "Ladda om senaste prisfil utan omstart",
            "POST /order": "Skicka orderbekräftelse"
        }
    }
