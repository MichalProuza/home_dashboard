# home_dashboard

Osobní domácí dashboard pro Vranov u Brna: počasí, meteostanice Netatmo,
fotovoltaika Growatt, stav brány a garáže (Tuya), rodinný kalendář, úkoly
z Microsoft To Do, jídelníček školní jídelny a plán akcí ZŠ. Běží jako statická
stránka bez frameworku a bez build kroku; data sbírají Python skripty
v GitHub Actions.

## Jak to funguje

```
Cloudflare Worker (cron každých 10 min)          tlačítko „obnovit"
        │ workflow_dispatch                              │ POST /api/refresh
        ▼                                                ▼
GitHub Actions  ──►  scripts/fetch_*.py  ──►  data/<zdroj>.json
                                                         │ scripts/publish_data.sh
                                                         ▼
                                              větev `data` (jen JSON)
                                                         │
        Cloudflare Pages Function /api/data/<zdroj>.json │  (na *.github.io přímo raw.githubusercontent.com)
                                                         ▼
                              index.html · kiosk.html · kiosk-ios27.html
```

- **Větev `data`.** Workflowy necommitují vygenerovaný JSON do `main`.
  `scripts/publish_data.sh` ho ukládá do kořene samostatné větve `data`, vedle
  něj i zašifrované rotující refresh tokeny Netatmo a Microsoft To Do
  (`*_token.enc`). Soubory `data/*.json` v `main` jsou jen ukázková data pro
  lokální vývoj.
- **Plánovač.** Plánované běhy (`schedule`) pouští GitHub jen několikrát denně,
  proto workflowy spouští Cloudflare Worker `workers/scheduler/` přes
  `workflow_dispatch`: mezi 5:00 a 7:59 pražského času každých 10 minut
  (Netatmo, Tuya, Growatt, počasí, To Do), jinak každé 2 hodiny (navíc
  kalendář), v 5:00 navíc jídelníček a akce ZŠ. Rozvrh je ve funkci
  `pickWorkflows()`. Crony ve workflowech zůstávají jako záloha.
- **Hosting.** Web je nasazený na Cloudflare Pages za Cloudflare Access.
  Frontend čte data ze same-origin funkce `functions/api/data/[name].js`,
  tlačítko „obnovit" volá `functions/api/refresh.js`, která spustí workflowy
  živých zdrojů. Na doméně `*.github.io` frontend čte větev `data` přímo
  z `raw.githubusercontent.com` a tlačítko jen znovu načte data.
- Repozitář i větev `data` jsou veřejné, takže publikovaný JSON (včetně názvů
  úkolů a událostí kalendáře) je veřejně čitelný. Důvody jsou v `CLOUDFLARE.md`.

## Frontendy

| Soubor | K čemu |
|--------|--------|
| `index.html` | Hlavní dashboard pro telefon a počítač. Počasí bere přímo z Open-Meteo (`weather.json` je záloha), Microsoft To Do přes přihlášení v prohlížeči (OAuth2 + PKCE). |
| `tasks.html` | Správa místních úkolů uložených v `localStorage` prohlížeče; zobrazuje je jen `index.html`. |
| `kiosk.html` | Nástěnný iPad Air 1 (Safari 12). Všechna data jen z JSON ve větvi `data`, noční ztmavení 22–6 h. |
| `kiosk-ios27.html` | Stejná data a logika jako `kiosk.html`, vzhled podle novějšího iOS, stále kompatibilní se Safari 12. |

Oba kiosky musí zůstat spustitelné v Safari 12 (žádné `?.`, `??`, flex `gap`
apod.). Hlídá to `check_compat.sh`, viz níže.

`garmin-watchface/` je samostatný ciferník pro hodinky Garmin (Connect IQ).
Data dashboardu nepoužívá a má vlastní README.

## Datové zdroje

| Zdroj | Skript | Workflow | Výstup |
|-------|--------|----------|--------|
| Fotovoltaika Growatt | `scripts/fetch_growatt.py` | `growatt.yml` | `growatt.json` |
| Brána a garáž (Tuya IoT Cloud) | `scripts/fetch_tuya.py` | `tuya.yml` | `tuya.json` |
| Meteostanice Netatmo | `scripts/fetch_netatmo.py` | `netatmo.yml` | `netatmo.json` |
| Počasí (Open-Meteo) | `scripts/fetch_weather.py` | `weather.yml` | `weather.json` |
| Kalendář (iCal) | `scripts/fetch_calendar.py` | `calendar.yml` | `calendar.json` |
| Microsoft To Do | `scripts/fetch_mstodo.py` | `mstodo.yml` | `mstodo.json` |
| Jídelníček (skolavranov.cz) | `scripts/fetch_school_menu.py` | `school_menu.yml` | `school_menu.json` |
| Plán akcí ZŠ (skolavranov.cz) | `scripts/fetch_school_calendar.py` | `school_calendar.yml` | `school_calendar.json` |

