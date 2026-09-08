#!/usr/bin/env bash
# Ukáže, které z tří frontendů (index.html, kiosk.html, kiosk-ios27.html)
# používají který datový zdroj — aby se nestalo, že feature přistane jen
# v jednom souboru a na zdi visí neúplný dashboard.
#
# Bez argumentů: matice všech data/*.json zdrojů × tři frontendy.
# S argumenty:   hledá zadané výrazy (pole v JSONu, id elementu, název funkce).
#
# Použití:
#   bash .claude/skills/dashboard-frontend/scripts/check_parity.sh
#   bash .claude/skills/dashboard-frontend/scripts/check_parity.sh sum_rain_8 w-rain-hours
#
# Mezery v matici NEJSOU automaticky chyba — počasí a Microsoft To Do mají
# v index.html jiný zdroj (živé API) než kiosky (JSON z větve data). Bere se
# to jako otázka k ověření, ne jako verdikt.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

FRONTENDS=(index.html kiosk.html kiosk-ios27.html)
for f in "${FRONTENDS[@]}"; do
  [ -f "$f" ] || { echo "CHYBÍ soubor $f" >&2; exit 1; }
done

mark() {  # mark <soubor> <regexp>
  if grep -qF -- "$2" "$1" 2>/dev/null; then printf '   ✓   '; else printf '   —   '; fi
}

header() {
  printf '%-26s %s\n' "$1" "index   kiosk   ios27"
  printf '%-26s %s\n' "──────────────────────────" "─────────────────────────"
}

if [ "$#" -eq 0 ]; then
  echo "Datové zdroje × frontendy"
  echo
  header "zdroj"
  for path in data/*.json; do
    name=$(basename "$path")
    printf '%-26s' "$name"
    for f in "${FRONTENDS[@]}"; do mark "$f" "$name"; done
    echo
  done
  echo
  echo "Očekávané rozdíly:"
  echo "  weather.json — index.html volá Open-Meteo přímo, JSON je jen záloha"
  echo "  mstodo.json  — index.html má živý OAuth/PKCE na MS Graph, kiosky čtou JSON"
  echo
  echo "Fetch funkce:"
  echo
  header "funkce"
  # Sjednocení názvů fetch* funkcí ze všech tří souborů
  FUNCS=$(grep -ohE 'function[[:space:]]+(fetch|render)[A-Za-z0-9_]+' "${FRONTENDS[@]}" \
          | awk '{print $2}' | sort -u)
  while read -r fn; do
    [ -z "$fn" ] && continue
    printf '%-26s' "$fn"
    for f in "${FRONTENDS[@]}"; do mark "$f" "function $fn"; done
    echo
  done <<< "$FUNCS"
  echo
  echo "Tip: 'check_parity.sh <pole|id|název>' zkontroluje konkrétní novinku."
  exit 0
fi

echo "Hledané výrazy × frontendy"
echo
header "výraz"
MISSING=0
for term in "$@"; do
  printf '%-26s' "$term"
  hits=0
  for f in "${FRONTENDS[@]}"; do
    if grep -qF -- "$term" "$f" 2>/dev/null; then printf '   ✓   '; hits=$((hits+1))
    else printf '   —   '; fi
  done
  if [ "$hits" -gt 0 ] && [ "$hits" -lt 3 ]; then printf '  ← jen %s/3' "$hits"; MISSING=1; fi
  echo
done
echo
if [ "$MISSING" -ne 0 ]; then
  echo "Něco je jen v části frontendů. Když to tak má být (živé API v index.html,"
  echo "layout jen v kioscích), je to v pořádku — jinak doplň zbytek."
fi
