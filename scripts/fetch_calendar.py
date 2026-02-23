#!/usr/bin/env python3
"""
Stahuje Google Calendar ICS feed a ukládá příští události do data/calendar.json.
Správně zpracovává opakující se události (RRULE) pomocí balíčku recurring-ical-events.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests není nainstalován. Spusť: pip install requests")
    sys.exit(1)

try:
    import icalendar
    import recurring_ical_events
except ImportError:
    print("ERROR: icalendar nebo recurring-ical-events není nainstalován.")
    print("Spusť: pip install icalendar recurring-ical-events")
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


def to_utc(dt_val) -> datetime:
    """Převede datum nebo datetime na timezone-aware UTC datetime."""
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            # Lokální čas bez timezone — předpokládáme Europe/Prague
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo("Europe/Prague")
                dt_val = dt_val.replace(tzinfo=tz)
            except Exception:
                dt_val = dt_val.replace(tzinfo=timezone(timedelta(hours=1)))
        return dt_val.astimezone(timezone.utc)
    elif isinstance(dt_val, date):
        # Celodenní událost — representujeme jako půlnoc UTC
        return datetime(dt_val.year, dt_val.month, dt_val.day, tzinfo=timezone.utc)
    return dt_val


def fetch():
    if not ICS_URL:
        safe_write_error("Chybí CALENDAR_ICS_URL v prostředí / GitHub Secrets.")
        sys.exit(1)

    now_utc_str = datetime.now(timezone.utc).isoformat()

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

    try:
        cal = icalendar.Calendar.from_ical(text)
    except Exception as e:
        safe_write_error(f"Nelze parsovat ICS: {e}")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=DAYS_AHEAD)

    try:
        occurrences = recurring_ical_events.of(cal).between(now, cutoff)
    except Exception as e:
        safe_write_error(f"Chyba při zpracování opakujících se událostí: {e}")
        sys.exit(1)

    events = []
    for component in occurrences:
        if component.name != "VEVENT":
            continue

        summary = str(component.get("SUMMARY", "")).strip()
        dtstart = component.get("DTSTART")
        if not summary or not dtstart:
            continue

        dt_val = dtstart.dt
        all_day = isinstance(dt_val, date) and not isinstance(dt_val, datetime)
        dt_utc = to_utc(dt_val)

        events.append({
            "summary": summary,
            "dt": dt_utc,
            "all_day": all_day,
            "location": str(component.get("LOCATION", "")).strip(),
        })

    events.sort(key=lambda e: e["dt"])
    events = events[:MAX_EVENTS]

    output = {
        "updated": now_utc_str,
        "error": None,
        "events": [
            {
                "summary": e["summary"],
                "date": e["dt"].isoformat(),
                "all_day": e["all_day"],
                "location": e["location"],
            }
            for e in events
        ],
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✓ Nalezeno a uloženo {len(events)} nadcházejících událostí → {OUTPUT_PATH}  ({now_utc_str})")


if __name__ == "__main__":
    fetch()
