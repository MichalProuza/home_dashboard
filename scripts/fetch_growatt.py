#!/usr/bin/env python3
"""
Stahuje data solární elektrárny přes oficiální Growatt Open API V1
(token-based) a ukládá je do data/growatt.json. Spouští se přes GitHub Actions.

Dřívější přihlašování jménem a heslem (newTwoLoginAPI.do) Growatt zablokoval
(HTTP 403 Forbidden), proto se používá oficiální V1 API s tokenem.

Token vygeneruješ v aplikaci ShinePhone: Já → (tvůj účet) → API Token,
případně na webu: Nastavení → Account Management → API Key. Ulož ho do
GitHub Secret GROWATT_API_TOKEN.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import growattServer
except ImportError:
    print("ERROR: growattServer není nainstalován. Spusť: pip install growattServer")
    sys.exit(1)

# ── Přihlašovací údaje z GitHub Secrets ──────────────────────────────────────
API_TOKEN = os.environ.get("GROWATT_API_TOKEN", "")

if not API_TOKEN:
    print("ERROR: Chybí GROWATT_API_TOKEN v prostředí / GitHub Secrets "
          "(vygeneruj v aplikaci ShinePhone: Já → účet → API Token).")
    sys.exit(1)

# ── Výstupní soubor ───────────────────────────────────────────────────────────
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "growatt.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Typy zařízení podle V1 API (device_list → "type"); hodnoty drží názvosloví
# původního JSON schématu ("mix", "tlx", …), aby frontend nepoznal rozdíl
TYPE_NAMES = {1: "inverter", 2: "storage", 3: "other", 4: "max", 5: "mix",
              6: "spa", 7: "tlx", 8: "pcs", 9: "hps", 10: "pbd"}

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def pick(d, *keys, default=None):
    """Vrátí první existující klíč ze slovníku (bez ohledu na velikost písmen)."""
    if not isinstance(d, dict):
        return default
    lower = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v is not None:
            return v
    return default

def fetch():
    api = growattServer.OpenApiV1(token=API_TOKEN)
    now_utc = datetime.now(timezone.utc).isoformat()

    try:
        plants = (api.plant_list() or {}).get("plants") or []
    except Exception as e:
        print(f"ERROR: Načtení seznamu elektráren selhalo: {e}")
        sys.exit(1)

    if not plants:
        print("WARN: Žádné elektrárny nenalezeny.")
        output = {"updated": now_utc, "error": "no_plants", "plants": []}
        OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    result_plants = []

    for plant in plants:
        plant_id = pick(plant, "plant_id", "id")
        plant_name = pick(plant, "name", "plant_name", default=str(plant_id))

        # Souhrn výroby (dnes/celkem) na úrovni elektrárny
        try:
            overview = api.plant_energy_overview(plant_id) or {}
        except Exception as e:
            print(f"WARN: Přehled výroby selhal: {e}")
            overview = {}

        try:
            devices = (api.device_list(plant_id) or {}).get("devices") or []
        except Exception as e:
            print(f"WARN: Seznam zařízení selhal: {e}")
            devices = []

        result_devices = []

        for device in devices:
            sn = pick(device, "device_sn", "sn", default="")
            type_id = pick(device, "type", default=0)
            device_data = {
                "sn": sn,
                "name": pick(device, "alias", "device_name", "model", default=sn),
                "type": TYPE_NAMES.get(type_id, str(type_id)),
                "status": pick(device, "status", default=-1),
            }

            try:
                if type_id in (5, 6):    # SPH/SPA – hybridní střídač (dříve "mix")
                    energy = api.sph_energy(sn) or {}
                elif type_id == 7:       # MIN (dříve "tlx")
                    energy = api.min_energy(sn) or {}
                else:
                    energy = {}

                if energy:
                    # Jen názvy klíčů (ne hodnoty) – pomáhá doladit mapování polí
                    print(f"DEBUG {device_data['type']} energy keys: {sorted(energy.keys())}")

                    pcharge    = safe_float(pick(energy, "pcharge1", "p_charge1", "pcharge"))
                    pdischarge = safe_float(pick(energy, "pdischarge1", "p_discharge1", "pdischarge"))
                    to_grid    = safe_float(pick(energy, "pactogrid_total", "pactogrid", "pac_to_grid_total", "pactogrid_r"))
                    to_user    = safe_float(pick(energy, "pactouser_total", "pactouser", "pac_to_user_total", "pactouser_r"))

                    device_data.update({
                        "solar_w":        safe_float(pick(energy, "ppv", "pac")),
                        "battery_pct":    safe_float(pick(energy, "soc")),
                        "battery_w":      pcharge - pdischarge,
                        "grid_w":         to_grid if to_grid > 0 else to_user,
                        "grid_direction": "export" if to_grid > 0 else "import",
                        "load_w":         safe_float(pick(energy, "plocal_load_total", "plocaload_total",
                                                          "plocaload", "p_local_load", "local_load_power", "pload")),
                        "today_kwh":      safe_float(pick(energy, "epv_today", "epvtoday", "eac_today", "etoday",
                                                          default=pick(overview, "today_energy"))),
                        "total_kwh":      safe_float(pick(energy, "epv_total", "epvtotal", "eac_total", "etotal",
                                                          default=pick(overview, "total_energy"))),
                        "today_import_kwh": safe_float(pick(energy, "etouser_today", "eto_user_today")),
                        "today_export_kwh": safe_float(pick(energy, "etogrid_today", "eto_grid_today")),
                    })
            except Exception as e:
                device_data["error"] = str(e)

            result_devices.append(device_data)

        result_plants.append({
            "id":      plant_id,
            "name":    plant_name,
            "today_kwh": safe_float(pick(overview, "today_energy", default=pick(plant, "today_energy"))),
            "total_kwh": safe_float(pick(overview, "total_energy", default=pick(plant, "total_energy"))),
            "current_w": safe_float(pick(plant, "current_power", default=pick(overview, "current_power"))),
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
