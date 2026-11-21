#!/usr/bin/env python3
"""
Runner domácího serveru — spouští scripts/fetch_*.py místo GitHub Actions.

Rozvrh je převzatý z pickWorkflows() ve workers/scheduler/index.js
(Europe/Prague, sloty po 10 min):
  • 5:00–7:59 každých 10 min živé zdroje (LIVE),
  • jinak každé 2 h (sudé hodiny, první slot) živé zdroje + kalendář,
  • v 5:00 navíc jídelníček a plán akcí ZŠ.
Při změně rozvrhu uprav obě místa (kontrola: `run.py plan`).

Každý skript běží jako samostatný proces s HD_MODE=local (konfigurace
z ~/.config/home_dashboard/env, výstup do HD_DATA_DIR, tokeny do HD_STATE_DIR —
viz scripts/hd_common.py). Skripty zapisují JSON atomicky (dočasný soubor +
přejmenování) a se stejnou obálkou updated/error jako v Actions.

Zámky (fcntl.flock v HD_STATE_DIR/locks):
  • daemon.lock — běží nejvýš jeden daemon,
  • <zdroj>.lock — jeden zdroj nikdy neběží dvakrát současně (rotující
    refresh tokeny Netatmo / MS To Do by si navzájem zneplatnily). Když už
    zdroj běží (např. z tlačítka „obnovit" přes server.py), přeskočí se.

Použití:
  run.py daemon                 nepřetržitý běh (launchd KeepAlive)
  run.py once live|all|<zdroj>… spustí zdroje hned a skončí (tlačítko „obnovit")
  run.py plan [--at ISO]        vypíše, co by se v daném slotu spustilo
  run.py plan --day YYYY-MM-DD  vypíše celodenní rozvrh (porovnání s Workerem)
"""

import argparse
import fcntl
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    PRAGUE = ZoneInfo("Europe/Prague")
except Exception as e:  # bez tzdata by rozvrh tiše jel v UTC — raději spadnout
    print(f"ERROR: Časová zóna Europe/Prague není dostupná ({e}); pip install tzdata")
    sys.exit(1)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
# Runner sám secrets nenačítá (HD_MODE=local dostanou až fetch skripty), jen
# z hd_common bere lokální adresáře a atomický zápis.
import hd_common  # noqa: E402

DATA_DIR = hd_common.local_data_dir()
STATE_DIR = hd_common.local_state_dir()
LOCK_DIR = STATE_DIR / "locks"
STATUS_DIR = STATE_DIR / "status"

SLOT_S = 600                 # 10min sloty jako cron Workeru (*/10 * * * *)
SCRIPT_TIMEOUT_S = 300       # Actions job by tak dlouho taky neběžel
EXIT_TRANSIENT = 75          # fetch_weather.py: přechodný výpadek Open-Meteo


class Source:
    def __init__(self, name, script, outputs, max_age_h):
        self.name = name
        self.script = script
        self.outputs = outputs
        # Po startu daemonu se dohoní zdroje starší než tohle (výpadek proudu…)
        self.max_age_h = max_age_h


# Názvy = workflowy bez .yml (stejně jako ve Workeru)
SOURCES = {s.name: s for s in [
    Source("netatmo",         "fetch_netatmo.py",         ["netatmo.json"],         2.2),
    Source("tuya",            "fetch_tuya.py",            ["tuya.json"],            2.2),
    Source("growatt",         "fetch_growatt.py",         ["growatt.json"],         2.2),
    Source("weather",         "fetch_weather.py",         ["weather.json"],         2.2),
    Source("mstodo",          "fetch_mstodo.py",          ["mstodo.json"],          2.2),
    Source("calendar",        "fetch_calendar.py",        ["calendar.json"],        2.2),
    Source("school_menu",     "fetch_school_menu.py",     ["school_menu.json"],     24.5),
    Source("school_calendar", "fetch_school_calendar.py", ["school_calendar.json"], 24.5),
]}

