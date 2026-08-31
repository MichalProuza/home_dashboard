#!/usr/bin/env python3
"""
Stahuje data Netatmo stanice (getstationsdata + 24h historie hluku)
a ukládá je do data/netatmo.json. Spouští se přes GitHub Actions.

Netatmo refresh tokeny při použití rotují (starý přestane platit), proto se
aktuální refresh token udržuje zašifrovaný v data/netatmo_token.enc, který
workflow publikuje do větve "data" a před dalším během zase načte.

Potřebné GitHub Secrets:
  NETATMO_CLIENT_ID     – Client ID aplikace z https://dev.netatmo.com
  NETATMO_CLIENT_SECRET – Client secret téže aplikace
  NETATMO_REFRESH_TOKEN – Počáteční refresh token; vygeneruj na
                          dev.netatmo.com → My apps → aplikace → Token generator
                          (scope read_station). Použije se jen pokud
                          data/netatmo_token.enc neexistuje nebo přestal platit.
  NETATMO_TOKEN_KEY     – Libovolné dlouhé náhodné heslo; šifruje uložený
                          refresh token (ten je v repu veřejně viditelný).
"""

import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests není nainstalován. Spusť: pip install requests")
    sys.exit(1)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:
    print("ERROR: cryptography není nainstalován. Spusť: pip install cryptography")
    sys.exit(1)

# ── Přihlašovací údaje z GitHub Secrets ──────────────────────────────────────
CLIENT_ID     = os.environ.get("NETATMO_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NETATMO_CLIENT_SECRET", "")
SEED_REFRESH  = os.environ.get("NETATMO_REFRESH_TOKEN", "")
TOKEN_KEY     = os.environ.get("NETATMO_TOKEN_KEY", "")

if not CLIENT_ID or not CLIENT_SECRET or not TOKEN_KEY:
    print("ERROR: Chybí NETATMO_CLIENT_ID, NETATMO_CLIENT_SECRET nebo NETATMO_TOKEN_KEY.")
    sys.exit(1)

DATA_DIR    = Path(__file__).parent.parent / "data"
OUTPUT_PATH = DATA_DIR / "netatmo.json"
TOKEN_PATH  = DATA_DIR / "netatmo_token.enc"
DATA_DIR.mkdir(parents=True, exist_ok=True)

API = "https://api.netatmo.com"
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(TOKEN_KEY.encode()).digest()))


# ── Práce s uloženým refresh tokenem ─────────────────────────────────────────

def load_refresh_candidates() -> list:
    """Kandidáti na refresh token: nejdřív uložený rotovaný, pak seed ze secrets."""
    candidates = []
    if TOKEN_PATH.exists():
        raw = TOKEN_PATH.read_bytes().strip()
        if raw:
            try:
                candidates.append(FERNET.decrypt(raw).decode())
            except InvalidToken:
                print("WARN: netatmo_token.enc nelze dešifrovat (změnil se NETATMO_TOKEN_KEY?)")
        else:
            # Prázdný soubor (selhalo načtení z větve data) – smazat, aby
            # publish_data.sh nepřepsal platný token v repu prázdným obsahem
            TOKEN_PATH.unlink()
    if SEED_REFRESH and SEED_REFRESH not in candidates:
        candidates.append(SEED_REFRESH)
    return candidates


def save_refresh_token(token: str):
    TOKEN_PATH.write_bytes(FERNET.encrypt(token.encode()))


# ── Netatmo API ───────────────────────────────────────────────────────────────

def refresh_access_token() -> str:
    """Vymění refresh token za access token a uloží nový (rotovaný) refresh token."""
    candidates = load_refresh_candidates()
    if not candidates:
        raise RuntimeError("Chybí refresh token – nastav secret NETATMO_REFRESH_TOKEN.")

    last_err = None
    for refresh_token in candidates:
        try:
            resp = requests.post(f"{API}/oauth2/token", data={
                "grant_type":    "refresh_token",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            }, timeout=15)
            data = resp.json()
        except Exception as e:
            last_err = f"Obnova tokenu selhala (síť): {e}"
            continue

        access_token = data.get("access_token")
        if access_token:
            # Rotovaný refresh token okamžitě ulož – starý přestává platit
            save_refresh_token(data.get("refresh_token") or refresh_token)
            return access_token
        last_err = f"Obnova tokenu odmítnuta: {data.get('error', resp.status_code)}"

    raise RuntimeError(f"{last_err} – vygeneruj nový NETATMO_REFRESH_TOKEN na dev.netatmo.com.")


