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

# Mapování českých názvů měsíců na čísla
MONTHS_CS = {
    "ledna": 1, "února": 2, "března": 3, "dubna": 4,
    "května": 5, "června": 6, "července": 7, "srpna": 8,
    "září": 9, "října": 10, "listopadu": 11, "prosince": 12,
}


def parse_date(kdy_text: str) -> str | None:
    """
    Parsuje datum z textu tvaru:
      "Kdy: sobota 7. března 2026 začátek od 9:00, délka 2:30"
      "Kdy: pondělí 2. – středa 4. března 2026"
    Vrací ISO datum (YYYY-MM-DD) začátku události nebo None.
    """
    # Hledáme vzor: číslo den + tečka + název měsíce + rok
    m = re.search(r"(\d{1,2})\.\s+(\w+)\s+(\d{4})", kdy_text)
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS_CS.get(m.group(2).lower())
    year = int(m.group(3))
    if not month:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_time(kdy_text: str) -> str | None:
    """Extrahuje čas začátku ve formátu HH:MM nebo None."""
    m = re.search(r"začátek od (\d{1,2}):(\d{2})", kdy_text)
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

        # Události jsou jako <a href="..."> obsahující <h3> nadpis
        # a text s "Kdy:" a "Kde:" informacemi
        for link in soup.find_all("a", href=re.compile(r"/zakladni-skola/plan-akci-zs/.+\.html")):
            h3 = link.find("h3")
            if not h3:
                continue

            title = h3.get_text(" ", strip=True)
            full_text = link.get_text(" ", strip=True)

            # Najdi blok "Kdy: ..."
            kdy_match = re.search(r"Kdy:\s*(.+?)(?:Kde:|$)", full_text, re.DOTALL)
            kdy_text = kdy_match.group(1).strip() if kdy_match else ""

            # Najdi blok "Kde: ..."
            kde_match = re.search(r"Kde:\s*(.+?)(?:\n|$)", full_text)
            kde_text = kde_match.group(1).strip() if kde_match else ""

            event_date = parse_date(kdy_text)
            if not event_date:
                continue

            # Přeskoč minulé události
            if event_date < today.isoformat():
                continue

            event_time = parse_time(kdy_text)

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