# ── Rozvrh (kopie pickWorkflows() z workers/scheduler/index.js) ──────────────
LIVE = ["netatmo", "tuya", "growatt", "weather", "mstodo"]
EVERY_2H = LIVE + ["calendar"]
DAILY_5AM = ["school_menu", "school_calendar"]


def pick_sources(when: datetime) -> list:
    """Které zdroje spustit v 10min slotu, do kterého spadá `when`."""
    local = when.astimezone(PRAGUE)
    h, m = local.hour, local.minute
    first_slot = m < 10
    if 5 <= h < 8:
        return EVERY_2H + DAILY_5AM if (h == 5 and first_slot) else list(LIVE)
    if h % 2 == 0 and first_slot:
        return list(EVERY_2H)
    return []


log = logging.getLogger("runner")


def setup_logging(log_file):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000,
                                                       backupCount=3, encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    log.addHandler(handler)
    log.setLevel(logging.INFO)


# ── Zámky a stav ─────────────────────────────────────────────────────────────

def try_lock(name: str):
    """Neblokující exkluzivní zámek; vrací otevřený soubor (drží zámek), nebo None."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    f = open(LOCK_DIR / f"{name}.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def write_status(name: str, status: dict):
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    hd_common.write_json(STATUS_DIR / f"{name}.json", status)


def check_envelope(path: Path):
    """Ověří, že výstup je JSON s obálkou updated/error; vrací (updated, error) nebo vyhodí."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or "updated" not in doc or "error" not in doc:
        raise ValueError("chybí obálka updated/error")
    return doc["updated"], doc["error"]


def output_age_h(src: Source):
    """Stáří nejstaršího výstupu zdroje v hodinách (None = chybí)."""
    ages = []
    for out in src.outputs:
        p = DATA_DIR / out
        if not p.exists():
            return None
        ages.append((time.time() - p.stat().st_mtime) / 3600)
    return max(ages)


# ── Spouštění skriptů ────────────────────────────────────────────────────────

def run_source(name: str) -> int:
    src = SOURCES[name]
    lock = try_lock(name)
    if lock is None:
        log.info("%s: už běží, přeskočeno", name)
        return 0
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    env = dict(os.environ, HD_MODE="local", HD_DATA_DIR=str(DATA_DIR),
               HD_STATE_DIR=str(STATE_DIR), PYTHONUNBUFFERED="1")
    try:
        try:
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / src.script)],
                cwd=str(SCRIPTS_DIR.parent), env=env, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=SCRIPT_TIMEOUT_S,
            )
            rc, output = proc.returncode, (proc.stdout + proc.stderr).strip()
        except subprocess.TimeoutExpired as e:
            rc = -1
            output = f"timeout po {SCRIPT_TIMEOUT_S} s\n{(e.stdout or '')}{(e.stderr or '')}"
        duration = round(time.monotonic() - t0, 1)

        envelope_error = None
        for out in src.outputs:
            try:
                _, envelope_error = check_envelope(DATA_DIR / out)
            except Exception as e:  # chybějící / rozbitý soubor
                envelope_error = f"{out}: {e}"

        tail = "\n".join(output.splitlines()[-15:])
        if rc == 0:
            log.info("%s: OK za %.1f s%s", name, duration,
                     f" (error v JSON: {envelope_error})" if envelope_error else "")
        elif rc == EXIT_TRANSIENT:
            # Jako weather.yml: jen varování, starý JSON zůstává
            log.warning("%s: přechodně nedostupné, data se tentokrát neaktualizují", name)
        else:
            log.error("%s: selhalo (kód %s) za %.1f s\n%s", name, rc, duration, tail)

        write_status(name, {
            "started": started.isoformat(),
            "duration_s": duration,
            "rc": rc,
            "json_error": envelope_error,
            "log_tail": tail if rc not in (0,) else None,
        })
        return rc
    finally:
        lock.close()


