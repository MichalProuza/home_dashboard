#!/usr/bin/env python3
"""
Stahuje jídelníček MŠ Vranov ze skolavranov.cz a ukládá do data/school_menu.json.
Spouští se přes GitHub Actions každý pracovní den.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Spusť: pip install requests beautifulsoup4")
    sys.exit(1)

URL = "https://www.skolavranov.cz/skolni-jidelna/jidelnicek/"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "school_menu.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Mapování názvů dnů (jak se objevují v HTML) na klíče
DAY_NAMES = {
    "PONDĚLÍ": "pondeli",
    "ÚTERÝ":   "utery",
    "STŘEDA":  "streda",
    "ČTVRTEK": "ctvrtek",
    "PÁTEK":   "patek",
}

DAY_LABELS = {
    "pondeli": "Pondělí",
    "utery":   "Úterý",
    "streda":  "Středa",
    "ctvrtek": "Čtvrtek",
    "patek":   "Pátek",
}


def fetch():
    now_utc = datetime.now(timezone.utc).isoformat()

    try:
        print(f"INFO: Stahuju {URL} …")
        resp = requests.get(URL, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # MŠ jídelníček je v záložce pane_220_1
        pane = soup.find(id="pane_220_1")
        if not pane:
            raise RuntimeError("Sekce MŠ nenalezena (pane_220_1)")

        content = pane.find(class_="content")
        if not content:
            raise RuntimeError("Obsah jídelníčku nenalezen (.content)")

        # Datum (týden) – druhý <h2> v content obsahuje datum
        week_str = ""
        for h2 in content.find_all("h2"):
            text = h2.get_text(" ", strip=True)
            if re.search(r"\d{1,2}\.\d{1,2}", text):
                week_str = re.sub(r"\s+", " ", text).strip()
                break

        # Parsování dnů a jídel
        days = {}
        current_day = None

        for el in content.children:
            if not hasattr(el, "name"):
                continue

            if el.name == "p":
                bold = el.find("b")
                if bold:
                    text = bold.get_text(strip=True).rstrip(":").strip()
                    if text in DAY_NAMES:
                        current_day = DAY_NAMES[text]
                        days[current_day] = {
                            "name":  DAY_LABELS[current_day],
                            "meals": [],
                        }

            elif el.name == "ul" and current_day:
                for li in el.find_all("li"):
                    meal = li.get_text(" ", strip=True)
                    meal = re.sub(r"\s+", " ", meal).strip()
                    if meal:
                        days[current_day]["meals"].append(meal)

        if not days:
            raise RuntimeError("Žádné dny nenalezeny – struktura stránky se možná změnila")

        output = {
            "updated": now_utc,
            "error":   None,
            "week":    week_str,
            "days":    days,
        }
        print(f"✓ Načten jídelníček: {week_str}")
        for key, day in days.items():
            print(f"  {day['name']}: {len(day['meals'])} položek")

    except Exception as e:
        print(f"ERROR: {e}")
        output = {
            "updated": now_utc,
            "error":   str(e),
            "week":    "",
            "days":    {},
        }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✓ Uloženo do {OUTPUT_PATH}")


if __name__ == "__main__":
    fetch()
