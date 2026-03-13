# api.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
import json, glob, os, sys

# Lägg till mappen i path så att guldpris_scraper kan importeras
sys.path.append(os.path.dirname(__file__))
from guldpris_scraper import AKTÖRER, save_json
from datetime import datetime

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])


def kör_scraper():
    print(f"[SCRAPER] Kör kl {datetime.now().strftime('%H:%M')}...")
    now = datetime.now()
    all_prices = {}
    for name, fetcher in AKTÖRER:
        try:
            all_prices[name] = fetcher()
        except Exception as e:
            print(f"[FEL] {name}: {e}")
            all_prices[name] = {}
    save_json(all_prices, now)
    print("[SCRAPER] Klar!")


# Kör scrapern vid start och sedan varje timme
kör_scraper()
scheduler = BackgroundScheduler()
scheduler.add_job(kör_scraper, "interval", hours=1)
scheduler.start()


@app.get("/priser")
def get_priser():
    filer = sorted(glob.glob("Guldpriser/*.json"))
    if not filer:
        return {"error": "Inga priser hittades ännu."}
    with open(filer[-1], encoding="utf-8") as f:
        return json.load(f)


@app.get("/")
def root():
    return {"status": "ok", "info": "Gå till /priser för aktuella guldpriser."}
