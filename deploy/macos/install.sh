#!/usr/bin/env bash
# Instalace domácího serveru home_dashboard na macOS (launchd, uživatelské agenty).
# Postup a souvislosti: HOMESERVER.md.
#
# Použití (z klonu repa, NE v ~/Documents, ~/Desktop, ~/Downloads ani v iCloudu):
#   bash deploy/macos/install.sh            venv + závislosti + agenti runner a server
#                                           (+ cloudflared, pokud existuje jeho config)
#   bash deploy/macos/install.sh --no-start jen připravit (venv, adresáře, plisty), nespouštět
#
# Proměnné (volitelné):
#   PYTHON=/opt/homebrew/bin/python3.13   interpret pro venv (min. 3.12 kvůli growattServer)
#   HD_PORT=8787                          port lokálního serveru
#   CLOUDFLARED=/opt/homebrew/bin/cloudflared
#
# Skript je idempotentní: opakované spuštění (např. po `git pull`) aktualizuje
# závislosti, přegeneruje plisty a agenty restartuje. Data, tokeny ani
# konfiguraci nepřepisuje.
set -euo pipefail

START=1
for arg in "$@"; do
  case "$arg" in
    --no-start) START=0 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Neznámý přepínač: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: install.sh je jen pro macOS." >&2
  exit 1
fi

REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
TEMPLATES="$REPO/deploy/macos"
HD_HOME="$HOME/Library/Application Support/home_dashboard"
CONFIG_DIR="$HOME/.config/home_dashboard"
ENV_FILE="$CONFIG_DIR/env"
CF_CONFIG="$CONFIG_DIR/cloudflared.yml"
LOGS="$HOME/Library/Logs/home_dashboard"
AGENTS="$HOME/Library/LaunchAgents"
VENV="$HD_HOME/venv"
PORT="${HD_PORT:-8787}"
DOMAIN="gui/$(id -u)"

say() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

# ── Kontroly ─────────────────────────────────────────────────────────────────
# launchd procesy nemají přístup do složek chráněných TCC (Documents, Desktop,
# Downloads, iCloud Drive) → skripty by padaly na „Operation not permitted".
case "$REPO" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*)
    echo "ERROR: Repo je v $REPO — složka chráněná macOS (TCC), launchd do ní nesmí." >&2
    echo "       Naklonuj ho např. do ~/src/home_dashboard a spusť install.sh odtud." >&2
    exit 1 ;;
esac

find_python() {
  if [ -n "${PYTHON:-}" ]; then echo "$PYTHON"; return; fi
  for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
           /usr/local/bin/python3.13 /usr/local/bin/python3.12 python3.13 python3.12 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        command -v "$c"; return
      fi
    fi
  done
}
PY="$(find_python || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "ERROR: Potřebuju Python 3.12+ (growattServer). Nainstaluj: brew install python@3.13" >&2
  exit 1
fi
echo "Python: $PY ($("$PY" -V 2>&1))"

# ── Adresáře a konfigurace ───────────────────────────────────────────────────
say "Adresáře"
mkdir -p "$HD_HOME/data" "$HD_HOME/state" "$LOGS" "$CONFIG_DIR" "$AGENTS"
chmod 700 "$HD_HOME/state" "$CONFIG_DIR"
echo "data:    $HD_HOME/data"
echo "state:   $HD_HOME/state   (tokeny, zámky, stav běhů)"
echo "logy:    $LOGS"
echo "config:  $ENV_FILE"

NEW_ENV=0
if [ ! -f "$ENV_FILE" ]; then
  (umask 077 && cp "$TEMPLATES/env.example" "$ENV_FILE")
  NEW_ENV=1
fi
chmod 600 "$ENV_FILE"

# ── venv a závislosti ────────────────────────────────────────────────────────
say "Virtuální prostředí a závislosti"
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"
# Cesta obsahuje mezeru („Application Support") → pip volat přes -m, ne přes shebang
"$VPY" -m pip install --quiet --upgrade pip
for i in 1 2 3 4; do
  # PyPI občas vrátí přechodné "versions: none" (stejně jako ve workflowech)
  "$VPY" -m pip install --quiet --upgrade -r "$TEMPLATES/requirements.txt" && break
  [ "$i" -eq 4 ] && { echo "ERROR: pip install selhal" >&2; exit 1; }
  echo "pip install selhal (pokus $i), čekám…"; sleep $((i * 15))
