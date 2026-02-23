#!/usr/bin/env python3
"""
Stahuje Google Calendar ICS feed a ukládá příští události do data/calendar.json.
Rozděluje na opakující se (RRULE) a jednorázové události.
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
MAX_EACH = int(os.environ.get("CALENDAR_MAX_EACH", "3"))  # max na každou skupinu

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "calendar.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def safe_write_error(msg: str):
    now_utc = datetime.now(timezone.utc).isoformat()
    OUTPUT_PATH.write_text(
        json.dumps(
            {"updated": now_utc, "error": msg, "recurring": [], "single": []},
            ensure_ascii=False, indent=2,
        )
    )
    print(f"ERROR: {msg}")


def to_utc(dt_val) -> datetime:
    """Převede datum nebo datetime na timezone-aware UTC datetime."""
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            try:
                from zoneinfo import ZoneInfo
                dt_val = dt_val.replace(tzinfo=ZoneInfo("Europe/Prague"))
            except Exception:
                dt_val = dt_val.replace(tzinfo=timezone(timedelta(hours=1)))
        return dt_val.astimezone(timezone.utc)
    elif isinstance(dt_val, date):
        return datetime(dt_val.year, dt_val.month, dt_val.day, tzinfo=timezone.utc)
    return dt_val


def is_recurring(component) -> bool:
    """Vrátí True pokud má událost RRULE (je opakující se)."""
    return bool(component.get("RRULE"))


def event_to_dict(component) -> dict:
    dtstart = component.get("DTSTART")
    dt_val = dtstart.dt
    all_day = isinstance(dt_val, date) and not isinstance(dt_val, datetime)
    return {
        "summary": str(component.get("SUMMARY", "")).strip(),
        "date": to_utc(dt_val).isoformat(),
        "all_day": all_day,
        "location": str(component.get("LOCATION", "")).strip(),
    }


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

    # Sestavíme sadu UID opakujících se událostí z raw kalendáře
    recurring_uids = set()
    for component in cal.walk():
        if component.name == "VEVENT" and component.get("RRULE"):
            uid = str(component.get("UID", ""))
            if uid:
                recurring_uids.add(uid)

    try:
        occurrences = recurring_ical_events.of(cal).between(now, cutoff)
    except Exception as e:
        safe_write_error(f"Chyba při zpracování opakujících se událostí: {e}")
        sys.exit(1)

    recurring = []
    single = []

    for component in occurrences:
        if component.name != "VEVENT":
            continue
        if not component.get("SUMMARY") or not component.get("DTSTART"):
            continue

        uid = str(component.get("UID", ""))
        ev = event_to_dict(component)

        if uid in recurring_uids:
            recurring.append(ev)
        else:
            single.append(ev)

    # Seřadit dle data a vzít první MAX_EACH z každé skupiny
    recurring.sort(key=lambda e: e["date"])
    single.sort(key=lambda e: e["date"])
    recurring = recurring[:MAX_EACH]
    single = single[:MAX_EACH]

    output = {
        "updated": now_utc_str,
        "error": None,
        "recurring": recurring,
        "single": single,
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(
        f"✓ Uloženo: {len(recurring)} opakujících se, {len(single)} jednorázových "
        f"→ {OUTPUT_PATH}  ({now_utc_str})"
    )


if __name__ == "__main__":
    fetch()
