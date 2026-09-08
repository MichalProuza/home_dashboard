---
name: dashboard-actions-debug
description: Diagnose a failing or silently-empty GitHub Actions fetch workflow by reading run logs through the GitHub MCP tools instead of pushing diagnostic commits, plus the catalogue of gotchas that have already bitten this repo (trailing newline in a secret, empty env overriding a default, YAML colon quoting, transient PyPI failures, Python version, rotating-token concurrency). Use this whenever a dashboard section shows stale or missing data, when the user says a workflow "padá", "neběží", "nejde", when a fetch script works locally but fails in Actions, or when data/*.json on the data branch stops updating.
---

# Debugging the fetch workflows

## Read the logs, don't push probes

The history of this repo contains commits like `chore: dočasná diagnostika 403
u Growatt loginu`, `chore: dočasná diagnostika polí Growatt V1 API` and
`chore: dočasné ověření fetch_weather.py přes growatt workflow`, each followed
by a revert. That pattern — push a debug print, wait for the cron, read the
output, push a revert — costs several commits and a lot of waiting per bug, and
it leaves noise in `main`'s history.

You have the GitHub MCP tools, so read the actual logs instead:

```
mcp__github__actions_list      → recent runs for a workflow, with conclusions
mcp__github__get_job_logs      → the failing step's output (failed_only + tail)
mcp__github__actions_run_trigger → fire workflow_dispatch and watch this run
```

Load them with `ToolSearch` first (`select:mcp__github__actions_list,...`). Every
workflow here has `workflow_dispatch`, so you can trigger a real run on demand
rather than waiting for the schedule — that is the whole reason it is there.

Reach for a temporary diagnostic commit only when the logs genuinely cannot tell
you what an external API returned and you cannot reproduce it locally. If you do,
put the probe behind an existing `workflow_dispatch` run, keep it in one commit,
and remove it in the same PR.

## Read the failure correctly

The scripts are written to **succeed with `error` set** rather than crash, so
the interesting failures come in three shapes, and they need different places to
look:

| Symptom | Where to look |
|---------|---------------|
| Workflow red | `get_job_logs` on the failing step — usually deps, YAML, or a missing secret causing `sys.exit(1)` |
| Workflow green, section stale | The published JSON's `error` field on the `data` branch — the script caught the problem and reported it |
| Workflow green, JSON fine, section empty | Not a backend problem — see the `dashboard-frontend` and `kiosk-safari12` skills |

For the second shape, fetch the live file rather than trusting the seed in
`main`:

```bash
curl -s "https://raw.githubusercontent.com/MichalProuza/home_dashboard/data/netatmo.json" | head -40
python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py --live /tmp/netatmo.json
```

## The gotcha catalogue

Each of these has already caused an outage here. Check them before theorising:

**A secret with a trailing newline.** Pasting a token into the GitHub Secrets UI
easily captures a newline; it then corrupts an `Authorization` header and the
API answers 401/403 with no clue why. Scripts strip credentials for this reason
(`chore: oříznout GROWATT_API_TOKEN`). Suspect this whenever auth fails in
Actions but the identical token works locally.

**An empty env var overriding a default.** Actions passes every declared `env:`
key even when the secret is unset, so the value is `""`, and
`os.environ.get("X", "default")` returns `""` — not the default. Optional
settings must use `os.environ.get("X") or "default"`
(`fix: prázdné env MSTODO_TENANT/LIST nesmí přebít výchozí hodnoty`).

**Unquoted YAML with a colon.** `run: bash scripts/publish_data.sh "chore: update
x" x.json` parses as a mapping and fails obscurely. Wrap the whole `run:` value
in single quotes (`fix: YAML quoting kroku Publish data`).

**A transient PyPI failure.** `pip install` intermittently returns
"versions: none", which killed runs until the retry loop was added
(`fix: opakovat pip install při přechodné chybě PyPI`). If a run failed at the
install step, re-run before investigating — and if a workflow lacks the loop,
add it.

**The wrong Python version.** `growatt.yml` pins 3.12 because `growattServer`
2.x uses PEP 695 `type X = …` syntax that 3.11 cannot parse. A `SyntaxError`
inside a dependency means the runner's Python is too old, not that the package
is broken.

**A rotating refresh token invalidated by a concurrent run.** Netatmo and
Microsoft rotate the refresh token on use, so two overlapping runs destroy each
other's credentials. Both workflows carry `concurrency: {group: …,
cancel-in-progress: false}`. If such a source dies intermittently around
schedule boundaries, check that the group is still there.

**An empty token file wiping a valid stored token.** If loading the encrypted
token fails and the script writes an empty file anyway, the source is bricked
until the seed secret is reissued (`fix: nemazat platný uložený Netatmo token
prázdným souborem`). A rotating-token source that needs manual reseeding is
usually this.

**A lost history series.** `growatt.json`'s `soc` and `netatmo.json`'s `noise`
are appended across runs, so the workflow must restore the previous file from
the `data` branch first. A graph that never shows more than one point means the
restore step is missing or its `git show` is silently failing.

**A 403 from the upstream API.** Growatt started rejecting the login and
Open-Meteo blocks some ISP ranges — which is why the weather has a server-side
copy at all. When an API rejects the runner but works from home, the fix is
usually a different endpoint or auth method, not a retry.

## Recovering a source

If a rotating token cannot be refreshed at all, the recovery path is: the user
generates a fresh seed refresh token, updates the secret, and the next run
re-encrypts it onto the `data` branch. Note the Azure caveat for Microsoft:
tokens issued against an SPA redirect URI expire in 24 h, so the seed must be
generated against a "Mobile and desktop applications" registration to last
~90 days.

The `data` branch is disposable and can be deleted to reset its history — but
that also deletes `netatmo_token.enc` and `mstodo_token.enc`, so both sources
then need fresh seeds. Never suggest it casually; say what will be lost first.

## Secrets are the user's job

You cannot read or set GitHub Secrets. When a secret is missing or wrong, say
exactly which one, where it is generated (the tables in `CLAUDE.md` name the
portal for each), and what scope it needs — then stop, rather than working
around it.
