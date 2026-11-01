# Privátní hosting na Cloudflare (plán B) — NASAZENO

Dashboard běží na **`https://dashboard.prouza.co.uk`** za **Cloudflare Access**:
přístup jen po přihlášení (e-mailový kód), ale **kiosk na zdi z domácí IP jede
bez přihlašování** (Access „Bypass"). Data se servírují ze same-origin **Pages
Function** `/api/data/:name`, která je čte z větve `data` přes GitHub token
(token zůstává jen na serveru Cloudflare).

- Browser dashboard: `https://dashboard.prouza.co.uk/`
- Kiosk: `https://dashboard.prouza.co.uk/kiosk.html`

GitHub Actions a Python skripty zůstaly **beze změny** — pořád publikují na
větev `data`.

## Důležité rozhodnutí: repo zůstává VEŘEJNÉ

Původně se počítalo s přepnutím repa na private (aby byla privátní i `data`
větev). **Neuděláno** — na privátním repu jsou **GitHub Actions minuty měřené**
(Pro ~3000 min/měsíc), ale fetch workflowy běží ~330×/den ≈ **10 000 min/měsíc**,
což kvótu mnohonásobně překračuje (data by se přestala aktualizovat, nebo by se
platilo). Na veřejném repu jsou Actions **zdarma a neomezené**.

Důsledek: **vykreslený dashboard je privátní** (za Access), ale **větev `data`
zůstává veřejně čitelná** přes `raw.githubusercontent.com`. Bráno jako přijatelné
riziko (neinzerovaná URL). Plné soukromí dat by vyžadovalo private repo +
přesun sběru dat mimo Actions (domácí cron / VPS).

## Jak je to poskládané

- `functions/api/data/[name].js` — Pages Function, čte `data` větev přes
  `GH_DATA_TOKEN`, vrací JSON. Povoluje jen názvy `*.json` (žádný path traversal).
- `functions/api/refresh.js` — Pages Function pro tlačítko „obnovit" (kiosky i
  index.html): přes `GH_ACTIONS_TOKEN` ručně spustí workflowy Netatmo, Tuya,
  Growatt, Počasí a To Do (`workflow_dispatch`); frontend pak data znovu načte
  po 1 a 2 minutách. Ruční běh v posledních 3 min → nespouští znovu.
- `index.html` i `kiosk.html` — `DATA_BRANCH_BASE` se přepíná podle domény:
  - na `*.github.io` → veřejné `raw`,
  - jinde (Cloudflare doména, i `localhost`) → same-origin `/api/data/`.

## Postup nasazení (reference)

### 1. Cloudflare Pages — POZOR: jako Pages, ne Worker
- Workers & Pages → **Create** → záložka **Pages** → **Connect to Git** → repo
  `home_dashboard`, větev `main`. Build: **None**, output directory `/`.
- ⚠️ Když se to založí přes „Workers" cestu, build padá na
  `npx wrangler versions upload` / „Missing entry-point". Náš kód (statika +
  složka `functions/`) patří do **Pages** projektu — ten žádný build/deploy
  příkaz nepotřebuje a `functions/` si najde sám.

### 2. Vlastní doména
- Pages projekt → **Custom domains** → `dashboard.prouza.co.uk`.
- CNAME se přidává **v Cloudflare DNS** zóny `prouza.co.uk` (Name `dashboard`,
  Target `<projekt>.pages.dev`, **Proxied**). U domény na stejném účtu to
  Cloudflare většinou založí sám.

### 3. Token pro data
- GitHub → Settings → Developer settings → **Fine-grained token**: jen repo
  `home_dashboard`, oprávnění **Contents: Read-only**.
- Pages projekt → Settings → **Variables and Secrets** → přidej
  **`GH_DATA_TOKEN`** (typ Secret, Production). **Pak redeploy** (env se načte
  až novým nasazením: Deployments → Retry deployment).
- Ověř: `https://dashboard.prouza.co.uk/api/data/weather.json` vrátí JSON.

### 3b. Token pro tlačítko „obnovit"
- GitHub → profil → **Settings → Developer settings → Personal access tokens →
  Fine-grained tokens → Generate new token**
  (přímo `https://github.com/settings/personal-access-tokens/new`).
- Repository access: **Only select repositories** → `home_dashboard`.
  Permissions → Repository permissions → **Actions: Read and write**.
