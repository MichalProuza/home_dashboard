---
name: dashboard-ship
description: Finish a home_dashboard change correctly — Czech Conventional Commits, the right branch, the CLAUDE.md sync, and the pre-commit checks (kiosk Safari 12 linter, JSON validator, frontend parity). Use this before committing or opening a PR in this repo, whenever the user says "commit", "pushni", "hotovo", "udělej PR", or when you have finished editing and are about to wrap up. The step forgotten most often is updating CLAUDE.md, which is the map every future session starts from.
---

# Shipping a change

## Check before you commit

There is no test suite and no CI on `main`, so these three commands are the
entire safety net. Run the ones your change touches:

```bash
# 1. kiosk*.html edited → Safari 12 / iPad Air 1 (silent failures)
bash .claude/skills/kiosk-safari12/scripts/check_compat.sh

# 2. data/*.json or a fetch script edited → envelope + required keys
python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py

# 3. a new value or section → present in all the frontends it should be
bash .claude/skills/dashboard-frontend/scripts/check_parity.sh
```

If a Python script changed, run it locally with real env vars too — a workflow
round-trip is the slowest possible way to find a typo.

## Update CLAUDE.md in the same commit

`CLAUDE.md` is how the next session (and the next you) learns what this repo
contains. It is detailed and it is trusted, so a stale line there is worse than
a missing one — it actively misleads. Update whichever of these your change
touched:

- the repository-layout tree (new file)
- the dashboard-sections table (new section, changed data source)
- the configuration constants and the **secrets table** (new secret)
- the workflows table (new or rescheduled workflow)
- the JSON-schemas section (new or changed field)
- the kiosk file descriptions (changed compatibility constraints)

Doing it in the same commit as the change is what keeps it honest; a follow-up
"docs:" commit is how drift starts. This repo has needed
`docs: aktualizovat CLAUDE.md podle aktuálního stavu repozitáře` twice.

## Commit messages: Conventional Commits, in Czech

Everything user-facing here is Czech — UI text, Python comments, error messages,
commit messages. Keep the type prefix in English and the subject in Czech,
imperative, no trailing period:

```
feat: přidat sekci srážek do kiosku
fix: opravit parsování jídelníčku MŠ (den v <strong> místo <b>)
docs: aktualizovat CLAUDE.md podle aktuálního stavu repozitáře
chore: odstranit dočasné ověření počasí z growatt workflow
revert: vrátit index.html na původní verzi
```

Use `chore:` for bot commits on the `data` branch only. Explain *why* in the
body when the reason isn't obvious from the diff — the "why" comments in these
scripts are load-bearing precisely because the reasons are unguessable
(a trailing newline in a secret, an empty env var, an A7 GPU).

## Branch and push

Work on the branch assigned for the session, never on `main` directly:

```bash
git push -u origin <branch>
```

Retry a network failure up to four times with backoff (2s, 4s, 8s, 16s). Open a
pull request only when the user asks for one — the repo's own history is
PR-based, but that is the user's call, not an automatic step.

## Don't commit generated data to main

`data/*.json` on `main` are **seed/fallback files only**. Live data lives on the
`data` branch, published by `scripts/publish_data.sh`, because bot commits used
to flood `main`'s history. If a local script run has updated `data/*.json` as a
side effect of testing, leave those changes out of the commit unless you are
deliberately changing the seed:

```bash
git status --short data/          # zkontroluj, co se do commitu chystá
git checkout -- data/             # zahoď testovací výstupy
```
