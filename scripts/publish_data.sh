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

# Push s retry – jiný workflow mohl mezitím pushnout
for attempt in 1 2 3; do
  if git push origin HEAD:refs/heads/data; then
    echo "✓ Publikováno do větve data (${COPIED[*]})"
    exit 0
  fi
  echo "WARN: Push selhal (pokus $attempt), zkouším rebase…"
  git pull --rebase origin data
done
git push origin HEAD:refs/heads/data
echo "✓ Publikováno do větve data (${COPIED[*]})"
