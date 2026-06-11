#!/usr/bin/env python3
"""
Stahuje data ze shine.growatt.com a ukládá je do data/growatt.json
Spouští se přes GitHub Actions každých 15 minut.

Vyžaduje growattServer >= 2.x (jiné návratové tvary než 1.x).
"""

import os
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import growattServer
except ImportError:
    print("ERROR: growattServer není nainstalován. Spusť: pip install growattServer")
    sys.exit(1)

# Growatt WAF blokuje výchozí User-Agent knihovny ("Dalvik/... PyPi_GrowattServer")
# s 403 Forbidden — UA oficiální mobilní aplikace projde.
AGENT_IDENTIFIER = "ShinePhone/8.1.8 (iPhone; iOS 16.6; Scale/3.00)"

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
    """Převede hodnotu na float; zvládne i řetězce s jednotkou ('142 W', '0.7 kWh')."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        m = re.match(r"\s*(-?\d+(?:[.,]\d+)?)", val)
        if m:
            return float(m.group(1).replace(",", "."))
    return default

def parse_with_unit(val, factors):
    """Převede '1.2 kW' → 1200 (W) resp. '0.7 kWh' → 0.7 podle mapy jednotek."""
    num = safe_float(val)
    if isinstance(val, str):
        m = re.search(r"([a-zA-Z]+)\s*$", val.strip())
        if m:
            factor = factors.get(m.group(1).lower())
            if factor is not None:
                return num * factor
    return num

POWER_W   = {"w": 1, "kw": 1000, "mw": 1000000}
ENERGY_KWH = {"wh": 0.001, "kwh": 1, "mwh": 1000}

def fetch():
    api = growattServer.GrowattApi(agent_identifier=AGENT_IDENTIFIER)
    api.server_url = "https://server.growatt.com/"

    try:
        login_res = api.login(USERNAME, PASSWORD)
    except Exception as e:
        print(f"ERROR: Přihlášení selhalo: {e}")
        sys.exit(1)

    # Pozor: nevypisovat obsah login_res – Actions logy jsou veřejné
    if not isinstance(login_res, dict) or not login_res.get("success"):
        msg = login_res.get("msg") if isinstance(login_res, dict) else None
        print(f"ERROR: Špatné přihlašovací údaje nebo API chyba (msg={msg!r})")
        sys.exit(1)

    user_id = login_res.get("userId") or (login_res.get("user") or {}).get("id")
    if not user_id:
        print("ERROR: Nelze získat user_id z odpovědi loginu.")
        sys.exit(1)

    now_utc = datetime.now(timezone.utc).isoformat()

    # Seznam plantáží (nevypisovat obsah – může obsahovat polohu domu)
    plants_res = api.plant_list(user_id)
    plant_rows = plants_res.get("data") if isinstance(plants_res, dict) else plants_res
    print(f"DEBUG: nalezeno plantáží: {len(plant_rows or [])}")
    if not plant_rows:
        print("WARN: Žádné plantáže nenalezeny.")
        output = {"updated": now_utc, "error": "no_plants", "plants": []}
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    result_plants = []

    for plant in plant_rows:
        plant_id = plant["plantId"]
        plant_name = plant.get("plantName", plant_id)

        # Seznam zařízení (growattServer 2.x vrací rovnou list)
        try:
            devices = api.device_list(plant_id)
        except Exception:
            devices = []
        if isinstance(devices, dict):
            devices = devices.get("data") or devices.get("deviceList") or []

        result_devices = []

        for device in devices:
            sn = device.get("deviceSn") or device.get("sn", "")
            dev_type = str(device.get("deviceType", "")).lower()

            device_data = {
                "sn": sn,
                # "deviceAilas" je překlep přímo v Growatt API
                "name": device.get("deviceAlias") or device.get("deviceAilas") or sn,
                "type": dev_type,
                "status": device.get("status", -1),
            }

            # Mix / hybridní střídač — okamžité hodnoty jsou v kW, převádíme na W
            if dev_type in ("mix", "hybrid", "sph", "spa"):
                try:
                    mix = api.mix_system_status(sn, plant_id)
                    mix_total = api.mix_totals(sn, plant_id)

                    charge_kw    = safe_float(mix.get("chargePower"))
                    discharge_kw = safe_float(mix.get("pdisCharge1"))
                    to_grid_kw   = safe_float(mix.get("pactogrid"))
                    from_grid_kw = safe_float(mix.get("pactouser"))
                    device_data.update({
                        "solar_w":        safe_float(mix.get("ppv")) * 1000,
                        "battery_pct":    safe_float(mix.get("SOC")),
                        "battery_w":      (charge_kw - discharge_kw) * 1000,
                        "grid_w":         (to_grid_kw if to_grid_kw > 0 else from_grid_kw) * 1000,
                        "grid_direction": "export" if to_grid_kw > 0 else "import",
                        "load_w":         safe_float(mix.get("pLocalLoad")) * 1000,
                        "today_kwh":      safe_float(mix_total.get("epvToday")),
                        "total_kwh":      safe_float(mix_total.get("epvTotal")),
                        "today_export_kwh": safe_float(mix_total.get("etoGridToday")),
                    })
                    # Dnešní import ze sítě je jen v mix_detail ('etouser')
                    try:
                        detail = api.mix_detail(sn, plant_id)
                        device_data["today_import_kwh"] = safe_float(detail.get("etouser"))
                    except Exception:
                        device_data["today_import_kwh"] = 0.0
                except Exception as e:
                    device_data["error"] = str(e)

            # Standardní střídač
            elif dev_type in ("tlx", "inv", "inverter", ""):
                try:
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

        # Frontend čte plants[0].devices[0] — střídač s daty musí být první
        # (device_list vrací i pomocná zařízení, např. "boost" nebo elektroměr)
        result_devices.sort(key=lambda d: "solar_w" not in d)

        result_plants.append({
            "id":      plant_id,
            "name":    plant_name,
            # PlantListAPI vrací hodnoty jako řetězce s jednotkou (např. '142 W', '0.7 kWh')
            "today_kwh": parse_with_unit(plant.get("todayEnergy", 0), ENERGY_KWH),
            "total_kwh": parse_with_unit(plant.get("totalEnergy", 0), ENERGY_KWH),
            "current_w": parse_with_unit(plant.get("currentPower", 0), POWER_W),
            "devices": result_devices,
        })

    output = {
        "updated": now_utc,
        "error":   None,
        "plants":  result_plants,
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Uloženo do {OUTPUT_PATH}  ({now_utc})")

if __name__ == "__main__":
    fetch()
