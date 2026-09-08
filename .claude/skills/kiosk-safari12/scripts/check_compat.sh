#!/usr/bin/env bash
# Hledá v kiosk*.html konstrukce, které Safari 12.1 (iPad Air 1, iOS 12.5) neumí.
#
# Safari 12 selhává tiše: jedna nepodporovaná CSS vlastnost zruší celý blok,
# jeden `?.` v JS shodí celý <script>. Tenhle skript je linter, ne parser —
# hlídá známé opakované chyby. Když nic nenajde a kiosk je přesto prázdný,
# hledej novou JS funkci (caniuse) a přidej si sem její vzor.
#
# Komentáře (HTML i JS) se ignorují, aby dokumentace typu "ŽÁDNÝ clamp()"
# nehlásila sama sebe.
#
# Použití: bash .claude/skills/kiosk-safari12/scripts/check_compat.sh [soubor…]
# Bez argumentů zkontroluje kiosk.html a kiosk-ios27.html.
# Exit 0 = čisté, 1 = nalezeny problémy.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

FILES=("$@")
if [ "${#FILES[@]}" -eq 0 ]; then
  FILES=()
  for f in kiosk.html kiosk-ios27.html; do
    [ -f "$f" ] && FILES+=("$f")
  done
fi
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "Žádné kiosk soubory k kontrole." >&2
  exit 1
fi

TMPDIR_C="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_C"' EXIT

# Vymaže obsah komentářů, ale zachová počet řádků (kvůli číslům řádků).
strip_comments() {
  awk '
    { line = $0 }
    {
      out = ""
      i = 1
      n = length(line)
      while (i <= n) {
        if (in_html) {
          p = index(substr(line, i), "-->")
          if (p == 0) { i = n + 1 } else { i += p + 2; in_html = 0 }
          continue
        }
        if (in_block) {
          p = index(substr(line, i), "*/")
          if (p == 0) { i = n + 1 } else { i += p + 1; in_block = 0 }
          continue
        }
        rest = substr(line, i)
        if (substr(rest, 1, 4) == "<!--") { in_html = 1; i += 4; continue }
        if (substr(rest, 1, 2) == "/*")   { in_block = 1; i += 2; continue }
        if (substr(rest, 1, 2) == "//")   { i = n + 1; continue }
        out = out substr(line, i, 1)
        i++
      }
      print out
    }
  ' "$1"
}

FOUND=0

# report <orig> <stripped> <regexp> <popis> <náhrada>
report() {
  local orig="$1" stripped="$2" re="$3" what="$4" fix="$5"
  local lines
  lines=$(grep -nE "$re" "$stripped" 2>/dev/null | cut -d: -f1 || true)
  [ -z "$lines" ] && return 0
  FOUND=1
  echo "  ✗ $what"
  while read -r n; do
    [ -z "$n" ] && continue
    printf '      %s: %s\n' "$n" "$(sed -n "${n}p" "$orig" | sed 's/^[[:space:]]*//')"
  done <<< "$lines"
  echo "      → $fix"
  echo
}

