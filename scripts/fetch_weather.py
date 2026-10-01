#!/usr/bin/env python3
"""
Stahuje předpověď počasí z Open-Meteo a ukládá ji do data/weather.json
Spouští se přes GitHub Actions každých 30 minut.

Slouží jako server-side záloha pro dashboard — Open-Meteo blokuje/limituje
některé IP rozsahy (viz open-meteo/open-meteo#1651), takže přímý dotaz
z prohlížeče nemusí projít.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests není nainstalován. Spusť: pip install requests")
    sys.exit(1)

# Vranov u Brna (stejné souřadnice jako v index.html)
LAT, LON = 49.043, 16.558

URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m,precipitation"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min"
    "&hourly=temperature_2m,precipitation"
    "&timezone=Europe%2FPrague&forecast_days=5"
)

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "weather.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

RETRIES = 5          # Open-Meteo občas vrací přechodné 5xx/429
BACKOFF_S = 10       # čekání mezi pokusy: 10, 20, 30, 40 s


def get_with_retry():
    last_exc = None
    for attempt in range(1, RETRIES + 1):
        try:
            res = requests.get(URL, timeout=30)
            res.raise_for_status()
            return res
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if isinstance(e, requests.HTTPError) and status not in (429, 500, 502, 503, 504):
                raise  # trvalá chyba (4xx) — opakování nepomůže
            last_exc = e
            if attempt < RETRIES:
                wait = BACKOFF_S * attempt
                print(f"Pokus {attempt}/{RETRIES} selhal ({e}), čekám {wait} s…")
                time.sleep(wait)
    raise last_exc


def fetch():
    now_utc = datetime.now(timezone.utc).isoformat()
    try:
        res = get_with_retry()
        body = res.json()
        if "current" not in body or "daily" not in body:
            raise ValueError(f"neúplná odpověď (klíče: {sorted(body.keys())})")
        output = {
            "updated": now_utc,
            "error": None,
            "current": body["current"],
            "daily": body["daily"],
            "hourly": body.get("hourly"),
        }
    except Exception as e:
        print(f"ERROR: Stažení počasí selhalo: {e}")
        sys.exit(1)

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Uloženo do {OUTPUT_PATH}  ({now_utc})")

if __name__ == "__main__":
    fetch()