done
"$VPY" -c 'import requests, cryptography, bs4, icalendar, recurring_ical_events, growattServer, zoneinfo; zoneinfo.ZoneInfo("Europe/Prague")'
echo "OK"

# ── Plisty ───────────────────────────────────────────────────────────────────
CLOUDFLARED="${CLOUDFLARED:-$(command -v cloudflared || true)}"
[ -z "$CLOUDFLARED" ] && [ -x /opt/homebrew/bin/cloudflared ] && CLOUDFLARED=/opt/homebrew/bin/cloudflared

# Hodnoty pro sed: escapovat znaky, které mají v náhradě význam (\ & |)
sed_escape() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

render() {  # render <šablona> <cíl>
  sed -e "s|__PYTHON__|$(sed_escape "$VPY")|g" \
      -e "s|__REPO__|$(sed_escape "$REPO")|g" \
      -e "s|__HD_HOME__|$(sed_escape "$HD_HOME")|g" \
      -e "s|__ENV_FILE__|$(sed_escape "$ENV_FILE")|g" \
      -e "s|__LOGS__|$(sed_escape "$LOGS")|g" \
      -e "s|__PORT__|$(sed_escape "$PORT")|g" \
      -e "s|__CLOUDFLARED__|$(sed_escape "$CLOUDFLARED")|g" \
      -e "s|__CF_CONFIG__|$(sed_escape "$CF_CONFIG")|g" \
      "$1" > "$2.tmp"
  plutil -lint "$2.tmp" >/dev/null
  mv "$2.tmp" "$2"
}

AGENT_NAMES=(runner server)
if [ -n "$CLOUDFLARED" ] && [ -f "$CF_CONFIG" ]; then
  AGENT_NAMES+=(cloudflared)
else
  warn "cloudflared se zatím neinstaluje (chybí binárka nebo $CF_CONFIG) — viz HOMESERVER.md, krok Tunel."
fi

say "LaunchAgents"
for name in "${AGENT_NAMES[@]}"; do
  label="local.home-dashboard.$name"
  render "$TEMPLATES/$label.plist" "$AGENTS/$label.plist"
  echo "$AGENTS/$label.plist"
done

if [ "$NEW_ENV" -eq 1 ]; then
  cat <<EOF

Vytvořil jsem $ENV_FILE ze vzoru (práva 600).
Vyplň v něm přihlašovací údaje a spusť install.sh znovu — teprve pak se
agenti spustí (bez konfigurace by fetch skripty jen padaly).
EOF
  exit 0
fi
if [ "$START" -eq 0 ]; then
  echo; echo "--no-start: agenti připraveni, nespouštím."
  exit 0
fi

# ── Spuštění (bootout → bootstrap = restart s novým plistem) ─────────────────
say "Spouštím agenty"
for name in "${AGENT_NAMES[@]}"; do
  label="local.home-dashboard.$name"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  # Dříve ručně vypnutý agent (launchctl disable) by bootstrap odmítl
  launchctl enable "$DOMAIN/$label"
  # bootout je asynchronní; bootstrap hned po něm občas skončí chybou 5
  for i in 1 2 3 4 5; do
    launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist" 2>/dev/null && break
    [ "$i" -eq 5 ] && { echo "ERROR: launchctl bootstrap $label selhal" >&2; exit 1; }
    sleep 1
  done
  echo "✓ $label"
done

say "Kontrola"
sleep 3
if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then
  echo "✓ server odpovídá na http://127.0.0.1:$PORT"
else
  warn "server neodpovídá — viz $LOGS/server.log a server.launchd.log"
fi
cat <<EOF

Hotovo. Runner po startu dohání chybějící/zastaralá data (prvních pár minut).
  stav:  curl -s http://127.0.0.1:$PORT/healthz | python3 -m json.tool
  data:  curl -s http://127.0.0.1:$PORT/data/weather.json | head
  logy:  tail -f "$LOGS/runner.log"
  ručně: "$VPY" "$REPO/scripts/local/run.py" once all
EOF
