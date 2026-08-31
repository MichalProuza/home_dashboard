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

def fetch():
    now_utc = datetime.now(timezone.utc).isoformat()
    try:
        res = requests.get(URL, timeout=30)
        res.raise_for_status()
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
