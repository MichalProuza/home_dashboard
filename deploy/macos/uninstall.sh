#!/usr/bin/env bash
# Odinstalace domácího serveru home_dashboard (zastaví a odebere launchd agenty).
#
# Použití:
#   bash deploy/macos/uninstall.sh          zastaví agenty, smaže plisty; data,
#                                           tokeny, venv, logy a konfigurace zůstanou
#   bash deploy/macos/uninstall.sh --purge  navíc smaže data, tokeny, venv a logy
#
# Konfiguraci se secrets (~/.config/home_dashboard/) a tunnel credentials
# (~/.cloudflared/) skript nikdy nemaže — to je ruční krok (HOMESERVER.md).
set -euo pipefail

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Neznámý přepínač: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: uninstall.sh je jen pro macOS." >&2
  exit 1
fi

HD_HOME="$HOME/Library/Application Support/home_dashboard"
LOGS="$HOME/Library/Logs/home_dashboard"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

for name in cloudflared server runner; do
  label="local.home-dashboard.$name"
  if launchctl print "$DOMAIN/$label" >/dev/null 2>&1; then
    launchctl bootout "$DOMAIN/$label" || true
    echo "✓ zastaven $label"
  fi
  if [ -f "$AGENTS/$label.plist" ]; then
    rm -f "$AGENTS/$label.plist"
    echo "✓ smazán $AGENTS/$label.plist"
  fi
done

if [ "$PURGE" -eq 1 ]; then
  rm -rf "$HD_HOME" "$LOGS"
  echo "✓ smazáno: $HD_HOME, $LOGS"
else
  echo "Data, tokeny a venv zůstávají v $HD_HOME (smazat: --purge)."
fi
echo "Konfigurace ~/.config/home_dashboard/ a ~/.cloudflared/ zůstávají — smaž ručně, pokud je už nepotřebuješ."
