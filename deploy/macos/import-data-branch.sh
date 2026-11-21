#!/usr/bin/env bash
# Jednorázově převezme soubory z větve "data" do lokálních adresářů domácího
# serveru — aby po přechodu navázala historie (graf SOC Growatt) a zálohy
# jídelníčku / akcí ZŠ. Spouští se z klonu repa na Macu. Viz HOMESERVER.md.
#
# Použití:
#   bash deploy/macos/import-data-branch.sh            *.json, jen chybějící lokálně
#   bash deploy/macos/import-data-branch.sh --force    *.json, přepsat i existující
#   bash deploy/macos/import-data-branch.sh --tokens   navíc *_token.enc do state/
#
# --tokens jen při převzetí rotujícího tokenu v okamžiku přepnutí (workflow
# netatmo.yml / mstodo.yml už NESMÍ běžet) a se STEJNÝM *_TOKEN_KEY jako
# v GitHub Secrets — jinak si Mac a Actions token navzájem zneplatní.
set -euo pipefail

FORCE=0; TOKENS=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --tokens) TOKENS=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Neznámý přepínač: $arg" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
# Stejné výchozí umístění jako scripts/hd_common.py (HD_HOME přebije)
if [ -z "${HD_HOME:-}" ]; then
  if [ "$(uname -s)" = "Darwin" ]; then
    HD_HOME="$HOME/Library/Application Support/home_dashboard"
  else
    HD_HOME="$HOME/.local/share/home_dashboard"
  fi
fi
DATA="$HD_HOME/data"; STATE="$HD_HOME/state"
mkdir -p "$DATA" "$STATE"; chmod 700 "$STATE"

cd "$REPO"
git fetch --quiet origin data
for f in $(git ls-tree --name-only origin/data); do
  case "$f" in
    *.json) dest="$DATA/$f"; mode=644 ;;
    *_token.enc) [ "$TOKENS" -eq 1 ] || continue; dest="$STATE/$f"; mode=600 ;;
    *) continue ;;
  esac
  if [ -e "$dest" ] && [ "$FORCE" -eq 0 ] && [ "${f%.enc}" = "$f" ]; then
    echo "· $f existuje, přeskočeno (--force přepíše)"
    continue
  fi
  # Zápis atomicky: dočasný soubor ve stejném adresáři + mv
  tmp="$(mktemp "$(dirname "$dest")/.$f.XXXXXX")"
  git show "origin/data:$f" > "$tmp"
  chmod "$mode" "$tmp"
  mv -f "$tmp" "$dest"
  echo "✓ $f → $dest"
done
