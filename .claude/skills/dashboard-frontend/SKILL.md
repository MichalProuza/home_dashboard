---
name: dashboard-frontend
description: How to add or change a dashboard section across the three frontends (index.html, kiosk.html, kiosk-ios27.html) without leaving one behind. Use this whenever the user asks to add, move, restyle or extend anything visible on the dashboard — a new value, a graph, a section, a layout tweak, a night-mode change — or says something like "přidej do počasí…", "zobraz taky…", "uprav kiosk". Also use when a value shows correctly on the phone dashboard but is missing from the wall iPad, since that is the signature of a change landed in only one of the three files.
---

# Frontend changes across three files

## The trap this skill exists to avoid

There is no build step and no shared component layer: the same section is
implemented **three times**, in three files with three different styles.

| File | Audience | JS style | Data |
|------|----------|----------|------|
| `index.html` | phone/desktop browser | modern ES, `async/await`, `Promise.allSettled` | data branch + live Open-Meteo + live MS Graph (OAuth/PKCE) |
| `kiosk.html` | wall iPad Air 1 (Safari 12) | ES2017, `var`, `.then()` | data-branch JSON only |
| `kiosk-ios27.html` | wall iPad, "Liquid Glass" look | ES2017, `var`, `.then()` | same as `kiosk.html` |

The repo history is full of follow-up commits doing the same feature again in
the next file (rain over 24 h, then rain over 1 h, then the other kiosk; the
10:00/14:00 forecast row; the To Do section). Each of those was an extra PR and
a day of the wall iPad showing stale information.

So before you start: decide explicitly which of the three files the change
belongs in, and say so in your reply. "All three" is the usual answer for a new
value or data source. "Only the kiosks" is right for wall-display layout and
night dimming. "Only `index.html`" is right for interactive things the kiosks
cannot do — the browser OAuth flow, `tasks.html` links, buttons.

Then verify you actually did it:

```bash
bash .claude/skills/dashboard-frontend/scripts/check_parity.sh
```

With no arguments it prints a matrix of every `data/*.json` source against the
three frontends, so a source present in one file and missing from another is
immediately visible. Pass keywords (`check_parity.sh sum_rain w-rain`) to check
a specific field or element id you just added. Read the gaps as questions, not
verdicts — some asymmetries are intentional and listed above.

## Anatomy of a section

### index.html

```html
<section>
  <div class="section-label">Název sekce</div>
  <div id="mysrc-content">načítám…</div>
</section>
```

```js
async function fetchMysrc() {
  const el = document.getElementById('mysrc-content');
  try {
    const j = await fetchDataJson(MYSRC_JSON_URL);      // data branch → ./data/ fallback
    if (j.error) { /* show it, but still render stored data if present */ }
    el.innerHTML = `<div class="row">${esc(j.value)}</div>`;
  } catch (e) {
    el.textContent = 'nedostupné';
  }
}
```

Then add `fetchMysrc()` to the `Promise.allSettled([...])` list inside
`initAll()`. A section not wired in there renders "načítám…" forever, and
because `Promise.allSettled` swallows rejections, a section that throws fails
quietly without taking the others down — good for robustness, bad for noticing.

Non-negotiable helpers, all defined at the top of the script:

- `esc()` around **every** external string before it goes into `innerHTML`.
  Every value here comes from an API, an iCal feed or a scraped school website;
  `esc()` is the only thing between those and script injection into the page.
- `fetchDataJson(name)` for workflow-generated JSON — it handles the data-branch
  URL, the cache-buster and the `./data/` fallback.
- `fetchJson(url)` for a direct API call — it adds `cache: 'no-store'`, a 15 s
  timeout and an HTTP status check.

### kiosk.html / kiosk-ios27.html

Same shape, ES2017 style, and the fixed full-screen grid means your section has
to fit a **predetermined cell** — the kiosks deliberately never scroll, so a
section that grows past its cell pushes content off-screen on the wall instead
of adding a scrollbar. Check the grid definition before adding rows.

```js
function fetchMysrc() {
  var el = document.getElementById('mysrc-content');
  return fetchDataJson('mysrc.json').then(function (j) {
    el.innerHTML = '<div class="row">' + esc(j.value) + '</div>';
  }).catch(function () {
    el.textContent = 'nedostupné';
  });
}
```

**Every kiosk edit ends with the Safari 12 checker.** The `kiosk-safari12` skill
has the full ruleset and the reasoning; the short version is that one `?.` or
one flex `gap` silently kills the section or the whole script, and neither your
browser nor the checker's absence of complaints is proof — but the checker is
what catches the mistakes people actually make:

```bash
bash .claude/skills/kiosk-safari12/scripts/check_compat.sh
```

Night dimming lives only in the kiosks (`body.night`, toggled around 22:00–06:00
in the clock tick) and is implemented as a **dark theme, not a brightness
filter** — a filter was tried and reverted because it made the display muddy
rather than dim. So any new kiosk colour needs a `body.night` counterpart, or it
will glow at 3 a.m.

## Data source availability differs per file

Two sections do not read the same source everywhere, and getting this backwards
produces a section that works in the browser and stays empty on the wall:

- **Weather** — `index.html` calls Open-Meteo directly and falls back to
  `weather.json`; the kiosks read `weather.json` only. Open-Meteo blocks some
  ISP IP ranges, which is why the server-side copy exists at all.
- **Microsoft To Do** — `index.html` uses the live browser OAuth2/PKCE flow
  against Graph; the kiosks read `mstodo.json`, produced server-side by
  `fetch_mstodo.py`, precisely because Safari 12 on a wall display cannot do an
  interactive login.

## Hosting: two origins, one page

`DATA_BRANCH_BASE` is chosen by hostname in all three files:

```js
location.hostname.indexOf('github.io') !== -1
  ? 'https://raw.githubusercontent.com/MichalProuza/home_dashboard/data/'
  : '/api/data/';     // Cloudflare Pages Function, and localhost
```

The dashboard is served both from GitHub Pages and from
`dashboard.prouza.co.uk` behind Cloudflare Access, where a Pages Function reads
the data branch with a server-side token. If you add a new frontend file, it
needs this switch too — hardcoding the raw URL works on Pages and breaks the
Cloudflare deployment, and hardcoding `/api/data/` does the reverse.

## Finishing

CSS variables and typography are documented in `CLAUDE.md` (`--ink`, `--paper`,
Spectral for text, JetBrains Mono for data) — reuse them instead of inventing
colours, and note the kiosks have their own palettes including the night theme.
All UI text is Czech.

For the commit, PR and `CLAUDE.md` update, see the `dashboard-ship` skill.
