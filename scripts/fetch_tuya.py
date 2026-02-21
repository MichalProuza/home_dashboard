#!/usr/bin/env python3
"""
Stahuje stav brány (nebo jiného Tuya zařízení) přes Tuya IoT Platform OpenAPI
a ukládá data do data/tuya.json.
Spouští se přes GitHub Actions každých 5 minut.

Potřebné GitHub Secrets:
  TUYA_ACCESS_ID     – Access ID z Tuya IoT Console (Cloud → projekt → Overview)
  TUYA_ACCESS_SECRET – Access Secret ze stejného místa
  TUYA_DEVICE_ID     – Device ID brány (IoT Console → Devices → Device ID)
  TUYA_REGION        – Datové centrum: "eu" | "us" | "cn" | "in"  (default: eu)
"""

import hashlib
import hmac
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

# ── Přihlašovací údaje z GitHub Secrets ──────────────────────────────────────
ACCESS_ID     = os.environ.get("TUYA_ACCESS_ID", "")
ACCESS_SECRET = os.environ.get("TUYA_ACCESS_SECRET", "")
DEVICE_ID     = os.environ.get("TUYA_DEVICE_ID", "")
REGION        = os.environ.get("TUYA_REGION", "eu").lower()

if not ACCESS_ID or not ACCESS_SECRET or not DEVICE_ID:
    print("ERROR: Chybí TUYA_ACCESS_ID, TUYA_ACCESS_SECRET nebo TUYA_DEVICE_ID.")
    sys.exit(1)

REGION_HOSTS = {
    "eu": "openapi.tuyaeu.com",
    "us": "openapi.tuyaus.com",
    "cn": "openapi.tuyacn.com",
    "in": "openapi.tuyain.com",
}
HOST = REGION_HOSTS.get(REGION, "openapi.tuyaeu.com")
BASE_URL = f"https://{HOST}"

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "tuya.json"
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Tuya HMAC-SHA256 podepisování ─────────────────────────────────────────────

def _calc_sign(access_id: str, secret: str, t: str, nonce: str,
               access_token: str, method: str, path: str, body: bytes = b"") -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    string_to_sign = f"{method}\n{body_hash}\n\n{path}"
    str_to_sign = access_id + access_token + t + nonce + string_to_sign
    return hmac.new(secret.encode(), str_to_sign.encode(), hashlib.sha256).hexdigest().upper()


def _headers(access_token: str, method: str, path: str, body: bytes = b"") -> dict:
    t = str(int(time.time() * 1000))
    nonce = ""
    sign = _calc_sign(ACCESS_ID, ACCESS_SECRET, t, nonce, access_token, method, path, body)
    return {
        "client_id":    ACCESS_ID,
        "access_token": access_token,
        "sign":         sign,
        "t":            t,
        "nonce":        nonce,
        "sign_method":  "HMAC-SHA256",
        "Content-Type": "application/json",
    }


# ── Tuya API volání ───────────────────────────────────────────────────────────

def get_token() -> str:
    """Získá dočasný access_token."""
    path = "/v1.0/token?grant_type=1"
    t = str(int(time.time() * 1000))
    nonce = ""
    sign = _calc_sign(ACCESS_ID, ACCESS_SECRET, t, nonce, "", "GET", path)
    headers = {
        "client_id":   ACCESS_ID,
        "sign":        sign,
        "t":           t,
        "nonce":       nonce,
        "sign_method": "HMAC-SHA256",
    }
    resp = requests.get(BASE_URL + path, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Token chyba: {data.get('msg', data)}")
    return data["result"]["access_token"]


def get_device_status(access_token: str, device_id: str) -> list:
    """Vrátí seznam data pointů zařízení."""
    path = f"/v1.0/iot-03/devices/{device_id}/status"
    resp = requests.get(
        BASE_URL + path,
        headers=_headers(access_token, "GET", path),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Status chyba: {data.get('msg', data)}")
    return data.get("result", [])


def get_device_info(access_token: str, device_id: str) -> dict:
    """Vrátí základní informace o zařízení (jméno, online stav…)."""
    path = f"/v1.0/iot-03/devices/{device_id}"
    resp = requests.get(
        BASE_URL + path,
        headers=_headers(access_token, "GET", path),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        return {}
    return data.get("result", {})


# ── Interpretace brány ─────────────────────────────────────────────────────────
# Různá Tuya zařízení používají různé kódy (data points):
GATE_OPEN_CODES = {
    # doorcontact_state: true = otevřeno
    "doorcontact_state": lambda v: v is True,
    # switch_1 / switch: true = zapnuto/otevřeno (záleží na zapojení)
    "switch_1":          lambda v: v is True,
    "switch":            lambda v: v is True,
    # percent_control: 100 = plně otevřeno, 0 = zavřeno
    "percent_control":   lambda v: int(v) > 0 if v is not None else False,
    "percent_state":     lambda v: int(v) > 0 if v is not None else False,
    # work_state: "open" / "close"
    "work_state":        lambda v: str(v).lower() in ("open", "opened", "opening"),
    # control: "open" / "close" / "stop"
    "control":           lambda v: str(v).lower() in ("open", "opening"),
}

def interpret_gate(dps: list) -> dict:
    """
    Z data pointů zařízení zjistí, zda je brána otevřena.
    Vrátí slovník s klíči: open (bool|None), raw_dps (list).
    """
    dp_map = {dp["code"]: dp["value"] for dp in dps}
    gate_open = None
    gate_dp = None

    for code, checker in GATE_OPEN_CODES.items():
        if code in dp_map:
            try:
                gate_open = checker(dp_map[code])
                gate_dp = code
                break
            except Exception:
                pass

    return {
        "open":    gate_open,   # True = otevřeno, False = zavřeno, None = neznámo
        "dp_used": gate_dp,     # Který data point byl použit
        "raw_dps": dps,         # Všechny raw data pointy pro debugging
    }


# ── Hlavní funkce ──────────────────────────────────────────────────────────────
def fetch():
    now_utc = datetime.now(timezone.utc).isoformat()

    try:
        print(f"INFO: Připojuji se k Tuya OpenAPI ({HOST})…")
        token = get_token()
        print("INFO: Token získán.")

        info = get_device_info(token, DEVICE_ID)
        device_name = info.get("name", DEVICE_ID)
        online = info.get("online", None)
        print(f"INFO: Zařízení: {device_name}, online: {online}")

        dps = get_device_status(token, DEVICE_ID)
        print(f"INFO: Data pointy: {dps}")

        gate = interpret_gate(dps)

        output = {
            "updated":     now_utc,
            "error":       None,
            "device_name": device_name,
            "online":      online,
            "gate_open":   gate["open"],
            "dp_used":     gate["dp_used"],
            "raw_dps":     gate["raw_dps"],
        }
        print(f"✓ Brána: {'OTEVŘENA' if gate['open'] else 'ZAVŘENA' if gate['open'] is False else 'NEZNÁMO'}")

    except Exception as e:
        print(f"ERROR: {e}")
        output = {
            "updated": now_utc,
            "error":   str(e),
            "device_name": None,
            "online":  None,
            "gate_open": None,
            "dp_used": None,
            "raw_dps": [],
        }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"✓ Uloženo do {OUTPUT_PATH}")


if __name__ == "__main__":
    fetch()
