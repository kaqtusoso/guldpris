# api.py  –  Fungerar både lokalt och på Railway
#
# Lokalt:  bash run_api.sh   (läser .env-filen)
# Railway: sätts upp via environment variables i Railway-dashboarden

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel, EmailStr
import sys, os, uuid, json, glob
from datetime import datetime

# Ladda .env-fil om den finns (för lokal körning)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from guldpris_scraper import AKTÖRER, KARAT_ORDER, save_json

import sendgrid
from sendgrid.helpers.mail import Mail

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

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
MAIL_FROM        = os.environ.get("MAIL_FROM", "noreply@saljguldet.se")
GOOGLE_SHEET_ID  = os.environ.get("GOOGLE_SHEET_ID", "")

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

def kör_scraper():
    global latest_prices
    now = datetime.now()
    print(f"[SCRAPER] Kör kl {now.strftime('%H:%M')}...")
    all_prices = {}
    for name, fetcher in AKTÖRER:
        try:
            all_prices[name] = fetcher()
        except Exception as e:
            print(f"[FEL] {name}: {e}")
            all_prices[name] = {}
    latest_prices = {
        "hämtad": now.strftime("%Y-%m-%d %H:%M"),
        "priser": {
            aktör: {
                karat: priser[karat]
                for karat in KARAT_ORDER
                if karat in priser
            }
            for aktör, priser in all_prices.items()
        },
    }
    # Spara till JSON-fil så att data finns kvar vid omstart av API:et
    save_json(all_prices, now)
    print("[SCRAPER] Klar!")


# Vid start: ladda senaste sparade data (snabbt). Om ingen fil finns, kör scraper direkt.
if not ladda_senaste_json():
    print("[STARTUP] Ingen sparad data hittades – kör scraper nu (kan ta en stund)...")
    kör_scraper()

# Kör scraper varje timme automatiskt (fungerar både lokalt och på Railway)
scheduler = BackgroundScheduler()
scheduler.add_job(kör_scraper, "interval", hours=1)
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


@app.get("/reload")
def reload_priser():
    """Läser in senaste sparade JSON-filen utan att starta om API:et."""
    if ladda_senaste_json():
        hämtad = latest_prices.get("hämtad", "okänd")
        return {"status": "ok", "meddelande": f"Priser laddade om. Senaste: {hämtad}"}
    raise HTTPException(status_code=404, detail="Ingen sparad prisfil hittades.")


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
