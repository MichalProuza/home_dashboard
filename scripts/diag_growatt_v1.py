#!/usr/bin/env python3
"""
DOČASNÁ diagnostika V1 API: vypíše klíče odpovědí plant_list / device_list /
sph_detail / sph_energy, aby šlo napsat přesné mapování polí.

Vypisuje POUZE názvy klíčů a hodnoty výkonových/energetických polí (ta se
stejně veřejně publikují v growatt.json). Žádné ID, tokeny ani polohu.
Vždy končí exit 1, aby se nespustil publish krok.
"""

import os
import sys

import growattServer

TOKEN = os.environ.get("GROWATT_API_TOKEN", "").strip()
if not TOKEN:
    print("ERROR: Chybí GROWATT_API_TOKEN.")
    sys.exit(1)

SAFE_SUBSTRINGS = (
    "ppv", "soc", "charge", "discharge", "pacto", "load", "epv",
    "etogrid", "etouser", "eac", "current_power", "today_energy",
    "total_energy", "peak_power", "pac", "elocal", "status", "lost", "type",
)

def dump(label, obj):
    if not isinstance(obj, dict):
        print(f"{label}: typ {type(obj).__name__}")
        return
    print(f"{label} klíče: {sorted(obj.keys())}")
    for k in sorted(obj.keys()):
        if any(s in k.lower() for s in SAFE_SUBSTRINGS):
            v = obj[k]
            if isinstance(v, (int, float, str, bool, type(None))):
                print(f"  {label}.{k} = {v!r}")

api = growattServer.OpenApiV1(token=TOKEN)

plants = api.plant_list()
dump("plant_list", plants)
plant_rows = plants.get("plants") or []
print(f"počet plantáží: {len(plant_rows)}")

for plant in plant_rows:
    dump("plant", plant)
    pid = plant.get("plant_id")

    try:
        overview = api.plant_energy_overview(pid)
        dump("plant_energy_overview", overview)
    except Exception as e:
        print(f"plant_energy_overview selhalo: {type(e).__name__}: {e}")

    devices = api.device_list(pid)
    dump("device_list", devices)
    for dev in devices.get("devices") or []:
        dump("device", dev)
        if dev.get("type") == 5:  # SPH / mix
            sn = dev.get("device_sn")
            try:
                dump("sph_detail", api.sph_detail(sn))
            except Exception as e:
                print(f"sph_detail selhalo: {type(e).__name__}: {e}")
            try:
                dump("sph_energy", api.sph_energy(sn))
            except Exception as e:
                print(f"sph_energy selhalo: {type(e).__name__}: {e}")

print("Diagnostika hotova — záměrně exit 1, aby neproběhl publish.")
sys.exit(1)
