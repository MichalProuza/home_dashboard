#!/usr/bin/env bash
# Publikuje JSON soubory z data/ do větve "data" (vytvoří ji, pokud neexistuje).
# Botí commity tak nezaplavují historii větve main.
#
# Použití: bash scripts/publish_data.sh "commit message" soubor1.json [soubor2.json ...]
# Soubory se čtou z data/<název> a ukládají do kořene větve "data".
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Použití: $0 \"commit message\" soubor1.json [soubor2.json ...]" >&2
  exit 1
fi

MSG="$1"; shift

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

# Bootstrap: pokud větev data neexistuje, založ ji prázdným commitem
if ! git fetch origin data 2>/dev/null; then
  echo "INFO: Větev data neexistuje, vytvářím…"
  EMPTY_COMMIT=$(git commit-tree "$(git mktree </dev/null)" -m "chore: init větve data")
  git push origin "$EMPTY_COMMIT:refs/heads/data"
  git fetch origin data
fi

WORKTREE="$(mktemp -d)/data-branch"
git worktree add --detach "$WORKTREE" origin/data

COPIED=()
for name in "$@"; do
  if [ ! -f "data/$name" ]; then
    echo "WARN: data/$name neexistuje, přeskočeno"
    continue
  fi
  cp "data/$name" "$WORKTREE/$name"
  COPIED+=("$name")
done

if [ "${#COPIED[@]}" -eq 0 ]; then
  echo "WARN: Žádné soubory k publikování."
  exit 0
fi

cd "$WORKTREE"
git add "${COPIED[@]}"
if git diff --cached --quiet; then
  echo "INFO: Žádné změny k publikování."
  exit 0
fi
git commit -m "$MSG"

# Push s retry – plánovač i tlačítko „obnovit" spouští 5–8 workflowů naráz,
# takže pushují na data ve stejnou chvíli. Bez náhodného odstupu se srazí
# při každém pokusu znovu → čekat náhodně 1–(2×pokus) s a pak rebase.
MAX_ATTEMPTS=8
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  if git push origin HEAD:refs/heads/data; then
    echo "✓ Publikováno do větve data (${COPIED[*]})"
    exit 0
  fi
  [ "$attempt" -eq "$MAX_ATTEMPTS" ] && break
  delay=$(( RANDOM % (2 * attempt) + 1 ))
  echo "WARN: Push selhal (pokus $attempt/$MAX_ATTEMPTS), za ${delay} s rebase a znovu…"
  sleep "$delay"
  git pull --rebase origin data
done
echo "ERROR: Push do větve data se nepodařil ani po $MAX_ATTEMPTS pokusech." >&2
exit 1
