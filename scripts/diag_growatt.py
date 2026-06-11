#!/usr/bin/env python3
"""
DOČASNÁ diagnostika: zkouší přihlášení ke Growatt legacy API přes různé
servery a User-Agenty, aby se zjistilo, odkud přichází 403 Forbidden.

Loguje POUZE HTTP status / typ chyby — nikdy přihlašovací údaje ani obsah
odpovědí. Vždy končí exit kódem 1, aby se nikdy nespustil publish krok.
"""

import hashlib
import os
import sys

import requests

USERNAME = os.environ.get("GROWATT_USER", "")
PASSWORD = os.environ.get("GROWATT_PASS", "")

if not USERNAME or not PASSWORD:
    print("ERROR: Chybí GROWATT_USER nebo GROWATT_PASS.")
    sys.exit(1)


def hash_password(password: str) -> str:
    """Stejný algoritmus jako growattServer.hash_password (md5 + oprava nul)."""
    password_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
    for i in range(0, len(password_md5), 2):
        if password_md5[i] == "0":
            password_md5 = password_md5[0:i] + "c" + password_md5[i + 1:]
    return password_md5


SERVERS = [
    "https://server.growatt.com/",
    "https://openapi.growatt.com/",
    "https://server-api.growatt.com/",
    "https://server-us.growatt.com/",
    "https://openapi-us.growatt.com/",
]

USER_AGENTS = {
    "dalvik": "Dalvik/2.1.0 (Linux; U; Android 12; https://github.com/indykoning/PyPi_GrowattServer) - 8h4f6k1q",
    "shinephone": "ShinePhone/8.1.8 (iPhone; iOS 16.6; Scale/3.00)",
    "okhttp": "okhttp/4.12.0",
    "browser": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
}

hashed = hash_password(PASSWORD)

for server in SERVERS:
    for ua_name, ua in USER_AGENTS.items():
        url = server + "newTwoLoginAPI.do"
        try:
            r = requests.post(
                url,
                data={"userName": USERNAME, "password": hashed},
                headers={"User-Agent": ua},
                timeout=20,
            )
            verdict = f"HTTP {r.status_code}"
            if r.status_code == 200:
                try:
                    back = r.json().get("back", {})
                    verdict += f" success={back.get('success')!r} msg={back.get('msg')!r}"
                except ValueError:
                    verdict += " (odpověď není JSON)"
        except requests.exceptions.RequestException as e:
            verdict = f"EXC {type(e).__name__}"
        print(f"{server:42s} UA={ua_name:11s} -> {verdict}")

print("Diagnostika hotova — záměrně končím s exit 1, aby neproběhl publish.")
sys.exit(1)