- Pages projekt → Settings → **Variables and Secrets** → **`GH_ACTIONS_TOKEN`**
  (typ Secret, Production). **Pak redeploy.**
- Bez tokenu tlačítko ukáže „nelze spustit" a jen znovu načte stávající data.

### 3c. Plánovač — Worker s Cron Triggerem (`workers/scheduler/`)
GitHub plánované běhy (`schedule`) reálně pouští ~5× denně, proto workflowy
pravidelně spouští samostatný Worker přes `workflow_dispatch`:
5:00–7:59 pražského času každých 10 min (Netatmo, Tuya, Growatt, Počasí, To Do),
jinak každé 2 h (+ kalendář), v 5:00 navíc jídelníček a akce ZŠ. Rozvrh je
v `pickWorkflows()` v `workers/scheduler/index.js`. `schedule` v GitHub
workflowech zůstávají jako záloha.

**⚠️ Nejdřív vypni Preview buildy z větve `data`** (Pages projekt → Settings →
Builds → Branch control → Preview branches: None, nebo Exclude `data`). Každý
běh workflowu pushne na `data` (~160× denně) a každý push by jinak spustil
Preview build — limit Free plánu je 500 buildů/měsíc.

Nasazení (stačí jednou, kód se mění zřídka):
- Workers & Pages → **Create** → **Worker** → *Start with Hello World* →
  název `home-dashboard-scheduler` → **Deploy** → **Edit code** → obsah
  `workers/scheduler/index.js` vložit místo vzorového kódu → **Deploy**.
- Worker → Settings → **Variables and Secrets** → **`GH_ACTIONS_TOKEN`**
  (Secret, stejný token jako u Pages).
- Worker → Settings → **Trigger events** (Triggers) → **Cron Triggers** →
  `*/10 * * * *`.
- Ověření: Worker → **Logs** (Observability) / Cron Events — každých 10 min
  ráno „spuštěno 5/5"; na GitHubu Actions běhy s událostí `workflow_dispatch`.
- Po změně `index.js` v repu kód do Workeru znovu vložit (Edit code → Deploy).

### 4. Microsoft To Do v prohlížeči (jen index.html)
- Browser To Do dělá OAuth redirect na aktuální URL. Po přesunu na novou doménu
  je nutné v **Azure → App registrations → [app] → Authentication** přidat pod
  platformu **Single-page application (SPA)** redirect URI:
  `https://dashboard.prouza.co.uk/`.
- Kiosk To Do je server-side (čte `mstodo.json`), s tímhle nemá nic společného.

### 5. Cloudflare Access (Zero Trust)
- Zero Trust (plán Free) → Access → Applications → **Add → Self-hosted** →
  hostname `dashboard.prouza.co.uk` (prázdná path → chrání celý web i `/api/data/`).
- Politiky:
  - **Bypass** (první) — Include: **IP ranges** = domácí veřejná IP. Přidej
    **IPv4 `X.X.X.X/32`**; když kiosk jede po IPv6, přidej i **IPv6 `…/64` prefix**
    (poslední část IPv6 se střídá, jedna /128 nestačí).
  - **Allow** — Include: Emails = tvůj e-mail (přihlášení přes One-time PIN).
- Domácí IP zjisti **z domácí sítě** (ideálně z kiosku) na `https://ifconfig.me`,
  s **vypnutým iCloud Private Relay / VPN** — jinak dostaneš cizí (relay) IP.

### 6. Úklid
- Na iPad přidej na plochu `https://dashboard.prouza.co.uk/kiosk.html`.
- **Vypni GitHub Pages** (Settings → Pages) — Cloudflare na něm nezávisí.

## Údržba / na co nezapomenout
- **Změna domácí IP** → kiosk by chtěl login → aktualizuj IP v Bypass politice.
- **`GH_DATA_TOKEN`** a **`GH_ACTIONS_TOKEN`** mají expiraci (max. rok) → po
  vypršení vygeneruj nový a v Cloudflare ho přepiš **+ redeploy**.
- **Nový obsah**: push/merge do `main` → Cloudflare Pages se **sám** redeployne.
  Jen po změně env proměnných je nutný ruční redeploy.
- **WARP/device politiky** na iPad Air 1 (iOS 12) nepoběží — proto IP bypass.
