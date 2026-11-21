#!/usr/bin/env python3
"""
Malý HTTP server domácího serveru (jen stdlib) — náhrada větve "data"
a workflow_dispatch pro Cloudflare Pages Functions (DATA_SOURCE=home).

Poslouchá jen na localhostu; ven ho vystavuje cloudflared tunnel na
samostatném hostname chráněném Cloudflare Access service tokenem
(viz HOMESERVER.md). Sám žádnou autentizaci nedělá.

Endpointy:
  GET  /data/<název>.json  JSON z HD_DATA_DIR (jen [A-Za-z0-9_-]+.json, žádné
                           podadresáře → žádný path traversal; tokeny leží
                           v jiném adresáři a mají příponu .enc)
  POST /refresh            spustí živé zdroje (`run.py once live`) na pozadí;
                           když byl refresh spuštěn před < 3 min, jen vrátí
                           {"status": "running"} — stejně jako functions/api/refresh.js.
                           Vyžaduje hlavičku X-Dashboard-Refresh: 1.
  GET  /healthz            stav posledních běhů jednotlivých zdrojů

Použití:
  server.py [--host 127.0.0.1] [--port 8787] [--log-file …]
"""

import argparse
import json
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOCAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LOCAL_DIR.parent))
import hd_common  # noqa: E402

DATA_DIR = hd_common.local_data_dir()
STATE_DIR = hd_common.local_state_dir()
LAST_REFRESH = STATE_DIR / "last_refresh"

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+\.json$")
MIN_REFRESH_INTERVAL_S = 3 * 60
# Stejné zdroje jako WORKFLOWS ve functions/api/refresh.js
LIVE = ["netatmo", "tuya", "growatt", "weather", "mstodo"]

log = logging.getLogger("server")
_refresh_lock = threading.Lock()


def start_refresh() -> dict:
    """Spustí runner pro živé zdroje, nebo ohlásí, že nedávno běžel."""
    with _refresh_lock:
        now = time.time()
        try:
            last = float(LAST_REFRESH.read_text().strip())
        except (OSError, ValueError):
            last = 0.0
        if now - last < MIN_REFRESH_INTERVAL_S:
            since = datetime.fromtimestamp(last, timezone.utc).isoformat()
            return {"status": "running", "since": since}
        hd_common.write_bytes(LAST_REFRESH, f"{now:.0f}".encode())
        args = [sys.executable, str(LOCAL_DIR / "run.py")]
        log_file = os.environ.get("HD_RUNNER_LOG")
        if log_file:
            args += ["--log-file", log_file]
        # Samostatný proces (a session), ať doběhne i při restartu serveru;
        # souběh s daemonem hlídají zámky zdrojů v run.py
        subprocess.Popen(args + ["once", *LIVE], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, cwd=str(LOCAL_DIR.parent.parent))
        return {"status": "started", "started": len(LIVE), "failed": []}


def health() -> dict:
    sources = {}
    status_dir = STATE_DIR / "status"
    for p in sorted(status_dir.glob("*.json")) if status_dir.exists() else []:
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            sources[p.stem] = {k: st.get(k) for k in ("started", "rc", "json_error")}
        except (OSError, ValueError):
            sources[p.stem] = {"error": "nečitelný stav"}
    ok = bool(sources) and all(s.get("rc") in (0, 75) and not s.get("json_error")
                               for s in sources.values())
    return {"ok": ok, "sources": sources}


class Handler(BaseHTTPRequestHandler):
    server_version = "home-dashboard"
    sys_version = ""

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def do_GET(self):
        path = self._path()
        if path == "/healthz":
            return self._json(200, health())
        if path.startswith("/data/"):
            name = path[len("/data/"):]
            if not NAME_RE.match(name):
                return self._json(400, {"error": "neplatný název souboru"})
            try:
                body = (DATA_DIR / name).read_bytes()
            except FileNotFoundError:
                return self._json(404, {"error": "data nedostupná"})
            except OSError as e:
                log.error("čtení %s selhalo: %s", name, e)
                return self._json(500, {"error": "data nedostupná"})
            return self._send(200, body)
        return self._json(404, {"error": "nenalezeno"})

    do_HEAD = do_GET

    def do_POST(self):
        if self._path() != "/refresh":
            return self._json(404, {"error": "nenalezeno"})
        if self.headers.get("X-Dashboard-Refresh") != "1":
            return self._json(400, {"error": "chybí hlavička X-Dashboard-Refresh"})
        try:
            result = start_refresh()
        except Exception as e:
            log.exception("refresh selhal")
            return self._json(500, {"error": f"spuštění selhalo ({e.__class__.__name__})"})
        log.info("refresh: %s", result["status"])
        return self._json(200, result)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default=os.environ.get("HD_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("HD_PORT", "8787")))
    ap.add_argument("--log-file", help="log s rotací (jinak stderr)")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost"):
        # Ven jen přes cloudflared + Access; přímé vystavení do LAN by obešlo autentizaci
        print(f"ERROR: server smí poslouchat jen na localhostu (ne {args.host}).")
        return 1

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    if args.log_file:
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(args.log_file, maxBytes=1_000_000,
                                                       backupCount=3, encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    hd_common.ensure_local_dirs()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    log.info("poslouchám na http://%s:%d (data: %s)", args.host, args.port, DATA_DIR)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
