# api.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel
from typing import Optional
import gspread
from google.oauth2.service_account import Credentials
import sys, os, json
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from guldpris_scraper import AKTÖRER, KARAT_ORDER

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])

latest_prices: dict = {}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_sheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON saknas i miljövariablerna")
    creds_data = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open("saljguldet.se ordrar")
    return spreadsheet.worksheet("Blad1")


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
    print("[SCRAPER] Klar!")


kör_scraper()
scheduler = BackgroundScheduler()
scheduler.add_job(kör_scraper, "cron", hour="0,4,8,12,16,20", minute=0)
scheduler.start()


# ── Ordermodell ───────────────────────────────────────────────────────────────

class Order(BaseModel):
    # Köpare & pris
    kopare: str
    karat: int
    gram: float
    totalPris: float
    # Leverans
    leveranssatt: str                  # "envelope" | "instore"
    # Personuppgifter
    fornamn: str
    efternamn: str
    personnummer: str
    epost: str
    telefon: str
    # Adress (ej obligatorisk vid butiksinlämning)
    gata: Optional[str] = None
    postnummer: Optional[str] = None
    ort: Optional[str] = None
    # Övrigt
    kommentar: Optional[str] = None
    skapadAt: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/priser")
def get_priser():
    if not latest_prices:
        return {"error": "Inga priser hittades ännu."}
    return latest_prices


@app.post("/order")
def ta_emot_order(order: Order):
    try:
        sheet = get_sheet()

        # Lägg till rubrikrad om arket är tomt
        if not sheet.row_values(1):
            sheet.append_row([
                "Tidsstämpel", "Köpare", "Karat", "Vikt (g)", "Totalpris (kr)",
                "Leveranssätt", "Förnamn", "Efternamn", "Personnummer",
                "E-post", "Telefon", "Gatuadress", "Postnummer", "Ort", "Kommentar"
            ])

        sheet.append_row([
            order.skapadAt,
            order.kopare,
            f"{order.karat}K",
            order.gram,
            order.totalPris,
            order.leveranssatt,
            order.fornamn,
            order.efternamn,
            order.personnummer,
            order.epost,
            order.telefon,
            order.gata or "",
            order.postnummer or "",
            order.ort or "",
            order.kommentar or "",
        ])

        print(f"[ORDER] Sparad: {order.fornamn} {order.efternamn} – {order.kopare} – {order.karat}K {order.gram}g")
        return {"status": "ok", "meddelande": "Order sparad!"}

    except Exception as e:
        print(f"[FEL] Order kunde inte sparas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
def root():
    return {"status": "ok", "info": "Gå till /priser för aktuella guldpriser."}