def get_stations(access_token: str) -> list:
    resp = requests.get(f"{API}/api/getstationsdata",
                        headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return (data.get("body") or {}).get("devices") or []


def get_rain_8h(access_token: str, device_id: str, module_id: str):
    """Úhrn srážek za posledních 8 h (mm) přes getmeasure, nebo None bez dat.

    Netatmo dashboard_data dává jen Rain / sum_rain_1 / sum_rain_24, takže
    8h úhrn skládáme z hodinových součtů (scale=1hour, type=sum_rain).
    """
    now = int(time.time())
    resp = requests.get(f"{API}/api/getmeasure", params={
        "device_id":  device_id,
        "module_id":  module_id,
        "type":       "sum_rain",
        "scale":      "1hour",
        "date_begin": now - 8 * 3600,
        "date_end":   now,
        "optimize":   "true",
    }, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    resp.raise_for_status()
    body = resp.json().get("body") or []
    values = [v[0] for series in body for v in (series.get("value") or [])
              if v and v[0] is not None]
    if not values:
        return None
    return round(sum(values), 1)


def insert_after(d: dict, after_key: str, key: str, value) -> dict:
    """Kopie dictu s novým klíčem vloženým za after_key (pořadí řádků na dashboardu)."""
    out = {}
    for k, v in d.items():
        out[k] = v
        if k == after_key:
            out[key] = value
    out.setdefault(key, value)
    return out


def get_noise_history(access_token: str, device_id: str) -> list:
    """24h historie hluku po 30 minutách → [{"t": unix, "v": dB}, ...]"""
    now = int(time.time())
    resp = requests.get(f"{API}/api/getmeasure", params={
        "device_id":  device_id,
        "type":       "noise",
        "scale":      "30min",
        "date_begin": now - 86400,
        "date_end":   now,
        "optimize":   "true",
    }, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    resp.raise_for_status()
    body = resp.json().get("body") or []
    if not body:
        return []
    series = body[0]
    points = []
    t = series["beg_time"]
    for values in series.get("value") or []:
        val = values[0] if values else None
        if val is not None:
            points.append({"t": t, "v": val})
        t += series.get("step_time", 1800)
    return points


# ── Výstup ────────────────────────────────────────────────────────────────────

def write_output(error, modules=None, noise=None):
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "error":   error,
        "modules": modules or [],
        "noise":   noise or [],
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Uloženo do {OUTPUT_PATH}" + (f"  (error: {error})" if error else ""))


def fetch():
    try:
        access_token = refresh_access_token()
    except Exception as e:
        write_output(str(e))
        return

    try:
        stations = get_stations(access_token)
        if not stations:
            write_output(None)
            return

        # Stanice + moduly → jednotný seznam {name, data}
        modules = []
        for station in stations:
            mods = [(station.get("module_name") or "Vnitřní", station.get("dashboard_data"), None)]
            for m in station.get("modules") or []:
                mods.append((m.get("module_name") or m.get("type", ""), m.get("dashboard_data"), m.get("_id")))
            for name, dd, module_id in mods:
                if not dd:
                    continue
                # Srážkoměr (NAModule3): doplnit úhrn za posledních 8 h
                if "Rain" in dd and module_id:
                    try:
                        rain8 = get_rain_8h(access_token, station["_id"], module_id)
                        if rain8 is not None:
                            dd = insert_after(dd, "sum_rain_1", "sum_rain_8", rain8)
                    except Exception as e:
                        print(f"WARN: Úhrn srážek za 8 h selhal: {e}")
                modules.append({"name": name, "data": dd})

        # Historie hluku pro první stanici, která hluk měří
        noise = []
        first = stations[0]
        if "Noise" in (first.get("dashboard_data") or {}):
            try:
                noise = get_noise_history(access_token, first["_id"])
            except Exception as e:
                print(f"WARN: Historie hluku selhala: {e}")

        write_output(None, modules, noise)
        print(f"✓ Načteno {len(modules)} modulů, {len(noise)} bodů hluku")

    except Exception as e:
        write_output(f"Načtení dat selhalo: {e}")


if __name__ == "__main__":
    fetch()
