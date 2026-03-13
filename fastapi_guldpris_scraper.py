# api.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
import sys, os

sys.path.append(os.path.dirname(__file__))
from guldpris_scraper import AKTÖRER, KARAT_ORDER
from datetime import datetime

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])

# Lagra senaste priserna i minnet
latest_prices: dict = {}


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


# Kör scrapern vid start och sedan varje timme
kör_scraper()
scheduler = BackgroundScheduler()
scheduler.add_job(kör_scraper, "interval", hours=1)
scheduler.start()


@app.get("/priser")
def get_priser():
    if not latest_prices:
        return {"error": "Inga priser hittades ännu."}
    return latest_prices


@app.get("/")
def root():
    return {"status": "ok", "info": "Gå till /priser för aktuella guldpriser."}