Každý JSON má obálku `updated` (čas v UTC) a `error` (`null` nebo popis chyby).
Frontendy u živých zdrojů ukazují stáří dat a starší data označí varováním.

## Co je potřeba nastavit

**GitHub → Settings → Secrets and variables → Actions**

| Zdroj | Secrets |
|-------|---------|
| Growatt | `GROWATT_API_TOKEN`, nebo `GROWATT_USER` + `GROWATT_PASS` |
| Tuya | `TUYA_ACCESS_ID`, `TUYA_ACCESS_SECRET`, `TUYA_DEVICE_ID`; volitelně `TUYA_DEVICE_ID_2`, `TUYA_DEVICE_ID_3`, `TUYA_REGION` |
| Netatmo | `NETATMO_CLIENT_ID`, `NETATMO_CLIENT_SECRET`, `NETATMO_REFRESH_TOKEN`, `NETATMO_TOKEN_KEY` |
| Kalendář | `CALENDAR_ICS_URL` |
| Microsoft To Do | `MSTODO_CLIENT_ID`, `MSTODO_REFRESH_TOKEN`, `MSTODO_TOKEN_KEY`; volitelně `MSTODO_TENANT`, `MSTODO_LIST` |

Počasí a oba školní zdroje žádné přihlašovací údaje nepotřebují.

**Cloudflare**

| Kde | Secret | Oprávnění GitHub tokenu |
|-----|--------|-------------------------|
| Pages projekt | `GH_DATA_TOKEN` | Contents: Read-only |
| Pages projekt a Worker plánovače | `GH_ACTIONS_TOKEN` | Actions: Read and write |

Oba tokeny jsou fine-grained, omezené na tento repozitář, a mají expiraci.
Postup nasazení, Cloudflare Access a údržba jsou v `CLOUDFLARE.md`. Worker
plánovače se nenasazuje automaticky: po změně `workers/scheduler/index.js` je
potřeba kód do Workeru vložit znovu.

Microsoft To Do v `index.html` navíc potřebuje v Azure registraci aplikace
redirect URI typu SPA s adresou dashboardu.

## Lokální spuštění

```bash
python3 -m http.server 8000
# http://localhost:8000/            hlavní dashboard
# http://localhost:8000/kiosk.html  kiosk
```

Na `localhost` funkce `/api/data/` neexistuje, takže frontendy spadnou na
ukázkové soubory `data/*.json`. Některé z nich jsou prázdné (Growatt, Netatmo,
počasí), příslušné sekce pak ukážou chybu nebo prázdný stav.

Stahovací skript jde spustit samostatně s proměnnými prostředí, zapíše do
`data/<zdroj>.json`:

```bash
pip install requests
TUYA_ACCESS_ID=… TUYA_ACCESS_SECRET=… TUYA_DEVICE_ID=… python3 scripts/fetch_tuya.py
```

Závislosti jednotlivých skriptů jsou v kroku „Install dependencies"
příslušného workflow. Výstup takového běhu do `main` necommituj
(`git checkout -- data/`).

## Kontroly

Automatické testy tu nejsou. Před commitem pomáhají tři skripty:

```bash
bash .claude/skills/kiosk-safari12/scripts/check_compat.sh                  # kiosky × Safari 12
python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py  # tvar data/*.json
bash .claude/skills/dashboard-frontend/scripts/check_parity.sh              # zdroj ve všech třech frontendech
python3 -m py_compile scripts/*.py
```

## Další dokumentace

- `CLAUDE.md` – podrobná mapa repozitáře: sekce dashboardu, schémata JSON,
  konvence skriptů a commitů.
- `CLOUDFLARE.md` – nasazení na Cloudflare Pages, Access, tokeny, plánovač.
- `.claude/skills/README.md` – projektové skilly pro Claude Code a kontrolní
  skripty.
