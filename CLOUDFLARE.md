# Privátní hosting na Cloudflare (plán B)

Cíl: dashboard (web **i data**) za **Cloudflare Access**, aby ho viděl jen
přihlášený uživatel — ale **kiosk na zdi z domácí IP funguje bez přihlašování**
(Access „Bypass"). Data se přestanou číst z veřejného
`raw.githubusercontent.com` a místo toho je servíruje **Pages Function**
`/api/data/:name` z větve `data` přes GitHub token (token zůstává jen na serveru).

GitHub Actions a Python skripty zůstávají **beze změny** — pořád publikují na
větev `data`.

## Co už je připravené v repu

- `functions/api/data/[name].js` — Pages Function, čte `data` větev přes
  `GH_DATA_TOKEN` a vrací JSON. Povoluje jen názvy `*.json` (žádný path traversal).
- `index.html` i `kiosk.html` — `DATA_BRANCH_BASE` se přepíná podle domény:
  - na `*.github.io` → veřejné `raw` (současný stav, nic se nerozbije),
  - jinde (Cloudflare doména, i `localhost`) → same-origin `/api/data/`.

Díky tomu jde tohle sloučit do `main` hned a po migraci to „jen funguje".

## Postup nasazení

### 0. Prerekvizity
- Účet Cloudflare.
- **Vlastní doména vedená přes Cloudflare** (Access nejde spolehlivě na holém
  `*.pages.dev`). Když žádnou nemáš, registruj levnou (~250 Kč/rok) a přepni jí
  nameservery na Cloudflare.
- **Fine-grained GitHub token**: GitHub → Settings → Developer settings →
  Fine-grained tokens → jen repo `home_dashboard`, oprávnění **Contents: Read-only**.

### 1. Cloudflare Pages
1. Cloudflare → Workers & Pages → **Create** → **Pages** → **Connect to Git** →
   vyber repo `home_dashboard`, větev `main`.
2. Build settings: **žádný build** (framework preset = None), output directory =
   `/` (kořen). Funkce ve složce `functions/` se nasadí automaticky.
3. Po prvním nasazení přidej **vlastní doménu** (Custom domains) dashboardu.

### 2. Secret pro Function
- Pages projekt → Settings → **Variables and Secrets** → přidej
  **`GH_DATA_TOKEN`** = ten fine-grained token (typ Secret). Ulož a re-deploy.
- Ověř: `https://<doména>/api/data/weather.json` vrátí JSON.

### 3. Cloudflare Access (Zero Trust)
1. Zero Trust → Access → **Applications** → **Add an application** → Self-hosted.
2. Application domain = doména dashboardu.
3. Politiky:
   - **Allow** — Include: Emails = tvůj e-mail (přihlášení přes jednorázový kód / Google).
   - **Bypass** — Include: **IP ranges = tvoje domácí IP** (kiosk se pak nepřihlašuje).
4. Zjisti domácí IP např. na `https://ifconfig.me` (z domácí sítě).

### 4. Přepnutí
1. **Repo → Private** (GitHub → Settings → General → Change visibility).
   Teď už to nic nerozbije — data tečou přes Function s tokenem.
2. **Vypni GitHub Pages** (Settings → Pages → zruš zdroj), ať veřejná verze zmizí.
3. Na iPadu přidej na plochu **novou Cloudflare URL** kiosku.

## Po migraci
- Privátní jsou i To Do, brána a kalendář (větev `data` už není veřejná).
- Cloudflare Pages se re-deployne při pushi do `main` (statika). Data se
  nemění buildem — Function je čte z `data` větve za běhu.

## Rizika / poznámky
- **Dynamická domácí IP**: když se změní, IP bypass přestane platit → kiosk by
  chtěl login. Většina připojení má IP dost stálou; jinak je nutné IP v Access
  politice občas aktualizovat.
- **GitHub API limity**: token autentizovaný = 5000 req/h; kiosk + dashboard
  dělají řádově desítky req/h. V pohodě.
- **WARP/device politiky** na iPad Air 1 (iOS 12) nejspíš nepoběží — proto IP bypass.
