# ── Lägg till detta i din api.py ──────────────────────────────────────────────
#
# 1. Installera sendgrid:  pip install sendgrid
#    Lägg till "sendgrid" i requirements.txt
#
# 2. Sätt miljövariabel i Railway:
#    SENDGRID_API_KEY  = ditt SendGrid API-nyckel
#    MAIL_FROM         = din avsändaradress (verifierad i SendGrid)
#
# 3. Klistra in importerna och koden nedan i din befintliga api.py
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel, EmailStr
import sys, os, uuid
from datetime import datetime

sys.path.append(os.path.dirname(__file__))
from guldpris_scraper import AKTÖRER, KARAT_ORDER

import sendgrid
from sendgrid.helpers.mail import Mail

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])

latest_prices: dict = {}

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
MAIL_FROM        = os.environ.get("MAIL_FROM", "noreply@dittforetag.se")


# ── Datamodell för order ──────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    namn: str
    email: EmailStr
    telefon: str | None = None
    karat: str              # t.ex. "18K"
    vikt_gram: float        # kundens uppskattning
    meddelande: str | None = None


# ── HTML-mailmall ─────────────────────────────────────────────────────────────

def bygg_mail_html(order_id: str, order: OrderRequest, pris_per_gram: float | None) -> str:
    pris_rad = ""
    if pris_per_gram:
        uppskattat = round(pris_per_gram * order.vikt_gram, 2)
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
    if order.meddelande:
        meddelande_rad = f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Ditt meddelande</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;font-style:italic;">{order.meddelande}</td>
        </tr>
        """

    telefon_rad = ""
    if order.telefon:
        telefon_rad = f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Telefon</td>
          <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.telefon}</td>
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
            <p style="margin:0 0 8px;font-size:22px;color:#2c2c2c;">Tack, {order.namn}!</p>
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
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.namn}</td>
              </tr>
              <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">E-post</td>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.email}</td>
              </tr>
              {telefon_rad}
              <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Karat</td>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.karat}</td>
              </tr>
              <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;color:#666;">Uppgiven vikt</td>
                <td style="padding:8px 12px;border-bottom:1px solid #f0e6c8;">{order.vikt_gram} gram</td>
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
            <a href="mailto:brjanssonp@gmail.com" style="color:#b8860b;">info@dittforetag.se</a>
            eller ring <a href="tel:+46XXXXXXXX" style="color:#b8860b;">070-232 06 15</a>.
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


# ── Endpoint ──────────────────────────────────────────────────────────────────

@app.post("/order")
def skicka_orderbekräftelse(order: OrderRequest):
    """
    Ta emot en order och skicka bekräftelsemail till kunden.

    Exempel-body:
    {
      "namn": "Anna Svensson",
      "email": "anna@exempel.se",
      "telefon": "070-123 45 67",
      "karat": "18K",
      "vikt_gram": 12.5,
      "meddelande": "Ringen har en liten diamant, spelar det roll?"
    }
    """
    order_id = str(uuid.uuid4())[:8].upper()
    dagspris = hämta_dagspris(order.karat)
    html     = bygg_mail_html(order_id, order, dagspris)

    try:
        skicka_mail(order.email, order.namn, html, order_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status":    "skickat",
        "order_id":  order_id,
        "dagspris":  dagspris,
        "mottagare": order.email,
    }


# ── Scraper-delen (oförändrad) ────────────────────────────────────────────────

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


@app.get("/priser")
def get_priser():
    if not latest_prices:
        return {"error": "Inga priser hittades ännu."}
    return latest_prices


@app.get("/")
def root():
    return {"status": "ok", "info": "Gå till /priser för priser, POST /order för orderbekräftelse."}
