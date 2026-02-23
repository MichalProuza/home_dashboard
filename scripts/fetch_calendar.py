#!/usr/bin/env python3
"""
Stahuje Google Calendar ICS feed a ukládá příští události do data/calendar.json.
Spouští se přes GitHub Actions každou hodinu.

Nevyžaduje žádné přihlašovací údaje — používá veřejný ICS odkaz z Google Kalendáře.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests není nainstalován. Spusť: pip install requests")
    sys.exit(1)

# ── Konfigurace ───────────────────────────────────────────────────────────────
ICS_URL = os.environ.get("CALENDAR_ICS_URL", "")
DAYS_AHEAD = int(os.environ.get("CALENDAR_DAYS_AHEAD", "30"))
MAX_EVENTS = int(os.environ.get("CALENDAR_MAX_EVENTS", "10"))

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "calendar.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def safe_write_error(msg: str):
    now_utc = datetime.now(timezone.utc).isoformat()
    OUTPUT_PATH.write_text(
        json.dumps({"updated": now_utc, "error": msg, "events": []}, ensure_ascii=False, indent=2)
    )
    print(f"ERROR: {msg}")


def unfold(text: str) -> str:
    """Rozbalí ICS line-folding (CRLF + mezera/tab = pokračování řádku)."""
    return re.sub(r"\r\n[ \t]|\n[ \t]", "", text)


def parse_dt(value: str):
    """
    Parsuje ICS datum/čas. Vrátí (datetime, all_day).
    Podporuje:
      - YYYYMMDD            → celodenní
      - YYYYMMDDTHHmmss     → lokální čas (přidáme UTC offset +01:00 / +02:00 dle DST)
      - YYYYMMDDTHHmmssZ    → UTC
    """
    value = value.strip()
    if len(value) == 8:
        # celodenní událost
        y, mo, d = int(value[:4]), int(value[4:6]), int(value[6:8])
        return datetime(y, mo, d, tzinfo=timezone.utc), True

    y, mo, d = int(value[:4]), int(value[4:6]), int(value[6:8])
    hh, mm, ss = int(value[9:11]), int(value[11:13]), int(value[13:15]) if len(value) >= 15 else 0

    if value.endswith("Z"):
        return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc), False

    # Lokální čas (předpokládáme Europe/Prague — UTC+1 zima, UTC+2 léto)
    # Jednoduché DST pravidlo: poslední neděle v březnu → poslední neděle v říjnu
    naive = datetime(y, mo, d, hh, mm, ss)
    offset = timedelta(hours=2) if _is_cest(naive) else timedelta(hours=1)
    return datetime(y, mo, d, hh, mm, ss, tzinfo=timezone(offset)), False


def _is_cest(dt: datetime) -> bool:
    """Vrátí True pokud je datum v letním čase (CEST = UTC+2)."""
    # Poslední neděle v březnu
    last_sun_march = max(
        datetime(dt.year, 3, d)
        for d in range(25, 32)
        if datetime(dt.year, 3, d).weekday() == 6
    )
    # Poslední neděle v říjnu
    last_sun_october = max(
        datetime(dt.year, 10, d)
        for d in range(25, 32)
        if datetime(dt.year, 10, d).weekday() == 6
    )
    return last_sun_march <= dt.replace(tzinfo=None) < last_sun_october


def parse_ics(text: str):
    """Parsuje ICS text a vrátí seznam událostí jako dict."""
    text = unfold(text)
    events = []

    for block in text.split("BEGIN:VEVENT")[1:]:
        def get(key):
            m = re.search(rf"^{key}[^:\r\n]*:([^\r\n]+)", block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        summary = get("SUMMARY")
        dtstart_raw = get("DTSTART")
        if not summary or not dtstart_raw:
            continue

        try:
            dt, all_day = parse_dt(dtstart_raw)
        except Exception:
            continue

        events.append({
            "summary": summary,
            "dt": dt,
            "all_day": all_day,
            "location": get("LOCATION"),
            "description": get("DESCRIPTION")[:200] if get("DESCRIPTION") else "",
        })

    return events


def fetch():
    if not ICS_URL:
        safe_write_error("Chybí CALENDAR_ICS_URL v prostředí / GitHub Secrets.")
        sys.exit(1)

    now_utc = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(ICS_URL, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        safe_write_error(f"Nelze stáhnout ICS: {e}")
        sys.exit(1)

    text = resp.text
    if "BEGIN:VCALENDAR" not in text:
        safe_write_error(f"Odpověď není ICS (začátek: {text[:100]!r})")
        sys.exit(1)

    all_events = parse_ics(text)
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=DAYS_AHEAD)

    upcoming = sorted(
        [e for e in all_events if now <= e["dt"] <= cutoff],
        key=lambda e: e["dt"],
    )[:MAX_EVENTS]

    output = {
        "updated": now_utc,
        "error": None,
        "events": [
            {
                "summary": e["summary"],
                "date": e["dt"].isoformat(),
                "all_day": e["all_day"],
                "location": e["location"],
            }
            for e in upcoming
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✓ Nalezeno {len(all_events)} událostí celkem, uloženo {len(upcoming)} nadcházejících → {OUTPUT_PATH}  ({now_utc})")


if __name__ == "__main__":
    fetch()
