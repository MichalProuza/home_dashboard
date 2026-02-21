#!/usr/bin/env python3
"""
Stahuje data ze shine.growatt.com a ukládá je do data/growatt.json
Spouští se přes GitHub Actions každých 15 minut.
"""

import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import growattServer
except ImportError:
    print("ERROR: growattServer není nainstalován. Spusť: pip install growattServer")
    sys.exit(1)

# ── Přihlašovací údaje z GitHub Secrets ──────────────────────────────────────
USERNAME = os.environ.get("GROWATT_USER", "")
PASSWORD = os.environ.get("GROWATT_PASS", "")

if not USERNAME or not PASSWORD:
    print("ERROR: Chybí GROWATT_USER nebo GROWATT_PASS v prostředí / GitHub Secrets.")
    sys.exit(1)

# ── Výstupní soubor ───────────────────────────────────────────────────────────
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "growatt.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

SERVERS = [
    "https://openapi.growatt.com/",
    "https://openapi-eu.growatt.com/",
    "https://openapi-us.growatt.com/",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Origin": "https://server.growatt.com",
    "Referer": "https://server.growatt.com/",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
}

def try_login(server_url):
    try:
        api = growattServer.GrowattApi(add_random_user_id=True)
    except TypeError:
        api = growattServer.GrowattApi()
    # Správný název atributu je server_url (ne server)
    api.server_url = server_url
    # Přidej browser-like hlavičky do session
    if hasattr(api, 'session'):
        api.session.headers.update(BROWSER_HEADERS)
    login_res = api.login(USERNAME, PASSWORD)
    return api, login_res

def fetch():
    print(f"INFO: growattServer verze: {growattServer.__version__ if hasattr(growattServer, '__version__') else 'neznámá'}")

    api = None
    login_res = None
    for server_url in SERVERS:
        print(f"INFO: Zkouším server: {server_url}")
        try:
            api, login_res = try_login(server_url)
            if login_res and login_res.get("result") == 1:
                print(f"INFO: Přihlášení OK přes {server_url}")
                break
            else:
                print(f"WARN: Server {server_url} vrátil: {login_res}")
                login_res = None
        except Exception as e:
            print(f"WARN: Server {server_url} selhal: {e}")
            login_res = None

    if not login_res:
        print("ERROR: Žádný server nefungoval. Growatt API pravděpodobně blokuje IP adresy GitHub Actions.")
        sys.exit(1)

    try:
        user_id = login_res["user"]["id"]
    except (KeyError, TypeError) as e:
        print(f"ERROR: Nelze získat user_id: {e}. login_res: {login_res}")
        sys.exit(1)
    now_utc = datetime.now(timezone.utc).isoformat()
    today = datetime.now().strftime("%Y-%m-%d")

    # Získej seznam plantáží
    plants = api.plant_list(user_id)
    if not plants or not plants.get("data"):
        print("WARN: Žádné plantáže nenalezeny.")
        output = {"updated": now_utc, "error": "no_plants", "plants": []}
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        return

    result_plants = []

    for plant in plants["data"]:
        plant_id = plant["plantId"]
        plant_name = plant.get("plantName", plant_id)

        # Přehled plantáže (celková výroba, příkon ze sítě…)
        try:
            plant_detail = api.plant_detail(plant_id, 1, today)
        except Exception:
            plant_detail = {}

        # Seznam zařízení
        try:
            devices = api.device_list(plant_id)
        except Exception:
            devices = {"data": []}

        result_devices = []

        for device in (devices.get("data") or []):
            sn = device.get("deviceSn") or device.get("sn", "")
            dev_type = device.get("deviceType", "").lower()

            device_data = {
                "sn": sn,
                "name": device.get("deviceAlias", sn),
                "type": dev_type,
                "status": device.get("status", -1),
            }

            # Mix / hybridní střídač
            if dev_type in ("mix", "hybrid", "sph", "spa"):
                try:
                    mix = api.mix_system_status(sn, plant_id)
                    mix_total = api.mix_totals(sn, plant_id)

                    pcharge1    = safe_float(mix.get("pcharge1", 0))
                    pdischarge1 = safe_float(mix.get("pdischarge1", 0))
                    device_data.update({
                        "solar_w":        safe_float(mix.get("ppv")),
                        "battery_pct":    safe_float(mix.get("SOC")),
                        "battery_w":      pcharge1 - pdischarge1,
                        "battery_status": mix.get("batteryType", ""),
                        "grid_w":         safe_float(mix.get("pactogrid", mix.get("pactouser", 0))),
                        "grid_direction": "export" if safe_float(mix.get("pactogrid", 0)) > 0 else "import",
                        "load_w":         safe_float(mix.get("pLocalLoad", mix.get("pLoad", 0))),
                        "today_kwh":      safe_float(mix_total.get("epvToday", mix_total.get("eChargeToday", 0))),
                        "total_kwh":      safe_float(mix_total.get("epvTotal", mix_total.get("eChargeTotal", 0))),
                        "today_import_kwh":  safe_float(mix_total.get("etoUserToday", 0)),
                        "today_export_kwh":  safe_float(mix_total.get("etoGridToday", 0)),
                    })
                except Exception as e:
                    device_data["error"] = str(e)

            # Standardní střídač (tlak)
            elif dev_type in ("tlx", "inv", "inverter", ""):
                try:
                    inv = api.inverter_data(sn, today)
                    inv_detail = api.inverter_detail(sn)

                    device_data.update({
                        "solar_w":     safe_float(inv_detail.get("ppv", inv_detail.get("pac", 0))),
                        "today_kwh":   safe_float(inv_detail.get("eacToday", 0)),
                        "total_kwh":   safe_float(inv_detail.get("eacTotal", 0)),
                        "grid_w":      safe_float(inv_detail.get("pacToGrid", 0)),
                        "grid_direction": "export" if safe_float(inv_detail.get("pacToGrid", 0)) > 0 else "import",
                        "battery_pct": safe_float(inv_detail.get("SOC", 0)),
                    })
                except Exception as e:
                    device_data["error"] = str(e)

            result_devices.append(device_data)

        result_plants.append({
            "id":      plant_id,
            "name":    plant_name,
            "today_kwh": safe_float(plant.get("todayEnergy", 0)),
            "total_kwh": safe_float(plant.get("totalEnergy", 0)),
            "current_w": safe_float(plant.get("currentPower", 0)),
            "devices": result_devices,
        })

    output = {
        "updated": now_utc,
        "error":   None,
        "plants":  result_plants,
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✓ Uloženo do {OUTPUT_PATH}  ({now_utc})")

if __name__ == "__main__":
    fetch()
