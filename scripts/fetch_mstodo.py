#!/usr/bin/env python3
"""
Stahuje nedokončené úkoly z Microsoft To Do (Microsoft Graph) a ukládá je do
data/mstodo.json. Spouští se přes GitHub Actions – díky tomu je To Do dostupné
i v kiosk verzi (kiosk.html), která umí jen číst hotový JSON z větve "data"
a nezvládne interaktivní OAuth přihlášení v prohlížeči.

Stejně jako u Netatma rotuje refresh token při použití, proto se aktuální
refresh token udržuje zašifrovaný v data/mstodo_token.enc, který workflow
publikuje do větve "data" a před dalším během zase načte.

Potřebné GitHub Secrets:
  MSTODO_CLIENT_ID      – ID aplikace (klienta) z https://portal.azure.com
                          → Registrace aplikací. Veřejný klient (bez secretu).
  MSTODO_REFRESH_TOKEN  – Počáteční refresh token se scope
                          "Tasks.Read offline_access". Použije se jen pokud
                          data/mstodo_token.enc neexistuje nebo přestal platit.
  MSTODO_TOKEN_KEY      – Libovolné dlouhé náhodné heslo; šifruje uložený
                          refresh token (větev data je veřejně viditelná).
Volitelně:
  MSTODO_TENANT         – 'consumers' (výchozí, osobní MS účty) / 'common'.
  MSTODO_LIST           – Název seznamu úkolů (výchozí 'Vranov').

Pozn. k Azure: refresh tokeny vydané pro typ "Jednostránková aplikace (SPA)"
mají životnost jen 24 h. Aby token na pozadí vydržel (rotace jednou za běh),
zaregistruj aplikaci i jako "Mobilní a klasické aplikace" (veřejný klient)
a počáteční MSTODO_REFRESH_TOKEN vygeneruj proti ní – ten vydrží ~90 dní.
"""

import base64
import hashlib
import json
import os
import sys
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
CLIENT_ID    = os.environ.get("MSTODO_CLIENT_ID", "")
SEED_REFRESH = os.environ.get("MSTODO_REFRESH_TOKEN", "")
TOKEN_KEY    = os.environ.get("MSTODO_TOKEN_KEY", "")
# Pozn.: workflow předává tyto env vždy (i prázdné, když secret chybí), proto
# `or` místo defaultu v get() – jinak by prázdný řetězec přebil výchozí hodnotu.
TENANT       = os.environ.get("MSTODO_TENANT") or "consumers"
LIST_NAME    = os.environ.get("MSTODO_LIST") or "Vranov"

if not CLIENT_ID or not TOKEN_KEY:
    print("ERROR: Chybí MSTODO_CLIENT_ID nebo MSTODO_TOKEN_KEY.")
    sys.exit(1)

DATA_DIR    = Path(__file__).parent.parent / "data"
OUTPUT_PATH = DATA_DIR / "mstodo.json"
TOKEN_PATH  = DATA_DIR / "mstodo_token.enc"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
GRAPH     = "https://graph.microsoft.com/v1.0"
SCOPE     = "Tasks.Read offline_access"
FERNET    = Fernet(base64.urlsafe_b64encode(hashlib.sha256(TOKEN_KEY.encode()).digest()))


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
                print("WARN: mstodo_token.enc nelze dešifrovat (změnil se MSTODO_TOKEN_KEY?)")
        else:
            # Prázdný soubor (selhalo načtení z větve data) – smazat, aby
            # publish_data.sh nepřepsal platný token v repu prázdným obsahem
            TOKEN_PATH.unlink()
    if SEED_REFRESH and SEED_REFRESH not in candidates:
        candidates.append(SEED_REFRESH)
    return candidates


def save_refresh_token(token: str):
    TOKEN_PATH.write_bytes(FERNET.encrypt(token.encode()))


# ── Microsoft identity platform / Graph ──────────────────────────────────────

def refresh_access_token() -> str:
    """Vymění refresh token za access token a uloží nový (rotovaný) refresh token."""
    candidates = load_refresh_candidates()
    if not candidates:
        raise RuntimeError("Chybí refresh token – nastav secret MSTODO_REFRESH_TOKEN.")

    last_err = None
    for refresh_token in candidates:
        try:
            resp = requests.post(TOKEN_URL, data={
                "client_id":     CLIENT_ID,
                "grant_type":    "refresh_token",
                "refresh_token": refresh_token,
                "scope":         SCOPE,
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

    raise RuntimeError(f"{last_err} – vygeneruj nový MSTODO_REFRESH_TOKEN (Azure / scope {SCOPE}).")


def get_lists(access_token: str) -> list:
    resp = requests.get(f"{GRAPH}/me/todo/lists",
                        headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("value") or []


def get_open_tasks(access_token: str, list_id: str) -> list:
    """Nedokončené úkoly seznamu, seřazené podle důležitosti a data vzniku."""
    url = (f"{GRAPH}/me/todo/lists/{list_id}/tasks"
           "?$filter=status ne 'completed'"
           "&$orderby=importance desc,createdDateTime asc"
           "&$top=50")
    resp = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("value") or []


def simplify_task(task: dict) -> dict:
    """Graph úkol → minimální položka pro frontend (jen nutná pole)."""
    due = None
    dd = task.get("dueDateTime") or {}
    raw = dd.get("dateTime")
    if raw:
        # "2026-06-16T00:00:00.0000000" → "2026-06-16"
        due = str(raw)[:10]
    return {
        "title":     task.get("title", ""),
        "due":       due,
        "important": task.get("importance") == "high",
    }


# ── Výstup ────────────────────────────────────────────────────────────────────

def write_output(error, list_name=None, tasks=None):
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "error":   error,
        "list":    list_name or LIST_NAME,
        "tasks":   tasks or [],
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
        lists = get_lists(access_token)
        target = next((l for l in lists if l.get("displayName") == LIST_NAME), None)
        if not target:
            write_output(f'Seznam „{LIST_NAME}" nenalezen.')
            return

        raw_tasks = get_open_tasks(access_token, target["id"])
        tasks = [simplify_task(t) for t in raw_tasks]
        write_output(None, target.get("displayName"), tasks)
        print(f'✓ Načteno {len(tasks)} nedokončených úkolů ze seznamu „{LIST_NAME}"')

    except Exception as e:
        write_output(f"Načtení úkolů selhalo: {e}")


if __name__ == "__main__":
    fetch()