def run_sources(names: list) -> dict:
    names = list(dict.fromkeys(names))  # bez duplicit, pořadí zachovat
    if not names:
        return {}
    log.info("spouštím: %s", ", ".join(names))
    # Paralelně jako workflowy ve Workeru; každý zdroj má vlastní zámek
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        results = dict(zip(names, pool.map(run_source, names)))
    failed = [n for n, rc in results.items() if rc not in (0, EXIT_TRANSIENT)]
    log.info("hotovo %d/%d%s", len(names) - len(failed), len(names),
             f", chyby: {', '.join(failed)}" if failed else "")
    return results


def resolve_names(args: list) -> list:
    names = []
    for a in args:
        if a == "live":
            names += LIVE
        elif a == "all":
            names += list(SOURCES)
        elif a in SOURCES:
            names.append(a)
        else:
            raise SystemExit(f"neznámý zdroj: {a} (možnosti: live, all, {', '.join(SOURCES)})")
    return names


# ── Daemon ───────────────────────────────────────────────────────────────────

_stop = threading.Event()


def daemon():
    lock = try_lock("daemon")
    if lock is None:
        log.error("daemon už běží (zámek %s)", LOCK_DIR / "daemon.lock")
        return 1
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: _stop.set())

    log.info("daemon start (data: %s, state: %s)", DATA_DIR, STATE_DIR)
    # Po startu (restart Macu, výpadek proudu) dohnat zastaralé zdroje + aktuální slot
    slot = int(time.time() // SLOT_S)
    stale = [n for n, s in SOURCES.items()
             if (age := output_age_h(s)) is None or age > s.max_age_h]
    if stale:
        log.info("dohánění zastaralých zdrojů: %s", ", ".join(stale))
    run_sources(stale + pick_sources(datetime.fromtimestamp(slot * SLOT_S, timezone.utc)))
    last_slot = slot

    while not _stop.is_set():
        # Krátké spánky: po uspání / změně hodin se navazuje podle reálného času.
        # Zmeškané sloty se nedohánějí, spustí se jen ten aktuální (jako cron).
        next_start = (last_slot + 1) * SLOT_S
        _stop.wait(min(60, max(1, next_start - time.time() + 2)))
        slot = int(time.time() // SLOT_S)
        if slot != last_slot and not _stop.is_set():
            last_slot = slot
            run_sources(pick_sources(datetime.fromtimestamp(slot * SLOT_S, timezone.utc)))
    log.info("daemon konec")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_plan(at, day):
    if day:
        # Krokovat v UTC (jako cron Workeru), vypisovat pražský čas — v den
        # přechodu letního času má den 23 nebo 25 h
        d = datetime.fromisoformat(day).date()
        t = datetime(d.year, d.month, d.day, tzinfo=PRAGUE).astimezone(timezone.utc)
        end = (datetime(d.year, d.month, d.day, tzinfo=PRAGUE) + timedelta(days=1)).astimezone(timezone.utc)
        while t < end:
            picked = pick_sources(t)
            if picked:
                print(f"{t.astimezone(PRAGUE):%H:%M %Z}  {' '.join(picked)}")
            t += timedelta(minutes=10)
        return 0
    when = datetime.fromisoformat(at) if at else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=PRAGUE)
    print(" ".join(pick_sources(when)) or "(nic)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--log-file", help="log s rotací (jinak stderr)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daemon")
    p_once = sub.add_parser("once")
    p_once.add_argument("sources", nargs="+")
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("--at", help="ISO čas (bez zóny = Europe/Prague)")
    p_plan.add_argument("--day", help="YYYY-MM-DD — celodenní rozvrh")
    args = ap.parse_args()

    if args.cmd == "plan":
        return cmd_plan(args.at, args.day)
    setup_logging(args.log_file)
    problem = hd_common.check_env_file()
    if problem:
        # Bez konfigurace by všechny skripty jen padaly — ohlásit hned a srozumitelně
        log.error(problem)
        return 1
    hd_common.ensure_local_dirs()
    if args.cmd == "daemon":
        return daemon()
    results = run_sources(resolve_names(args.sources))
    return 0 if all(rc in (0, EXIT_TRANSIENT) for rc in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
