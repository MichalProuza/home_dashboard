#!/usr/bin/env python3
"""Zkontroluje data/*.json — obálku, ISO datum a klíče, které frontendy čtou.

Neexistuje tu žádný test suite, takže tohle je jediná mechanická kontrola, že
skript vyrobil něco, co dashboard umí zobrazit.

Dva režimy, protože soubory v data/ na mainu a na větvi data mají jiný účel:

  bez přepínače  „seed" režim — data/ v mainu jsou záložní placeholdery a mají
                 legitimně {"updated": null} a prázdné payloady. Hlídá se
                 struktura, ne obsah.
  --live         strict režim — pro JSON, který právě vyrobil fetch skript.
                 Vyžaduje reálné ISO `updated` a neprázdná data.

Použití:
  python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py
  python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py --live data/mysrc.json

Exit 0 = v pořádku (varování nevadí), 1 = chyby.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DATA = REPO / "data"

# Klíče, které frontend u daného zdroje skutečně čte. Chybí-li, sekce se
# rozbije nebo zůstane prázdná. Nový zdroj si sem dopiš.
REQUIRED = {
    "growatt.json":         ["plants"],
    "tuya.json":            ["devices"],
    "netatmo.json":         ["modules"],
    "weather.json":         ["current", "daily", "hourly"],
    "school_menu.json":     ["week", "days"],
    "school_calendar.json": ["events"],
    "calendar.json":        ["recurring", "single"],
    "mstodo.json":          ["list", "tasks"],
}

# Jak často má který zdroj přitékat (hodiny) — kontroluje se jen v --live.
MAX_AGE_H = {
    "growatt.json": 3, "tuya.json": 3, "netatmo.json": 3, "weather.json": 3,
    "calendar.json": 6, "mstodo.json": 3,
    "school_menu.json": 72, "school_calendar.json": 48,
}

errors: list = []
warnings: list = []


def check(path: Path, live: bool) -> None:
    name = path.name
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        errors.append(f"{name}: nelze přečíst ({e})")
        return
    except json.JSONDecodeError as e:
        errors.append(f"{name}: nevalidní JSON — {e}")
        return

    if not isinstance(doc, dict):
        errors.append(f"{name}: kořen musí být objekt, je {type(doc).__name__}")
        return

    fail = errors.append
    soft = warnings.append

    # ── updated ──────────────────────────────────────────────────────────────
    if "updated" not in doc:
        fail(f"{name}: chybí povinné pole 'updated'")
    elif doc["updated"] is None:
        (fail if live else soft)(
            f"{name}: 'updated' je null"
            + (" — živý výstup musí nést čas běhu" if live
               else " (seed placeholder — na mainu v pořádku)")
        )
    else:
        iso = doc["updated"]
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                soft(f"{name}: 'updated' bez časové zóny ({iso}) — má být UTC")
                dt = dt.replace(tzinfo=timezone.utc)
            if live:
                age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                limit = MAX_AGE_H.get(name)
                if limit and age_h > limit:
                    soft(f"{name}: 'updated' je {age_h:.0f} h staré (limit {limit} h) "
                         "— zkontroluj, jestli workflow běží")
        except (ValueError, TypeError):
            fail(f"{name}: 'updated' není ISO 8601 datum: {iso!r}")

    # ── error ────────────────────────────────────────────────────────────────
    if "error" not in doc:
        fail(f"{name}: chybí povinné pole 'error' (null nebo popis chyby)")
    elif not (doc["error"] is None or isinstance(doc["error"], str)):
        fail(f"{name}: 'error' musí být null nebo string, je {type(doc['error']).__name__}")
    elif doc["error"]:
        soft(f"{name}: nese chybu: {doc['error']}")

    # ── Klíče podle zdroje ───────────────────────────────────────────────────
    known = name in REQUIRED
    for key in REQUIRED.get(name, []):
        if key not in doc:
            fail(f"{name}: chybí '{key}', na kterém frontend závisí")
        elif doc[key] in ([], {}, None, "") and not doc.get("error"):
            (fail if live else soft)(
                f"{name}: '{key}' je prázdné, ale 'error' je null"
                + (" — buď naplň data, nebo popiš chybu" if live
                   else " (u seedu obvyklé)")
            )

    if not known:
        soft(f"{name}: neznámý zdroj — dopiš jeho povinné klíče do REQUIRED "
             "v tomhle skriptu, ať je nová sekce taky pod kontrolou")


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--live"]
    live = "--live" in sys.argv[1:]

    if args:
        paths = [Path(a) for a in args]
    else:
        if not DATA.is_dir():
            print(f"CHYBA: {DATA} neexistuje", file=sys.stderr)
            return 1
        paths = sorted(DATA.glob("*.json"))

    if not paths:
        print("Žádné JSON soubory ke kontrole.")
        return 0

    for p in paths:
        check(p, live)

    mode = "live (strict)" if live else "seed"
    print(f"Zkontrolováno {len(paths)} souborů, režim: {mode}.\n")
    if warnings:
        print("Varování:")
        for w in warnings:
            print(f"  ⚠ {w}")
        print()
    if errors:
        print("Chyby:")
        for e in errors:
            print(f"  ✗ {e}")
        print("\nSchéma jednotlivých zdrojů je v CLAUDE.md (JSON data schemas).")
        return 1

    print("✓ Obálka i povinné klíče v pořádku.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