for file in "${FILES[@]}"; do
  echo "═══ $file ═══"
  BEFORE=$FOUND
  S="$TMPDIR_C/$(basename "$file").stripped"
  strip_comments "$file" > "$S"

  # ── CSS ────────────────────────────────────────────────────────────────────
  report "$file" "$S" '(^|[^-])(gap|row-gap|column-gap)[[:space:]]*:' \
    "CSS gap / row-gap / column-gap (Safari 14.1)" \
    "grid-gap u gridu, margin u flexu"
  report "$file" "$S" 'clamp\(' \
    "CSS clamp() (Safari 13.4)" \
    "jedna hodnota ve vmin/vw, případně media query"
  report "$file" "$S" '(^|[^-[:alnum:]])inset[[:space:]]*:' \
    "CSS inset shorthand (Safari 14.1)" \
    "top/right/bottom/left rozepsané"
  report "$file" "$S" 'aspect-ratio[[:space:]]*:' \
    "CSS aspect-ratio (Safari 15)" \
    "padding-ratio box nebo pevné vmin rozměry"
  report "$file" "$S" ':(is|where)\(' \
    "CSS :is() / :where() (Safari 14)" \
    "rozepsat selektory"
  # Konkrétní doložené selhání: var() ve stop-color gradientu se v Safari 12
  # neaplikuje → gradient zmizí. (fill/stroke na <text> v praxi fungují.)
  report "$file" "$S" 'stop-color="var\(' \
    "var() ve stop-color SVG gradientu (Safari 12 ho ignoruje)" \
    "barvu v gradientu napevno"

  if grep -qE '(^|[^-])backdrop-filter[[:space:]]*:' "$S" 2>/dev/null \
     && ! grep -q '\-webkit-backdrop-filter' "$S" 2>/dev/null; then
    FOUND=1
    echo "  ✗ backdrop-filter bez -webkit- varianty"
    grep -nE '(^|[^-])backdrop-filter[[:space:]]*:' "$S" | sed 's/^/      /'
    echo "      → přidat -webkit-backdrop-filter se stejnou hodnotou"
    echo
  fi

  # ── JavaScript (ES2018+) ───────────────────────────────────────────────────
  report "$file" "$S" '[^[:space:]?]\?\.[[:alpha:]_([]' \
    "optional chaining ?. (Safari 13.1) — shodí celý <script>" \
    "a && a.b && a.b.c"
  report "$file" "$S" '\?\?' \
    "nullish coalescing ?? / ??= (Safari 13.1) — shodí celý <script>" \
    "explicitní test na undefined/null, nebo ||"
  report "$file" "$S" '(\|\|=|&&=)' \
    "logical assignment ||= &&= (Safari 14)" \
    "if + přiřazení"
  report "$file" "$S" 'Promise\.allSettled' \
    "Promise.allSettled (Safari 13) — typicky zkopírované z index.html" \
    "Promise.all nad promisy, které mají vlastní .catch()"
  report "$file" "$S" 'Promise\.any' \
    "Promise.any (Safari 14)" \
    "ruční řetěz .then()/.catch()"
  report "$file" "$S" 'Object\.fromEntries' \
    "Object.fromEntries (Safari 12.1)" \
    "forEach smyčka plnící objekt"
  report "$file" "$S" '\.replaceAll\(' \
    "String.replaceAll (Safari 13.1)" \
    ".replace(/x/g, …)"
  report "$file" "$S" '\.matchAll\(' \
    "String.matchAll (Safari 13)" \
    "while ((m = re.exec(s)))"
  report "$file" "$S" '\.(flat|flatMap)\(' \
    "Array.flat / flatMap (Safari 12 / nespolehlivé)" \
    "concat.apply nebo reduce"
  report "$file" "$S" '\.at\(-?[0-9]' \
    "Array/String.at (Safari 15.4)" \
    "indexace [i] / [len-1]"
  report "$file" "$S" '(^|[^.[:alnum:]_])globalThis' \
    "globalThis (Safari 12.1)" \
    "window"
  report "$file" "$S" 'structuredClone' \
    "structuredClone (Safari 15.4)" \
    "JSON.parse(JSON.stringify(x))"
  report "$file" "$S" '[0-9]_[0-9]' \
    "numerický separátor 1_000 (Safari 13)" \
    "1000"
  report "$file" "$S" '\(\?<[=!]' \
    "regex lookbehind (Safari 16.4)" \
    "capture groups"
  report "$file" "$S" 'Intl\.(RelativeTimeFormat|ListFormat|DisplayNames)' \
    "Intl.RelativeTimeFormat / ListFormat / DisplayNames (Safari 14)" \
    "vlastní české formátování"
  report "$file" "$S" 'for[[:space:]]+await' \
    "for await…of (Safari 12)" \
    "řetěz .then()"

  # ── Datum ──────────────────────────────────────────────────────────────────
  # Safari 12 neumí ISO s víc než milisekundami — a přesně tak vypadá `updated`
  # v každém data/*.json. Hlásí jen parsování pole z JSONu, ne new Date(cislo).
  report "$file" "$S" '(Date\.parse\(|new Date\([^)]*\.(updated|date|due|dateTime|time)\b)' \
    "ISO datum z JSONu parsované mimo safeDate() (Safari 12 padá na mikrosekundách)" \
    "safeDate(iso); u YYYY-MM-DD pomocník na lokální půlnoc (Date.parse dá UTC)"

  [ "$FOUND" -eq "$BEFORE" ] && { echo "  ✓ čisté"; echo; }
done

if [ "$FOUND" -ne 0 ]; then
  echo "Nalezeny nekompatibility se Safari 12. Detaily a náhrady:"
  echo ".claude/skills/kiosk-safari12/SKILL.md"
  exit 1
fi
echo "Vše čisté pro Safari 12 / iPad Air 1."
