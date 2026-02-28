#!/usr/bin/env python3
"""
Stahuje plán akcí ZŠ Vranov ze skolavranov.cz a ukládá 5 nejbližších
událostí do data/school_calendar.json.
Spouští se přes GitHub Actions každý den.
"""

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Spusť: pip install requests beautifulsoup4")
    sys.exit(1)

URL = "https://www.skolavranov.cz/zakladni-skola/plan-akci-zs/"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "school_calendar.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

MAX_EVENTS = 5


def parse_date(action_date_text: str) -> str | None:
    """
    Parsuje datum z textu tvaru:
      "6. 3. 2026 začátek od 08:00"
      "13. 3. 2026 začátek od 07:45, délka 285 minut"
    Vrací ISO datum (YYYY-MM-DD) nebo None.
    """
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", action_date_text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def parse_time(action_date_text: str) -> str | None:
    """Extrahuje čas začátku ve formátu HH:MM nebo None."""
    m = re.search(r"začátek od (\d{1,2}):(\d{2})", action_date_text)
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def fetch():
    now_utc = datetime.now(timezone.utc).isoformat()
    today = date.today()

    try:
        print(f"INFO: Stahuju {URL} …")
        resp = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        events = []

        # Každá událost je div.readable_item obsahující a.event-link
        for item in soup.find_all("div", class_="readable_item"):
            link = item.find("a", class_="event-link")
            if not link:
                continue

            # Název
            h3 = link.find("h3", class_="event-name")
            if not h3:
                continue
            title = h3.get_text(strip=True)

            # Datum a čas
            action_date_div = link.find("div", class_="action_date")
            if not action_date_div:
                continue
            action_date_text = action_date_div.get_text(" ", strip=True)

            event_date = parse_date(action_date_text)
            if not event_date:
                continue

            # Přeskoč minulé události
            if event_date < today.isoformat():
                continue

            event_time = parse_time(action_date_text)

            # Místo konání
            venues_div = link.find("div", class_="venues")
            kde_text = venues_div.get_text(strip=True) if venues_div else ""

            # URL detailu
            href = link.get("href", "")
            if href.startswith("/"):
                href = "https://www.skolavranov.cz" + href

            events.append({
                "title": title,
                "date": event_date,
                "time": event_time,
                "location": kde_text,
                "url": href,
            })

        # Seřaď podle data a vezmi 5 nejbližších
        events.sort(key=lambda e: e["date"])
        events = events[:MAX_EVENTS]

        if not events:
            print("WARN: Žádné nadcházející události nenalezeny")

        output = {
            "updated": now_utc,
            "error": None,
            "events": events,
        }
        print(f"✓ Načteno {len(events)} událostí ZŠ:")
        for ev in events:
            t = f" {ev['time']}" if ev["time"] else ""
            print(f"  {ev['date']}{t} – {ev['title']}")

    except Exception as e:
        print(f"ERROR: {e}")
        output = {
            "updated": now_utc,
            "error": str(e),
            "events": [],
        }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✓ Uloženo do {OUTPUT_PATH}")


if __name__ == "__main__":
    fetch()
