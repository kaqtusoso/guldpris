# Memory – Guldkollen.se

## Projektet
**Guldkollen.se** – prisjämförelsetjänst för att sälja guld i Sverige. Användaren anger vikt + karat, och tjänsten visar realtidspriser från flera guldköpare (Noblex, Guldbrev, Kaplans, Guldcentralen m.fl.) sorterade från bäst till sämst. **Nystartat – noll användare idag (april 2026).**

## Kärnmålgrupp
Se full analys: memory/audience/målgrupp.md

**Primär:** Kvinna 45–65 år, har ärvt eller hittat guld i byrålådan, vet inte vart hon ska vända sig och är rädd att bli lurad.
**Sekundär:** Man/kvinna 35–55 år i ekonomisk press (skuld, räkningar, separation), behöver pengar snabbt.
**Tertiär:** Privatpersoner 30–60 år som rensar ut – inte akut behov, men vill ha rimligt pris.

## Aktiva projekt
| Namn | Vad |
|------|-----|
| **Guldkollen.se** | Prisjämförelse guldköpare Sverige, nystart |
| **Google Ads** | Aktiv kampanj sedan 28 april 2026 – se memory/marketing/google-ads-kampanj.md |

## Teknisk infrastruktur
- **Railway API:** https://web-production-5273.up.railway.app/
  - `/priser` – hämtar aktuella priser
  - `/scrape` – triggar manuell scrape
  - `/debug/webbguld` – diagnostik för WebbGuld

## Marknadsföring
- Kanal 1: **Facebook/Meta** (cold audience, emotionellt driven)
- Kanal 2: **Google Search** (intent-driven, söker redan)
- Strategi: Medvetandetrappan – se memory/marketing/annonsstrategi.md

## Konkurrenter
Guldbrev, Noblex, Guldcentralen, Kaplans, Finguld, Guldexperten, Svenska Guld, Tavex

## SEO
- Ca 10 artiklar publicerade (april 2026)
- Bot genererar 2 nya artiklar per vecka med relevanta sökord

## Preferenser
- Pascal vill alltid ha annonser kopplade till medvetandetrappan
- Spara all marknadsföringsstrategi i memory/marketing/
