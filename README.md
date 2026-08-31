# Home Dashboard — Vranov u Brna

Osobní domácí dashboard pro Vranov u Brna. Statická single-page aplikace bez
frameworku a bez build kroku — data sbírají Python skripty spouštěné přes
GitHub Actions a publikované jako JSON na větev `data`.

Dashboard běží na **https://dashboard.prouza.co.uk** (Cloudflare Pages +
Cloudflare Access — detaily nasazení v [CLOUDFLARE.md](CLOUDFLARE.md)).

## Stránky

| Soubor | Účel |
|--------|------|
| `index.html` | Hlavní dashboard (HTML + CSS + JS v jednom souboru) |
| `tasks.html` | Správce úkolů (localStorage `dashboard_tasks`) |
| `kiosk.html` | Zjednodušený kiosk pro staré prohlížeče (Safari 12 / iPad Air 1), včetně nočního ztlumení |
| `kiosk-ios27.html` | Kiosk ve stylu moderního iOS („Liquid Glass"), stále Safari 12 kompatibilní |

## Co dashboard zobrazuje

- **Počasí** — Open-Meteo (přímo z prohlížeče, fallback `weather.json`)
- **Meteostanice Netatmo** — teploty, CO₂, vlhkost, hluk (s 24h grafem), srážky
- **Senzory Tuya** — stav brány a garáže
- **Fotovoltaika Growatt** — výroba, baterie (s 24h grafem SoC), síť, spotřeba
- **Kalendář** — události z Google Kalendáře (iCal)
- **Microsoft To Do** — v prohlížeči přes OAuth2 + PKCE, na kiosku ze server-side `mstodo.json`
- **Jídelníček MŠ** a **plán akcí ZŠ** — scraping webů školy
- **Úkoly** — lokální seznam v localStorage

## Architektura

```
GitHub Actions (plánované / ruční)
  └─► scripts/fetch_*.py  →  external API (Growatt, Tuya, Netatmo, Open-Meteo,
        │                     iCal, Microsoft Graph, weby školy)
        └─► data/*.json  →  scripts/publish_data.sh  →  větev "data"

Frontend (statika)
  └─► čte JSON z větve "data" (raw.githubusercontent.com, nebo same-origin
      Cloudflare Pages Function /api/data/:name), fallback lokální ./data/
  └─► Open-Meteo a Microsoft Graph volá přímo z prohlížeče
```

Workflowy necommitují generovaný JSON do `main` — publikují ho na samostatnou
větev **`data`**. Soubory v `data/` na `main` jsou jen seed/fallback pro lokální
vývoj. Větev `data` je jednorázově smazatelná (obnoví se dalším během workflow);
pozor jen na uložené šifrované rotující tokeny (`netatmo_token.enc`,
`mstodo_token.enc`) — po smazání je potřeba nový seed refresh token.

## Struktura repozitáře

```
home_dashboard/
├── index.html / tasks.html / kiosk.html / kiosk-ios27.html
├── scripts/               # Python fetch skripty + publish_data.sh
├── data/                  # seed/fallback JSON (živá data jsou na větvi "data")
├── functions/api/data/    # Cloudflare Pages Function — proxy na větev "data"
├── garmin-watchface/      # ciferník Garmin (Connect IQ) — samostatný projekt
├── .github/workflows/     # plánované fetch workflowy
├── CLAUDE.md              # podrobná dokumentace pro vývoj (schémata JSON, secrets…)
├── CLOUDFLARE.md          # nasazení na Cloudflare Pages + Access
└── Odkazy.md              # užitečné odkazy
```

## Technologie

- **Frontend:** vanilla HTML5 / CSS3 / JavaScript (ES6+; kiosk ES2017-safe) — žádný framework, žádný bundler
- **Skripty:** Python 3.11 (`growattServer`, `requests`, `beautifulsoup4`, `icalendar`, `recurring-ical-events`, `cryptography`)
- **Hosting:** Cloudflare Pages (statika + Pages Functions)
- **Automatizace:** GitHub Actions (rozvrhy po 15–30 min, denní scraping školy)

## Vývoj

Není tu žádný package manager ani build — soubory se editují přímo a pushnou;
push do `main` automaticky redeployne Cloudflare Pages.

Lokální spuštění frontendu (kvůli relativním fetch cestám):

```bash
python -m http.server
```

Lokální běh skriptu (credentials přes env proměnné):

```bash
GROWATT_USER=me GROWATT_PASS=secret python scripts/fetch_growatt.py
```

Serverové credentials žijí v **GitHub Secrets** a injektují se jen v Actions;
jediný hardcoded údaj ve frontendu je veřejné `MSTODO_CLIENT_ID` pro PKCE flow.
Kompletní přehled secrets, JSON schémat a konvencí je v [CLAUDE.md](CLAUDE.md).
