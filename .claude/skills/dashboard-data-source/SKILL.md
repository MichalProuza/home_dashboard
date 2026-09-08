---
name: dashboard-data-source
description: End-to-end recipe for adding a new data source to the dashboard or changing an existing one — the Python fetch script, the GitHub Actions workflow, the seed JSON, the frontend sections and the CLAUDE.md entry. Use this whenever the user wants the dashboard to show data it does not collect yet ("přidej na dashboard…", "chtěl bych vidět…", "šlo by stahovat…"), when adding or reworking a scripts/fetch_*.py, when a source needs an OAuth token that rotates, or when a source needs history kept across runs. Six pieces have to change together and the ones forgotten most often are the seed JSON and the kiosk sections.
---

# Adding or changing a data source

## The six pieces

A data source is only finished when all six exist. The ones skipped most often
are #3 (the page shows "nedostupné" for anyone testing locally or before the
first workflow run) and #5 for the kiosks (the wall display silently misses the
new value):

1. `scripts/fetch_<name>.py` — fetches and writes `data/<name>.json`
2. `.github/workflows/<name>.yml` — schedule, secrets, publish step
3. `data/<name>.json` — a committed seed/fallback on `main`
4. Any new GitHub Secrets — and their row in the `CLAUDE.md` secrets table
5. The frontend sections — see the `dashboard-frontend` skill for which of the
   three files, and the parity checker
6. `CLAUDE.md` — repository layout, sections table, workflow table, JSON schema

## 1. The fetch script

Conventions every existing script follows, because each one solves a problem
that already bit this repo:

```python
#!/usr/bin/env python3
"""Co skript dělá + jaké GitHub Secrets potřebuje."""   # docstring in Czech

API_KEY = os.environ.get("MYSRC_API_KEY", "")
# Workflow předává env vždy — i prázdné, když secret chybí. Proto `or`,
# ne default v get(): prázdný string by přebil výchozí hodnotu.
LIST    = os.environ.get("MYSRC_LIST") or "Vranov"

if not API_KEY:
    print("ERROR: Chybí MYSRC_API_KEY.")
    sys.exit(1)

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "mysrc.json"
```

- **`or` instead of a `get()` default for optional env vars.** GitHub Actions
  passes every declared `env:` key, empty string included, when the secret is
  missing. `os.environ.get("X", "default")` therefore yields `""`, not the
  default. This was a real bug (`fix: prázdné env MSTODO_TENANT/LIST nesmí
  přebít výchozí hodnoty`).
- **Strip secrets before use.** A pasted secret often carries a trailing
  newline; sending it in a header produces a baffling 401/403. Existing code
  trims (`chore: oříznout GROWATT_API_TOKEN`).
- **Always write the JSON, even on failure.** Every output has the envelope
  `{"updated": "<ISO UTC>", "error": null|"…", …}`. The frontend renders stored
  data plus a staleness warning when `error` is set, so a failed run must not
  leave the file absent or truncated.
- **Never overwrite good data with nothing.** If the fetch fails, keep the
  previously stored payload and only set `error`. `fetch_school_calendar.py`
  does this, and it is why a school-website outage does not blank the section.
- **`safe_float(val, default=0.0)`** for every untrusted numeric field.
- **Exit 0 even when `error` is set**, so the publish step still runs and the
  frontend can show the error. Exit 1 only for a missing-credentials
  misconfiguration, where there is nothing worth publishing.

Validate the shape before committing:

```bash
python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py
```

It checks every `data/*.json` for the envelope, valid ISO `updated`, JSON
validity and the per-source keys the frontends actually read.

Run the script locally with real credentials whenever you can — there is no
test suite, and a local run is far cheaper than a workflow round-trip:

```bash
MYSRC_API_KEY=... python3 scripts/fetch_mysrc.py && cat data/mysrc.json
```

## 2. The workflow

Copy `weather.yml` for a plain source. The pieces that matter:

```yaml
on:
  schedule:
    - cron: '*/30 * * * *'
  workflow_dispatch:          # vždy — bez toho se to nedá ručně ověřit
jobs:
  fetch:
    runs-on: ubuntu-latest
    permissions:
      contents: write         # publish_data.sh pushuje do větve data
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        # PyPI občas vrátí přechodné "versions: none" → opakovat s odstupem
        run: |
          for i in 1 2 3 4; do
            pip install requests && break
            echo "pip install selhal (pokus $i), čekám…"; sleep $((i*15))
          done
          python -c "import requests"
      - name: Fetch
        env:
          MYSRC_API_KEY: ${{ secrets.MYSRC_API_KEY }}
        run: python scripts/fetch_mysrc.py
      - name: Publish data
        run: 'bash scripts/publish_data.sh "chore: update mysrc data" mysrc.json'
```

- **Always include `workflow_dispatch`.** Without it you cannot test the thing
  you just wrote except by waiting for the cron.
- **Quote the publish step in single quotes.** The commit message contains a
  colon (`chore: …`), which unquoted YAML parses as a mapping
  (`fix: YAML quoting kroku Publish data`).
- **Keep the pip retry loop.** PyPI's transient failures caused real gaps in the
  data (`fix: opakovat pip install při přechodné chybě PyPI`).
- **Python version.** 3.11 for most; `growatt.yml` needs 3.12 because
  `growattServer` 2.x uses PEP 695 syntax. Pin deliberately.
- Never commit generated JSON to `main` — `publish_data.sh` pushes to the `data`
  branch, which is what keeps `main`'s history free of bot commits. The script
  bootstraps the branch, copies from `data/<name>`, and retries the push with a
  rebase when a concurrent workflow got there first.

### If the source keeps history (a graph)

`growatt.json` (`soc`) and `netatmo.json` (`noise`) carry 24 h series. The script
appends to whatever is already there, so the workflow has to **restore the
previous file first** — otherwise every run starts from an empty series:

```yaml
      - name: Load previous data (historie)
        run: |
          git fetch origin data 2>/dev/null || true
          git show origin/data:mysrc.json > data/mysrc.json 2>/dev/null || true
```

The `|| true` matters: on the very first run the branch or file does not exist,
and the workflow must not fail there. Trim the series to 24 h in the script,
otherwise the file grows without bound.

### If the source uses a rotating refresh token

Netatmo and Microsoft both invalidate the old refresh token on every use, so the
current one lives Fernet-encrypted on the `data` branch and the secret is only a
bootstrap seed. Copy `netatmo.yml` or `mstodo.yml` wholesale and keep all three
protections — each exists because of a real outage:

```yaml
concurrency:                  # dva běhy najednou si token navzájem zneplatní
  group: mysrc-data
  cancel-in-progress: false
```

```yaml
      - name: Load stored refresh token
        run: |
          git fetch origin data 2>/dev/null || true
          git show origin/data:mysrc_token.enc > data/mysrc_token.enc 2>/dev/null || true
```

```yaml
      - name: Publish data
        run: 'bash scripts/publish_data.sh "chore: update mysrc data" mysrc.json mysrc_token.enc'
```

In the script:

- Try the **stored** token first, then the seed secret — in that order.
- **Never write an empty token file.** A failed load that overwrites a valid
  stored token bricks the source until someone reissues the seed by hand
  (`fix: nemazat platný uložený Netatmo token prázdným souborem`).
- Encrypt with `Fernet(base64.urlsafe_b64encode(hashlib.sha256(KEY.encode()).digest()))`
  — the `data` branch is **public**, so an unencrypted token there is a leaked
  credential.

Remember what publishing means: the `data` branch is public (the repo stays
public because Actions minutes are free there — see `CLOUDFLARE.md`). Anything
the script writes is world-readable. Keep tokens read-only in scope, and tell
the user plainly if a new source would publish something they may not want
public.

## 3–6. The rest

- **Seed JSON on `main`** — a realistic, valid `data/<name>.json`. It is the
  local-development fallback and the pre-first-run fallback.
- **Secrets** — created by the user in GitHub, not by you. List exactly which
  ones you need and where to generate them, and add the `CLAUDE.md` row.
- **Frontend** — the `dashboard-frontend` skill.
- **CLAUDE.md** — four places: repository layout tree, the sections table, the
  workflows table, and a JSON schema block. `CLAUDE.md` is the map every future
  session starts from, so a source missing from it is a source the next session
  will not know exists.

Then commit, push and PR per the `dashboard-ship` skill.
