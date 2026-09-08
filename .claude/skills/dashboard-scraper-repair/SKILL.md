---
name: dashboard-scraper-repair
description: Repair the HTML scrapers for the school lunch menu (fetch_school_menu.py) and the school event plan (fetch_school_calendar.py) when the school website changes its markup. Use this when the menu or "Plán akcí ZŠ" section shows nothing, stale content, the wrong week or the wrong day, when the user says "jídelníček nejde", "nezobrazuje se menu", "špatný týden", or when either script reports a parse error. These break every few months because the source site is not an API and nobody announces the change.
---

# Repairing the school scrapers

## Why these break and what that means

`fetch_school_menu.py` and `fetch_school_calendar.py` parse a school website
with BeautifulSoup. There is no API and no contract: someone edits the page in a
CMS, the markup shifts, and the scraper quietly stops matching. It has already
happened twice for the menu alone (`fix: opravit parsování jídelníčku MŠ (den
v <strong> místo <b>)`, `fix: stahovat jídelníček MŠ i o víkendu`).

So when you repair one, assume the markup will move again. Prefer a tolerant
match over an exact one — the existing code already does this in the place that
broke:

```python
bold = el.find("b") or el.find("strong")     # CMS střídá <b> a <strong>
```

That line is the model for the whole file: accept both spellings, search by
visible Czech text rather than by generated ids where you can, and don't anchor
on layout wrappers that a CMS regenerates.

## Diagnose against the live page

Never guess from the script alone — fetch the page and look:

```bash
# co skript vidí
python3 - <<'PY'
import requests
from bs4 import BeautifulSoup
url = "<URL ze skriptu>"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
print(r.status_code, len(r.text))
soup = BeautifulSoup(r.text, "html.parser")
print(soup.find(id="pane_220_1") and "pane nalezen" or "PANE CHYBÍ ← struktura se změnila")
PY
```

Then work down the chain of assumptions the script makes, checking each:

1. **HTTP** — did the URL move, or is a redirect/403 being returned? The URL was
   corrected once already (`fix: opravit parsování… current page urls`).
2. **The container** — `fetch_school_menu.py` anchors on `id="pane_220_1"`. A
   CMS-generated id like that is the most fragile assumption in the file; if it
   is gone, find the new container by its visible heading text instead.
3. **The day headings** — `h2` elements, with the day name in `<b>` *or*
   `<strong>`. This is what broke in August.
4. **The meal items** — `li` elements under each day.
5. **The week label** — the `week` field the frontend displays.

Run the script locally after each change; it needs no credentials:

```bash
python3 scripts/fetch_school_menu.py && cat data/school_menu.json
python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py --live data/school_menu.json
```

Check the parsed Czech text actually reads like a menu — a scraper can produce a
perfectly-shaped JSON full of navigation labels. That is the failure mode a
schema check cannot catch, so read the values.

## Keep the previous data on failure

`fetch_school_calendar.py` retains the stored `events` and sets `error` when a
scrape fails, and the frontend then renders them with a staleness warning. Keep
that behaviour in any repair: a school-website outage should degrade to "old but
labelled" rather than an empty section on the wall. Never let a failed parse
write an empty list over good data.

## Weekend and time-of-day logic

Two subtleties bite here, both already fixed once — reproduce them, don't
rediscover them:

- **The school publishes next week's menu over the weekend**, so
  `school_menu.yml` runs daily rather than on weekdays only
  (`fix: stahovat jídelníček MŠ i o víkendu`). A weekday-only cron means Monday
  morning shows last week.
- **After 16:00 the frontend shows the next day's menu**, since the current
  day's lunch is over (`feat: jídelníček po 16:00 ukáže další den`). That is
  frontend logic, not scraper logic — if the wrong day is displayed while the
  JSON is correct, the bug is in the frontend and there are three files to check
  (see the `dashboard-frontend` skill).

Distinguishing "wrong data" from "wrong day chosen from correct data" is the
first question to answer, and reading the published JSON answers it.

## If the site becomes unscrapeable

If the page moves to a JS-rendered layout, scraping it from a GitHub runner with
`requests` stops being possible. Say so plainly rather than building something
fragile — the honest options are a different source URL (some CMSes expose a
printable or RSS variant), or dropping the section. Don't add a headless browser
to this repo; it has no build step and the workflows are deliberately tiny.
