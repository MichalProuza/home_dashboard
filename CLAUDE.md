# CLAUDE.md — home_dashboard

Personal home dashboard for Vranov u Brna (Czech Republic). Static single-page
app hosted on GitHub Pages, with data collected by Python scripts running via
GitHub Actions.

---

## Repository layout

```
home_dashboard/
├── index.html                      # Entire frontend: HTML + CSS + JS in one file
├── tasks.html                      # Task manager page (localStorage `dashboard_tasks`)
├── kiosk.html                      # Simplified kiosk view for old browsers (Safari 12 / iPad Air 1): ES2017-safe JS, data-branch JSON only (incl. Microsoft To Do via server-side fetch), no localStorage Tasks, built-in night dimming
├── kiosk-ios27.html                # Kiosk view styled after modern iOS (iOS 26/27 "Liquid Glass") but kept Safari 12 / iPad Air 1 compatible: same data sources/logic + ES2017-safe JS as kiosk.html, glass look via translucent cards + light -webkit-backdrop-filter, NO flex gap / clamp() / inset shorthand (margins + grid-gap instead), SF Pro system font
├── scripts/
│   ├── fetch_growatt.py            # Solar system data from Growatt API
│   ├── fetch_tuya.py               # Tuya sensor status (gate, garage) from Tuya IoT Cloud
│   ├── fetch_netatmo.py            # Netatmo station data + noise history (rotating token)
│   ├── fetch_weather.py            # Open-Meteo forecast (server-side fallback for the browser)
│   ├── fetch_school_menu.py        # School lunch menu scraper
│   ├── fetch_school_calendar.py    # School (ZŠ) event plan scraper
│   ├── fetch_calendar.py           # Google Calendar events via iCal
│   ├── fetch_mstodo.py             # Microsoft To Do tasks (rotating token) — server-side so the kiosk can show them
│   └── publish_data.sh             # Publishes data/*.json to the "data" branch
├── data/                           # Seed/fallback only — live data is on the "data" branch
│   ├── growatt.json
│   ├── tuya.json
│   ├── netatmo.json
│   ├── weather.json
│   ├── school_menu.json
│   ├── school_calendar.json
│   ├── calendar.json
│   └── mstodo.json
├── garmin-watchface/               # Garmin watch face (Connect IQ, separate project)
├── Odkazy.md                        # Useful links (Tuya, etc.)
└── .github/workflows/
    ├── growatt.yml                 # fetch_growatt.py (15 min daytime, hourly at night)
    ├── tuya.yml                    # fetch_tuya.py (every 30 min + manual)
    ├── netatmo.yml                 # fetch_netatmo.py (every 15 min + manual)
    ├── weather.yml                 # fetch_weather.py (every 30 min + manual)
    ├── school_menu.yml             # fetch_school_menu.py (weekdays 05:00 UTC)
    ├── school_calendar.yml         # fetch_school_calendar.py (daily 05:00 UTC)
    ├── calendar.yml                # fetch_calendar.py (every hour + manual)
    └── mstodo.yml                  # fetch_mstodo.py (every 30 min + manual)
```

### The `data` branch

Workflows do **not** commit generated JSON to `main` (that used to flood the
history with bot commits). Instead `scripts/publish_data.sh` pushes the files
to the root of a dedicated **`data` branch** (auto-created on first run). The
frontend reads them from
`https://raw.githubusercontent.com/MichalProuza/home_dashboard/data/<name>.json`
with a fallback to the local `./data/<name>.json` seed files in `main`
(used for local development or while the `data` branch does not exist yet).
The `data` branch is disposable — it can be deleted at any time to reset its
history and will be recreated by the next workflow run (note: deleting it also
deletes `netatmo_token.enc`, so Netatmo then needs a fresh
`NETATMO_REFRESH_TOKEN` seed).

---

## Technology stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML5 / CSS3 / JavaScript (ES6+) — no framework, no build step |
| Backend scripts | Python 3.11 |
| Python deps | `growattServer`, `requests`, `beautifulsoup4`, `icalendar`, `recurring-ical-events`, `cryptography` |
| Hosting | GitHub Pages (static) |
| Automation | GitHub Actions |
| Data transport | JSON files committed to the repo, served as static assets |

There is **no package manager, no bundler, no transpiler**. Edit files directly
and push — GitHub Pages redeploys automatically.

---

## Dashboard sections (index.html)

The page renders these sections in order, each populated by a dedicated async
function called inside `initAll()`:

| Section | JS function | Data source |
|---------|-------------|-------------|
| Clock / date | `updateClock()` | `Date` API, runs every second |
| Weather (Počasí) | `fetchWeather()` | Open-Meteo API directly, fallback `weather.json` (data branch) — Open-Meteo blocks some ISP IP ranges |
| Netatmo weather station | `fetchNetatmo()` | `netatmo.json` (data branch) |
| Tuya sensors (gate, garage) | `fetchTuya()` | `tuya.json` (data branch) |
| Solar system (Growatt) | `fetchGrowatt()` | `growatt.json` (data branch) |
| Calendar (Kalendář) | `fetchCalendar()` | `calendar.json` (data branch) |
| Microsoft To Do | `fetchMsTodo()` | Microsoft Graph API (OAuth2 + PKCE) via browser |
| School menu (Jídelníček MŠ) | `fetchSchoolMenu()` | `school_menu.json` (data branch) |
| School events (Plán akcí ZŠ) | `fetchZsCalendar()` | `school_calendar.json` (data branch) |
| Tasks (Úkoly) | `renderTasks()` | `localStorage` (`dashboard_tasks`), managed via `tasks.html` |

`initAll()` first runs `handleMsTodoCallback()` (OAuth2 redirect handling),
then calls all fetch functions via `Promise.allSettled`, and finally
`renderTasks()`. It is called on page load, every 15 minutes via
`setInterval`, and when the tab becomes visible again after >5 minutes
(`visibilitychange`). A `_refreshing` flag prevents overlapping runs.

Shared helpers at the top of the script: `esc()` (HTML-escapes all external
strings before they are inserted via `innerHTML`), `fetchJson()` (fetch with
`cache: 'no-store'`, a 15 s timeout, and an HTTP status check) and
`fetchDataJson(name)` (loads workflow-generated JSON from the `data` branch
with a fallback to local `./data/`). Use them for any new section.

---

## Configuration (constants at top of `<script>` in index.html)

```js
// Source of workflow-generated data: "data" branch, fallback to local ./data/
const DATA_BRANCH_BASE = 'https://raw.githubusercontent.com/MichalProuza/home_dashboard/data/';
const GROWATT_JSON_URL     = 'growatt.json';
const TUYA_JSON_URL        = 'tuya.json';
const CALENDAR_JSON_URL    = 'calendar.json';
const SCHOOL_MENU_URL      = 'school_menu.json';
const ZS_CALENDAR_JSON_URL = 'school_calendar.json';
const NETATMO_JSON_URL     = 'netatmo.json';
const WEATHER_JSON_URL     = 'weather.json';

// Microsoft To Do (OAuth2 Authorization Code + PKCE — no client_secret needed)
// Register app at https://portal.azure.com → App registrations
// Redirect URI type must be "Single-page application (SPA)"
const MSTODO_CLIENT_ID = '...';      // Client ID from Azure portal (hardcoded)
const MSTODO_TENANT    = 'consumers'; // 'consumers' = personal MS accounts only

// Geographic coordinates for Open-Meteo
const LAT = 49.043, LON = 16.558;  // Vranov u Brna
```

`MSTODO_CLIENT_ID` is hardcoded in `index.html` — it is a public client ID
needed for the browser-based PKCE flow. No client secrets live in the
frontend (Netatmo moved server-side for exactly this reason).

Server-side credentials (API keys, passwords) live in **GitHub Secrets** and
are injected only during GitHub Actions runs.

| Secret | Used by |
|--------|---------|
| `GROWATT_API_TOKEN` | `fetch_growatt.py` (official V1 API; generate in the ShinePhone app: Me → account name → API Token) |
| `GROWATT_USER` | `fetch_growatt.py` (legacy fallback) |
| `GROWATT_PASS` | `fetch_growatt.py` (legacy fallback) |
| `TUYA_ACCESS_ID` | `fetch_tuya.py` |
| `TUYA_ACCESS_SECRET` | `fetch_tuya.py` |
| `TUYA_DEVICE_ID` | `fetch_tuya.py` |
| `TUYA_DEVICE_ID_2` | `fetch_tuya.py` (optional second device) |
| `TUYA_DEVICE_ID_3` | `fetch_tuya.py` (optional third device) |
| `TUYA_REGION` | `fetch_tuya.py` |
| `CALENDAR_ICS_URL` | `fetch_calendar.py` |
| `NETATMO_CLIENT_ID` | `fetch_netatmo.py` |
| `NETATMO_CLIENT_SECRET` | `fetch_netatmo.py` |
| `NETATMO_REFRESH_TOKEN` | `fetch_netatmo.py` (seed; generate at dev.netatmo.com → Token generator, scope `read_station`) |
| `NETATMO_TOKEN_KEY` | `fetch_netatmo.py` (any long random string; encrypts the stored rotating refresh token) |
| `MSTODO_CLIENT_ID` | `fetch_mstodo.py` (Azure app / public client ID; may be the same one as the frontend) |
| `MSTODO_REFRESH_TOKEN` | `fetch_mstodo.py` (seed; refresh token with scope `Tasks.Read offline_access`) |
| `MSTODO_TOKEN_KEY` | `fetch_mstodo.py` (any long random string; encrypts the stored rotating refresh token) |
| `MSTODO_TENANT` | `fetch_mstodo.py` (optional; defaults to `consumers`) |
| `MSTODO_LIST` | `fetch_mstodo.py` (optional; To Do list name, defaults to `Vranov`) |

