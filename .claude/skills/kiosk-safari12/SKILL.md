---
name: kiosk-safari12
description: Safari 12 / iPad Air 1 compatibility rules and an automated checker for kiosk.html and kiosk-ios27.html. Use this whenever you edit, add CSS to, or add JavaScript to either kiosk file, when a kiosk section renders blank or unstyled on the wall iPad while looking fine in a desktop browser, or when the user says the kiosk "nefunguje", "je rozbitý", "nezobrazuje se" or reports a problem visible only on the old iPad. Also use before committing any kiosk change — silent Safari 12 parse failures are the single most common regression in this repo, and desktop Chrome will never reveal them.
---

# Kiosk compatibility: Safari 12 / iPad Air 1

## Why this matters more than it looks

`kiosk.html` and `kiosk-ios27.html` run on an **iPad Air 1 stuck at iOS 12.5.x
(Safari 12.1)**. That browser fails *silently*:

- One unsupported CSS property → the whole declaration block is dropped, the
  layout collapses, no error anywhere.
- One `?.` or `??` anywhere in the script → **the entire `<script>` fails to
  parse** and every section stays at "načítám…" forever.

The device cannot be debugged comfortably, and Chrome on the desktop happily
renders everything, so a broken kiosk is usually only discovered days later by
the person looking at the wall. That is why this repo has already spent whole
PRs on nothing but restoring Safari 12 compatibility (`fix: zajistit
kompatibilitu kiosk-ios27.html se Safari 12`). Treat the checker below as a
required step, not an optional nicety.

## Run the checker

After any edit to a kiosk file, before committing:

```bash
bash .claude/skills/kiosk-safari12/scripts/check_compat.sh
```

It greps both kiosk files for constructs Safari 12.1 cannot handle and exits
non-zero on findings. Findings are line-numbered, so fix them in place. Note it
is a linter, not a parser: it catches the known repeat offenders, not everything.
If it reports nothing but the kiosk is still blank on the iPad, the cause is
almost always a *new* JS feature it doesn't know about yet — check
caniuse for anything you used, then add the pattern to the script so the next
change is covered too.

## The rules

`index.html` is exempt from all of this — it runs in a modern browser and may
use anything. These constraints apply **only** to `kiosk.html` and
`kiosk-ios27.html`.

### CSS: use these instead

| Don't use | Since | Use instead |
|-----------|-------|-------------|
| `gap` / `row-gap` / `column-gap` in flexbox | Safari 14.1 | `margin` on the children |
| `gap` in grid | Safari 14.1 | `grid-gap` (the old spelling still works) |
| `clamp()` | Safari 13.4 | a single `vmin`/`vw` value, or a media query |
| `inset:` shorthand | Safari 14.1 | `top/right/bottom/left` written out |
| `aspect-ratio` | Safari 15 | padding-ratio box, or fixed `vmin` sizes |
| `:is()` / `:where()` | Safari 14 | write the selectors out |
| `var()` inside SVG paint attributes | unreliable | hardcode the colour in the SVG |
| bare `backdrop-filter` | Safari 9 w/ prefix | `-webkit-backdrop-filter` **and** the unprefixed one |

Both kiosk files scale type with `vmin` for exactly this reason — the fixed
full-screen grid means `vmin` gives you responsive sizing without `clamp()`.

Keep the glass blur radius low in `kiosk-ios27.html`: the A7 GPU in an iPad
Air 1 will drop frames on a heavy `backdrop-filter`, and the design has to stay
readable if the blur is ignored entirely.

### JavaScript: ES2017 only

ES6 is fine — `let`, `const`, arrow functions, template literals, `class`,
`Promise`, `padStart` all work. What breaks:

| Don't use | Since | Use instead |
|-----------|-------|-------------|
| `?.` optional chaining | Safari 13.1 | `a && a.b && a.b.c` |
| `??` nullish coalescing | Safari 13.1 | `x !== undefined && x !== null ? x : def` — or `\|\|` when falsy-vs-null doesn't matter |
| `??=` `\|\|=` `&&=` | Safari 14 | plain `if` + assignment |
| `Promise.allSettled` | Safari 13 | sequential `.then()` chains, or `Promise.all` over promises that each `.catch()` |
| `Object.fromEntries` | Safari 12.1 | a `forEach` loop building the object |
| `String.replaceAll` | Safari 13.1 | `.replace(/x/g, …)` |
| `String.matchAll` | Safari 13 | `while ((m = re.exec(s)))` |
| `Array.at` / `flat` / `flatMap` | Safari 15.4 / 12 | index arithmetic, `concat.apply` |
| `globalThis` | Safari 12.1 | `window` |
| numeric separators `1_000` | Safari 13 | `1000` |
| regex lookbehind `(?<=…)` | Safari 16.4 | capture groups |
| `async` / `await` | works, but | the existing kiosk code is callback/`.then()` style — match it |

`Promise.allSettled` deserves special attention: it is what `index.html` uses in
`initAll()`, so copying a fetch-orchestration block from `index.html` into a
kiosk is a very easy way to kill the whole page.

### Dates

Safari 12 rejects ISO timestamps with more than millisecond precision, which is
exactly what the `updated` field in every `data/*.json` looks like. Both kiosk
files already have the fix — always parse through it:

```js
// kiosk.html / kiosk-ios27.html
var d = safeDate(json.updated);   // trims .123456 → .123, returns null if invalid
```

For a `YYYY-MM-DD` date, `Date.parse` gives you UTC midnight, which shifts the
day in Czech local time. The kiosk files have a local-midnight helper for this —
find it before writing your own.

## Verifying without the iPad

You can't test on the device, so build confidence this way instead:

1. Run the checker — it catches the mechanical failures.
2. Re-read your diff hunting specifically for the table entries above; the
   patterns are easy to introduce by habit.
3. Open the file locally (`python -m http.server`) to confirm the layout is
   sane, remembering this proves nothing about Safari 12.
4. Sanity-check that removed `gap` was actually replaced by margins — dropping
   `gap` without a replacement is a silent layout regression rather than a
   silent parse failure, and the checker cannot tell the difference.