Netatmo rotates its refresh token on every use, so `fetch_netatmo.py` keeps
the current one Fernet-encrypted in `netatmo_token.enc` on the `data` branch.
The `NETATMO_REFRESH_TOKEN` secret is only a bootstrap/recovery seed.

`fetch_mstodo.py` works the same way: the Microsoft refresh token rotates on
use and is kept Fernet-encrypted in `mstodo_token.enc` on the `data` branch
(`MSTODO_REFRESH_TOKEN` is only the bootstrap seed). This server-side fetch
exists so the **kiosk** (which can't do the browser OAuth/PKCE flow) can show
To Do as plain data-branch JSON. The browser dashboard (`index.html`) still
talks to Microsoft Graph directly and does **not** use this file. Note the
`data` branch is public, so the published task titles are public too; the
`Tasks.Read`-only token cannot modify anything. Azure caveat: refresh tokens
issued to "Single-page application (SPA)" redirect URIs live only 24 h — for a
long-lived (~90 day) seed, register the app also as "Mobile and desktop
applications" and generate `MSTODO_REFRESH_TOKEN` against that.

---

## Data flow

```
GitHub Actions (scheduled / manual)
  └─► scripts/fetch_*.py (growatt, tuya, netatmo, school_menu, calendar)
        └─► external API (Growatt, Tuya IoT, Netatmo, school website, iCal)
        └─► writes data/*.json
        └─► scripts/publish_data.sh pushes the JSON to the "data" branch

GitHub Pages (main) serves index.html
  └─► browser fetches JSON from raw.githubusercontent.com (data branch,
      cache-busted with ?t=Date.now()), fallback to local ./data/ seeds
  └─► browser calls Open-Meteo / Microsoft Graph APIs directly
```

No server-side rendering; no API gateway. All dynamic data either comes from
the pre-built JSON files or is fetched client-side.

---

## GitHub Actions workflows

| Workflow | Schedule | Runner | Key secrets |
|----------|----------|--------|-------------|
| `school_menu.yml` | `0 5 * * 1-5` (05:00 UTC weekdays) + manual | `ubuntu-latest` | — |
| `school_calendar.yml` | `0 5 * * *` (05:00 UTC daily) + manual | `ubuntu-latest` | — |
| `growatt.yml` | `*/15 4-19 * * *` + hourly at night + manual | `ubuntu-latest` | `GROWATT_USER`, `GROWATT_PASS` |
| `tuya.yml` | `*/30 * * * *` (every 30 min) + manual | `ubuntu-latest` | `TUYA_*` |
| `netatmo.yml` | `*/15 * * * *` (every 15 min) + manual | `ubuntu-latest` | `NETATMO_*` |
| `weather.yml` | `*/30 * * * *` (every 30 min) + manual | `ubuntu-latest` | — |
| `calendar.yml` | `0 * * * *` (every hour) + manual | `ubuntu-latest` | `CALENDAR_ICS_URL` |
| `mstodo.yml` | `*/30 * * * *` (every 30 min) + manual | `ubuntu-latest` | `MSTODO_*` |

All workflows follow the same pattern:
1. Checkout repo
2. Set up Python 3.11
3. `pip install <deps>`
4. Run script (injects secrets via `env:`)
5. `bash scripts/publish_data.sh "<commit message>" <file>.json` → `data` branch

`netatmo.yml` and `mstodo.yml` additionally load the stored encrypted refresh
token from the `data` branch before running the script, and use a
`concurrency` group so two runs can't invalidate each other's rotating token.

---

## Python script conventions

- Read credentials from environment variables; exit with code 1 if missing.
- Use `safe_float(val, default=0.0)` helper for untrusted numeric values.
- Always write a JSON file with the shape `{"updated": "<ISO UTC>", "error": null|"string", ...}`.
- Output path is always `Path(__file__).parent.parent / "data" / "<name>.json"`.
- Scripts are standalone — run locally by setting the required env vars.

Local test run example:
```bash
GROWATT_USER=me GROWATT_PASS=secret python scripts/fetch_growatt.py
```

---

## CSS design system (in index.html `<style>`)

| Variable | Value | Usage |
|----------|-------|-------|
| `--ink` | `#0a0a0a` | Primary text |
| `--ink-mid` | `#3a3a3a` | Secondary text |
| `--ink-light` | `#888` | Labels, metadata |
| `--ink-faint` | `#ccc` | Timestamps, dividers |
| `--paper` | `#f5f2ec` | Background |
| `--paper-dark` | `#e8e4db` | Subtle backgrounds |
| `--rule` | `#d0ccc3` | Borders, dividers |

Typography:
- **Body / headings**: `Spectral` (Google Fonts, serif)
- **Data / labels / monospace**: `JetBrains Mono` (Google Fonts)

Layout: mobile-first, single column, `max-width: 480px`, centered.

Section labels use `.section-label` (JetBrains Mono, 0.6 rem, uppercase,
letter-spacing 0.18 em, `--ink-light` colour).

---

## Language and localisation

- **All UI text is in Czech** (`lang="cs"` on `<html>`).
- Day and month names are hardcoded Czech arrays in `updateClock()`.
- Python scripts, comments, error messages, and commit messages are also in Czech.
- Date/time is formatted with Czech locale (`cs-CZ`) using `toLocaleTimeString`.

---

## Adding a new data source

1. **Script**: create `scripts/fetch_<name>.py` — follows the existing pattern
   (env-var credentials, `safe_float`, write `data/<name>.json`).
2. **Workflow**: create `.github/workflows/<name>.yml` — copy an existing one,
   adjust deps, secrets and schedule; the last step publishes via
   `bash scripts/publish_data.sh "<msg>" <name>.json`.
3. **HTML section**: add a `<section>` in `index.html` with a `section-label`
   and a content div (e.g. `id="<name>-content"`).
4. **CSS**: add component-specific styles under the relevant comment block.
5. **JS fetch function**: add `async function fetch<Name>() { ... }` following
   the pattern of `fetchTuya()` or `fetchSchoolMenu()` (use `fetchDataJson`
   and `esc`).
6. **Wire up**: add `fetch<Name>()` to the `Promise.allSettled(...)` inside
   `initAll()`, and commit a seed `data/<name>.json` to `main` as fallback.

---

## JSON data schemas

### `data/growatt.json`
```json
{
  "updated": "2025-02-21T10:00:00+00:00",
  "error": null,
  "plants": [
    {
      "id": "...",
      "name": "...",
      "today_kwh": 5.2,
      "total_kwh": 1234.5,
      "current_w": 800,
      "devices": [
        {
          "sn": "...", "name": "...", "type": "mix", "status": 1,
          "solar_w": 800, "battery_pct": 75, "battery_w": 200,
          "grid_w": 100, "grid_direction": "export",
          "load_w": 500, "today_kwh": 5.2, "total_kwh": 1234.5,
          "today_export_kwh": 1.1, "today_import_kwh": 0.0
        }
      ]
    }
  ],
  "soc": [
    {"t": 1740130200, "v": 52.0}
  ]
}
```
`soc` is a 24 h battery state-of-charge history (unix time, %) for the graph
in the Growatt section. The workflow restores the previous `growatt.json`
from the `data` branch before each run so the script can append to it
(same pattern as the Netatmo token).

### `data/tuya.json`
```json
{
  "updated": "2025-02-21T10:05:00+00:00",
  "error": null,
  "devices": [
    {
      "device_name": "Garáž",
      "online": true,
      "gate_open": false,
      "dp_used": "switch",
      "raw_dps": [{"code": "switch", "value": false}]
    },
    {
      "device_name": "Brána",
      "online": true,
      "gate_open": false,
      "dp_used": "doorcontact_state",
      "raw_dps": [{"code": "doorcontact_state", "value": false}]
    }
  ]
}
```

### `data/school_menu.json`
```json
{
  "updated": "2025-02-21T05:01:00+00:00",
  "error": null,
  "week": "24.2.-28.2.2025",
  "days": {
    "pondeli": {"name": "Pondělí", "meals": ["Polévka: ...", "Oběd 1: ..."]},
    "utery":   {"name": "Úterý",   "meals": [...]},
    "streda":  {"name": "Středa",  "meals": [...]},
    "ctvrtek": {"name": "Čtvrtek", "meals": [...]},
    "patek":   {"name": "Pátek",   "meals": [...]}
  }
}
```

### `data/calendar.json`
```json
{
  "updated": "2025-02-21T10:00:00+00:00",
  "error": null,
  "recurring": [
    {"summary": "Event name", "date": "2025-02-24T15:15:00+00:00", "all_day": false, "location": ""}
  ],
  "single": [
    {"summary": "Event name", "date": "2025-02-25", "all_day": true, "location": "Place"}
  ]
}
```

### `data/school_calendar.json`
```json
{
  "updated": "2025-02-21T05:01:00+00:00",
  "error": null,
  "events": [
    {
      "title": "Event name",
      "date": "2025-02-24",
      "time": "08:30",
      "location": "Place",
      "url": "https://www.skolavranov.cz/..."
    }
  ]
}
```
On scrape failure the script keeps the previously stored `events` and sets
`error`; the frontend then shows them with a stale-data warning.

### `data/weather.json`
```json
{
  "updated": "2025-02-21T10:00:00+00:00",
  "error": null,
  "current": {"temperature_2m": 18.4, "weather_code": 2, "wind_speed_10m": 11.2,
               "relative_humidity_2m": 55, "precipitation": 0},
  "daily": {"time": ["2025-02-21"], "weather_code": [2],
             "temperature_2m_max": [21.2], "temperature_2m_min": [9.8]},
  "hourly": {"time": ["2025-02-21T10:00"], "temperature_2m": [16.8], "precipitation": [0.2]}
}
```
`current`/`daily`/`hourly` mirror the Open-Meteo response (local-time hourly
steps feed the 10:00/14:00 forecast row; `hourly.precipitation` feeds the
"expected rain next 8h/24h" line — the frontend sums it from the current
hour). The browser queries Open-Meteo directly first and uses this file only
as a fallback.

### `data/netatmo.json`
```json
{
  "updated": "2025-02-21T10:00:00+00:00",
  "error": null,
  "modules": [
    {"name": "Obývák", "data": {"Temperature": 22.4, "CO2": 612, "Humidity": 45, "Noise": 38, "Pressure": 1015.2}},
    {"name": "Venku",  "data": {"Temperature": 18.1, "Humidity": 60}}
  ],
  "noise": [
    {"t": 1740130200, "v": 38}
  ]
}
```
`modules[].data` mirrors Netatmo `dashboard_data` keys (labels/format in
`NLABELS`/`fmtN` in index.html). For the rain gauge (NAModule3) the script
additionally computes `sum_rain_8` (rain over the last 8 h, via
`/api/getmeasure` with `type=sum_rain&scale=1hour`) and inserts it after
`sum_rain_1` — Netatmo itself only provides 1 h and 24 h sums. `noise` is a
24 h history (unix time, dB) for the noise graph. The encrypted rotating refresh token lives next to it
as `netatmo_token.enc` (on the `data` branch only).

### `data/mstodo.json`
```json
{
  "updated": "2026-06-15T10:00:00+00:00",
  "error": null,
  "list": "Vranov",
  "tasks": [
    {"title": "Koupit krmení", "due": "2026-06-16", "important": false}
  ]
}
```
Incomplete tasks from the Microsoft To Do list named by `MSTODO_LIST`
(default `Vranov`). `due` is a `YYYY-MM-DD` string or `null`; `important` is
`true` for high-importance tasks. Read only by `kiosk.html` (`fetchMsTodo`,
which sorts dated tasks first and flags overdue ones). The encrypted rotating
refresh token lives next to it as `mstodo_token.enc` (on the `data` branch
only). Only `index.html` shows To Do via the live browser OAuth flow instead.

All JSON files share the envelope: `updated` (ISO 8601 UTC string) and `error`
(null or error description string).

---

## Commit message conventions

Follows Conventional Commits in Czech:

```
feat: přidat novou sekci XYZ
fix: opravit chybu v načítání dat Growatt
chore: update school menu   ← bot commits (only on the data branch)
```

---

## No tests

There is no automated test suite. Validate changes by:
- Running Python scripts locally with the appropriate env vars set.
- Opening `index.html` directly in a browser (some fetch calls need a server
  for relative paths — use `python -m http.server` or VS Code Live Server).
- Checking GitHub Actions run logs for script errors.
