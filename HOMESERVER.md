# Domácí server (Mac) — sběr dat mimo GitHub Actions

> **Stav: připraveno, NEPŘEPNUTO.** Produkce běží dál přes Worker scheduler →
> GitHub Actions → větev `data` → Pages Function. Kód domácího serveru je
> v repu, ale nic ho nepoužívá, dokud se v Cloudflare Pages nenastaví
> `DATA_SOURCE=home` (postup níže, [checklist přepnutí](#5-checklist-přepnutí)).

## Proč

Dnes je vykreslený dashboard privátní (Cloudflare Access), ale **větev `data`
je veřejná** — repo musí zůstat veřejné, protože na privátním repu by
fetch workflowy (~10 000 min/měsíc) mnohonásobně přečerpaly kvótu Actions
minut (viz `CLOUDFLARE.md`, sekce „repo zůstává VEŘEJNÉ"). Když data bude
sbírat domácí Mac, Actions nejsou potřeba, data nikdy neopustí Mac jinak než
přes Access a repo lze přepnout na private.

## Architektura

```
            Mac (MacBook Air M1, launchd agenti)
  ┌──────────────────────────────────────────────────────────────┐
  │ runner   scripts/local/run.py daemon                         │
  │          rozvrh = pickWorkflows() (Europe/Prague, 10min sloty)│
  │          └─► scripts/fetch_*.py  (HD_MODE=local)              │
  │                └─► ~/Library/Application Support/             │
  │                     home_dashboard/data/*.json   (atomicky)   │
  │                     home_dashboard/state/*_token.enc, zámky   │
  │ server   scripts/local/server.py  127.0.0.1:8787              │
  │          GET /data/<x>.json · POST /refresh · GET /healthz    │
  │ cloudflared tunnel (jen odchozí spojení, žádný port-forward)  │
  └──────────────────────────┬───────────────────────────────────┘
                             │ dashboard-data.prouza.co.uk
                             │ Access: jen Service Auth (service token)
                             ▼
  Cloudflare Pages (dashboard.prouza.co.uk, za Access, kiosk bypass z domácí IP)
    functions/api/data/[name].js   DATA_SOURCE=home → GET  HOME_ORIGIN/data/<x>.json
    functions/api/refresh.js       DATA_SOURCE=home → POST HOME_ORIGIN/refresh
                             ▼
  index.html · kiosk.html · kiosk-ios27.html   (beze změny)
```

- **Frontendy se nemění.** Dál čtou same-origin `/api/data/<x>.json`
  a tlačítko „obnovit" dál volá `/api/refresh`; mění se jen to, odkud si data
  bere Pages Function.
- **Kiosk bypass z domácí IP** se týká jen `dashboard.prouza.co.uk`, nemění se.
- **Hostname tunelu** (`dashboard-data.prouza.co.uk`, název je jen návrh)
  je samostatná Access aplikace s jedinou politikou *Service Auth* — přihlášení
  e-mailem ani bypass tam nejsou, projde jen Pages Function se service tokenem.
  Navíc ho ověřuje i `cloudflared` sám (`originRequest.access.required`).

## Co je v repu

| Soubor | K čemu |
|--------|--------|
| `scripts/hd_common.py` | Společný modul fetch skriptů: výstupní adresář, atomický zápis (dočasný soubor + `os.replace`), v `HD_MODE=local` načtení konfigurace z `~/.config/home_dashboard/env` (jen s právy 600) a tokeny do adresáře `state`. Bez `HD_MODE` vše jako dřív (`data/` v repu). |
| `scripts/local/run.py` | Runner: `daemon` (rozvrh), `once live\|all\|<zdroj>…`, `plan [--at ISO \| --day YYYY-MM-DD]`. Zámky proti souběhu (daemon i každý zdroj zvlášť), stav běhů v `state/status/`. |
| `scripts/local/server.py` | HTTP server (jen stdlib, jen localhost): `GET /data/<x>.json`, `POST /refresh` (3min ochrana proti opakování), `GET /healthz`. |
| `deploy/macos/install.sh` / `uninstall.sh` | Instalace: venv, závislosti, plisty, `launchctl bootstrap`. Idempotentní. |
| `deploy/macos/local.home-dashboard.*.plist` | Šablony launchd agentů (runner, server, cloudflared), `KeepAlive`, logy do `~/Library/Logs/home_dashboard/`. |
| `deploy/macos/env.example` | Vzor konfigurace se secrets (náhrada GitHub Secrets). |
| `deploy/macos/cloudflared.yml.example` | Vzor konfigurace tunelu. |
| `deploy/macos/requirements.txt` | Závislosti všech skriptů (sjednocené z workflowů) + `tzdata`. |
| `deploy/macos/import-data-branch.sh` | Jednorázové převzetí JSON (a volitelně tokenů) z větve `data`. |

Rozvrh runneru je kopie `pickWorkflows()` z `workers/scheduler/index.js`
(ověřeno na všech 52 560 slotech roku 2026, včetně přechodů letního času).
Při změně rozvrhu uprav obě místa; `run.py plan --day 2026-03-29` vypíše den.

Umístění na Macu:

| Co | Kde |
|----|-----|
| Klon repa (kód) | `~/src/home_dashboard` — **ne** v `~/Documents`, `~/Desktop`, `~/Downloads` ani iCloudu (TCC: launchd tam nesmí, `install.sh` to odmítne) |
| Konfigurace se secrets | `~/.config/home_dashboard/env` (600), `~/.config/home_dashboard/cloudflared.yml` |
| Data (servírovaná) | `~/Library/Application Support/home_dashboard/data/` |
| Tokeny, zámky, stav | `~/Library/Application Support/home_dashboard/state/` (700, server ho nikdy neservíruje) |
| venv | `~/Library/Application Support/home_dashboard/venv/` |
| Logy | `~/Library/Logs/home_dashboard/` — `runner.log`, `refresh.log`, `server.log` (rotace 1 MB × 3), `cloudflared.log`, `*.launchd.log` (jen pády) |
| Tunnel credentials | `~/.cloudflared/` |

---

## 1. Nastavení Macu

### Napájení a spánek (`pmset`)

MacBook má baterii, takže krátký výpadek proudu přečká sám (funguje jako UPS).
Je ale potřeba, aby na adaptéru nikdy neusnul:

```bash
sudo pmset -c sleep 0 disksleep 0 displaysleep 5 powernap 0 womp 1 tcpkeepalive 1
```

```bash
sudo pmset -a autorestart 1
```

```bash
pmset -g
```

- `-c` = na adaptéru. Displej zhasne po 5 min, systém ani disk nespí.
- `autorestart 1` = start po výpadku proudu; u MacBooků nemusí být podporováno
  (`pmset -g` ho pak nevypíše). Apple Silicon MacBook se ale po úplném vybití
  baterie sám zapne, jakmile dostane napájení (výchozí `nvram AutoBoot=%03`).
  **Ověř jednou testem**: Mac vypnout, odpojit a připojit zdroj → musí naběhnout.
- **Víko nechej otevřené** (stačí pootevřené, displej zhasne sám) — se zavřeným
  víkem bez externího monitoru MacBook usne. Alternativa
  `sudo pmset -a disablesleep 1` drží Mac vzhůru i zavřený, ale hůř chladí.
- Nastavení → Baterie → Volby: „Zabránit automatickému uspání na napájecím
  adaptéru, když je displej vypnutý" **zapnout**, „Probouzet při přístupu
  k síti" **vždy**.
- Nastavení → Obecné → Aktualizace softwaru → Automatické aktualizace:
  **instalaci aktualizací macOS vypnout** (restart by přišel kdykoli),
  bezpečnostní odpovědi a systémové soubory nechat. Aktualizace dělej ručně
  a po restartu zkontroluj `/healthz`.

### Spouštění po restartu

Agenti jsou uživatelské LaunchAgents (`gui/<uid>`), startují po přihlášení
uživatele. Pro bezobslužný provoz:

- **Nastavení → Uživatelé a skupiny → Automaticky přihlásit** → tvůj účet.
- To vyžaduje **vypnutý FileVault**. Kompromis:
  - *FileVault vypnutý + auto-login* (doporučeno pro server): po výpadku/
    restartu vše naběhne samo. Při krádeži Macu jsou ale čitelné secrets
    v `~/.config/home_dashboard/env` → v takovém případě rotuj všechny tokeny
    (seznam viz [rotace](#rotace-tokenů)).
  - *FileVault zapnutý*: po restartu z aktualizace macOS se Mac odemkne sám
    (authenticated restart), ale po úplném vybití baterie čeká na ruční
    odemčení — data do té doby stárnou (frontend ukáže ⚠).
- Zámek obrazovky může zůstat zapnutý — agenti běží i se zamčenou obrazovkou.

### Baterie (omezení nabíjení)

MacBook trvale na adaptéru se 100 % nabitím baterii rychle opotřebí.

- **AlDente** (https://apphousekitchen.com, free verze stačí): limit nabíjení
  **80 %**, „Stop charging when sleeping" vypnout, spouštět po přihlášení.
  Potřebuje svůj helper (při instalaci se zeptá na heslo).
- Vestavěné „Optimalizované nabíjení" pevný limit nedrží, nestačí.
- Kontrola stavu baterie občas:
  `system_profiler SPPowerDataType | grep -iE "cycle|condition|maximum"`.

### Síť

- **Ethernet přes USB-C adaptér** (doporučeno) — stabilnější než Wi-Fi, žádné
  usínání Wi-Fi. Wi-Fi nech zapnutou jako zálohu (macOS ji použije, když kabel
  vypadne).
- Port-forwarding ani veřejná IP nejsou potřeba: tunel je jen odchozí spojení.
  Domácí IP (a Access bypass kiosku) se tím nemění.
- Vzdálená správa (volitelné): Nastavení → Obecné → Sdílení → Vzdálené
  přihlášení (SSH) jen z LAN; přístup zvenku třeba přes Tailscale.

### Software

```bash
brew install python@3.13 cloudflared git
```

```bash
mkdir -p ~/src && git clone https://github.com/MichalProuza/home_dashboard.git ~/src/home_dashboard
```

Po přepnutí repa na private bude `git pull` na Macu potřebovat přihlášení
(`gh auth login`, nebo read-only *deploy key* jen pro tohle repo).

## 2. Instalace

```bash
cd ~/src/home_dashboard && bash deploy/macos/install.sh
```

První běh vytvoří `~/.config/home_dashboard/env` (práva 600) ze vzoru
`deploy/macos/env.example` a skončí. Vyplň ho (viz
[souběžný provoz](#4-souběžný-provoz-ověřovací-fáze) — rotující tokeny Netatmo
a MS To Do **nesmí** sdílet s Actions) a spusť znovu:

```bash
bash deploy/macos/install.sh
```

Druhý běh vytvoří venv, nainstaluje závislosti, vygeneruje plisty do
`~/Library/LaunchAgents/` a spustí agenty runner a server (cloudflared až po
kroku 3). Runner po startu hned dohání chybějící/zastaralá data.

Volitelně převezmi data z větve `data` (historie SOC pro graf Growatt, zálohy
jídelníčku a akcí ZŠ) — **bez** `--tokens`:

```bash
bash deploy/macos/import-data-branch.sh
```

Ověření:

```bash
curl -s http://127.0.0.1:8787/healthz | python3 -m json.tool
```

```bash
curl -s http://127.0.0.1:8787/data/weather.json | head -5
```

```bash
tail -f ~/Library/Logs/home_dashboard/runner.log
```

`/healthz` vrací `ok: true`, až mají všechny zdroje poslední běh s kódem 0
(nebo 75 = přechodný výpadek Open-Meteo) a bez `error` v JSON. Ručně spustit
vše: `~/Library/Application\ Support/home_dashboard/venv/bin/python scripts/local/run.py once all`.

## 3. Tunel a Access service token

**Pořadí je důležité: nejdřív Access aplikace, pak DNS** — hostname tak není
ani chvíli dostupný bez ochrany.

1. **Service token** — Cloudflare Zero Trust → Access → Service auth →
   Service Tokens → *Create*: název `home-dashboard-pages`, doba platnosti
   (doporučeno 1 rok + připomínka v kalendáři). **Client Secret se ukáže jen
   jednou** — ulož Client ID i Secret.
2. **Access aplikace** — Access → Applications → *Add* → *Self-hosted*:
   - hostname `dashboard-data.prouza.co.uk` (prázdná path = celý host),
   - politika: **Action: Service Auth**, Include: **Service Token =
     `home-dashboard-pages`**. Žádná další politika (žádný Bypass, žádné
     e-maily).
   - Po uložení si z přehledu aplikace opiš **Application Audience (AUD) Tag**
     a ze Zero Trust → Settings název týmu (team domain `<team>.cloudflareaccess.com`).
3. **Tunel** (na Macu):

   ```bash
   cloudflared tunnel login
   ```

   (v prohlížeči vyber zónu `prouza.co.uk`)

   ```bash
   cloudflared tunnel create home-dashboard
   ```

   (vypíše UUID a vytvoří `~/.cloudflared/<UUID>.json`)

   ```bash
   cloudflared tunnel route dns home-dashboard dashboard-data.prouza.co.uk
   ```

4. **Konfigurace tunelu**:

   ```bash
   cp deploy/macos/cloudflared.yml.example ~/.config/home_dashboard/cloudflared.yml
   ```

   Doplň `<TUNNEL_UUID>`, cestu ke credentials, `<team>` a `<AUD_TAG>`, pak:

   ```bash
   cloudflared tunnel --config ~/.config/home_dashboard/cloudflared.yml ingress validate
   ```

   ```bash
   bash deploy/macos/install.sh
   ```

   (teď nainstaluje i agenta cloudflared)
5. **Ověření** (odkudkoli):

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' https://dashboard-data.prouza.co.uk/data/weather.json
   ```

   → bez tokenu **302/403**, nikdy 200.

   ```bash
   curl -s -H "CF-Access-Client-Id: <ID>" -H "CF-Access-Client-Secret: <SECRET>" https://dashboard-data.prouza.co.uk/data/weather.json | head -5
   ```

   → JSON.

**Proměnné v Cloudflare Pages** (Settings → Variables and Secrets, Production;
dokud chybí `DATA_SOURCE`, nemají žádný účinek — lze je přidat předem):

| Proměnná | Typ | Hodnota |
|----------|-----|---------|
| `HOME_ORIGIN` | Text | `https://dashboard-data.prouza.co.uk` |
| `CF_ACCESS_CLIENT_ID` | Secret | Client ID service tokenu |
| `CF_ACCESS_CLIENT_SECRET` | Secret | Client Secret service tokenu |
| `DATA_SOURCE` | Text | `github` (výchozí, i když chybí) / `home` — **až při přepnutí** |
| `DATA_FALLBACK` | Text | volitelně `github`: když Mac neodpoví, číst větev `data` |

Odpověď `/api/data/*` nese hlavičku `X-Data-Source: github | home |
github-fallback` (DevTools → Network), takže je vidět, odkud data přišla.

## 4. Souběžný provoz (ověřovací fáze)

Mac může několik dní běžet **souběžně** s Actions — data se zatím nikde
nepoužívají, jen se porovnávají. Jediné, na co je třeba dát pozor, jsou
**rotující refresh tokeny**: každý refresh vydá nový token a starý zneplatní,
takže Mac a Actions nesmí sdílet jeden řetězec (ani zkopírovaný
`*_token.enc`) — navzájem by se odstřelili.

- **Netatmo**: na https://dev.netatmo.com založ **novou aplikaci** (např.
  `home_dashboard-mac`), v env použij její `NETATMO_CLIENT_ID/SECRET`
  a refresh token z jejího Token generatoru (scope `read_station`).
- **Microsoft To Do**: v Azure založ **novou registraci aplikace** jen pro Mac
  (platforma *Mobile and desktop applications*, aby refresh token žil ~90 dní,
  viz CLAUDE.md) a vygeneruj proti ní `MSTODO_REFRESH_TOKEN`. Původní aplikace
  zůstává pro `index.html` (přihlášení v prohlížeči).
- `NETATMO_TOKEN_KEY` a `MSTODO_TOKEN_KEY`: **nové** náhodné řetězce
  (`openssl rand -hex 32`).
- Ostatní (Growatt, Tuya, kalendář) lze zkopírovat z GitHub Secrets. Souběh
  zdvojnásobí počet volání Growatt/Tuya API; kdyby Growatt hlásil omezení
  četnosti, je to souběhem a po přepnutí zmizí.

Tím se zároveň vyřeší rotace: tokeny, jejichž šifrovaná podoba ležela ve
veřejné větvi `data`, se po přepnutí jen zneplatní (smazáním starých aplikací).

Porovnání: `/healthz` na Macu a stáří dat (`updated`) vůči
`https://dashboard.prouza.co.uk/api/data/<x>.json`.

*Alternativa bez nových aplikací*: převzít stávající řetězec tokenů až
v okamžiku přepnutí — vypnout workflowy `netatmo.yml` a `mstodo.yml`, do env
dát **stejné** `*_TOKEN_KEY` jako v GitHub Secrets a spustit
`bash deploy/macos/import-data-branch.sh --tokens`. Pak ale v kroku rotace
vygeneruj nové seedy a klíče.

## 5. Checklist přepnutí

Předpoklad: Mac běží souběžně aspoň pár dní, `/healthz` je `ok: true`, tunel
s Access je ověřený (krok 3) a v Pages jsou `HOME_ORIGIN`
+ `CF_ACCESS_CLIENT_ID/SECRET`.

1. **Přepnout čtení na Mac** — Pages → Variables: `DATA_SOURCE=home`,
   `DATA_FALLBACK=github` → **Deployments → Retry deployment** (env se načte až
   novým nasazením).
   - Ověř: v prohlížeči (přihlášen přes Access) DevTools → Network →
     `/api/data/weather.json` má `X-Data-Source: home`; kiosk ukazuje čerstvá
     data; tlačítko „obnovit" → na Macu přibude záznam v `refresh.log`
     a druhé stisknutí do 3 min vrátí `running`.
2. **Vypnout Worker scheduler** — Workers & Pages → `home-dashboard-scheduler`
   → Settings → Trigger events → cron `*/10 * * * *` **smazat** (kód i secret
   nech, kvůli rollbacku).
   - Ověř: na GitHubu v Actions nepřibývají běhy `workflow_dispatch`.
3. **Vypnout workflowy na GitHubu** (záložní `schedule` crony) — Actions →
   každý z 8 workflowů → `…` → **Disable workflow**. Bez změny kódu, vratné
   jedním klikem.
   - Ověř: žádné nové běhy, větev `data` přestane přibývat commity.
4. **Den–dva sledovat** — dashboard i kiosk, `runner.log`, `/healthz`, ranní
   okno 5:00–7:59 (sloty po 10 min).
5. **Vypnout fallback** — Pages: smazat `DATA_FALLBACK` → redeploy. (Větev
   `data` už se neaktualizuje; fallback by tiše ukazoval stará data.)
6. **Repo na private** — Settings → General → Danger zone → Change visibility.
   Předtím:
   - Insights → Forks: veřejné forky by zůstaly veřejné (včetně historie).
   - Po přepnutí ověř, že Cloudflare Pages dál nasazuje z `main` (GitHub app
     Cloudflare musí mít přístup k repu) — např. Deployments → Retry deployment.
   - Na Macu ověř `git pull` (přihlášení, viz Software).
7. **Smazat větev `data`** — `git push origin --delete data`. Na privátním
   repu už nikdo cizí nečte, smazání odstraní i historii JSON.
8. **Rotace tokenů a úklid** (viz níže).
9. **Navazující PR** (volitelně, až nebude potřeba rollback): odstranit
   `schedule` z workflowů, `publish_data.sh`, Worker scheduler, větev
   `github` ve Functions; aktualizovat CLAUDE.md / README / CLOUDFLARE.md.

### Rotace tokenů

Co bylo veřejně dostupné: obsah JSON ve větvi `data` (úkoly, události
kalendáře, stav brány, energie) a **šifrované** refresh tokeny
`netatmo_token.enc` / `mstodo_token.enc` (klíč byl jen v GitHub Secrets).
Přímo uniklý secret tedy žádný, ale šifrované tokeny mohl kdokoli stáhnout,
takže je zneplatni:

| Co | Jak |
|----|-----|
| Netatmo (řetězec z Actions) | dev.netatmo.com → **smazat původní aplikaci** (zneplatní její tokeny). Mac používá novou. Smazat GitHub Secrets `NETATMO_*`. |
| MS To Do (řetězec z Actions) | https://account.live.com/consent/Manage (účet Microsoft → Soukromí → Aplikace a služby) → u původní aplikace **odebrat oprávnění** (zneplatní její refresh tokeny; `index.html` se při příštím přihlášení zeptá znovu). Mac používá novou registraci. Smazat GitHub Secrets `MSTODO_*`. |
| Převzaté tokeny (alternativa s `--tokens`) | Vygenerovat nové seedy a nové `*_TOKEN_KEY`, smazat `state/*_token.enc`, restart runneru. |
| `GH_DATA_TOKEN`, `GH_ACTIONS_TOKEN` | Smazat z Pages a Workeru, na GitHubu **revoke** (Settings → Developer settings → Fine-grained tokens). |
| Growatt, Tuya, `CALENDAR_ICS_URL` | Nikdy veřejné nebyly → rotace nepovinná. Secrets na GitHubu smazat, až nebude potřeba rollback. (Tajnou iCal adresu lze v Google Kalendáři resetovat, pokud chceš.) |

## 6. Rollback

**Rychlý rollback** (Mac nefunguje, repo ještě veřejné, větev `data` existuje):

1. Pages: `DATA_SOURCE=github` (nebo proměnnou smazat) → **Retry deployment**.
   Dashboard okamžitě čte větev `data` (s poslední publikovanou verzí).
2. Worker: Trigger events → znovu přidat cron `*/10 * * * *`.
3. GitHub Actions: workflowy **Enable workflow**.
4. Ověř běhy `workflow_dispatch` v Actions a `X-Data-Source: github`.

Pokud už byly smazány původní Netatmo/Azure aplikace nebo GitHub Secrets,
je nutné je obnovit a vygenerovat nové seedy `NETATMO_REFRESH_TOKEN` /
`MSTODO_REFRESH_TOKEN` (stejně jako po smazání větve `data`, viz CLAUDE.md).

**Po smazání větve `data`**: první běh workflowu ji založí znovu
(`publish_data.sh`), ale bez `*_token.enc` → nové seedy Netatmo i To Do;
historie SOC Growatt začne od nuly.

**Po přepnutí repa na private**: Actions minuty jsou měřené (~3 000 min/měsíc
na Pro). Plný rozvrh (~10 000 min) se nevejde; jako dočasné řešení stačí
upravit Worker jen na 2hodinový rytmus (~2 200 min/měsíc), nebo repo vrátit na
public (pak je ale větev `data` zase veřejná).

**Mac**: zastavit agenty `bash deploy/macos/uninstall.sh` (data a konfigurace
zůstanou), znovu spustit `bash deploy/macos/install.sh`.

## 7. Provoz a údržba

- **Stav**: `curl -s http://127.0.0.1:8787/healthz`, logy
  `~/Library/Logs/home_dashboard/` (i v Console.app).
- **Agenti**:
  `launchctl print gui/$(id -u)/local.home-dashboard.runner` (stav),
  `launchctl kickstart -k gui/$(id -u)/local.home-dashboard.runner` (restart);
  totéž pro `.server` a `.cloudflared`.
- **Aktualizace kódu**: Mac spouští kód ze svého klonu, ne z Cloudflare. Po
  merge změn ve `scripts/`:
  `cd ~/src/home_dashboard && git pull && bash deploy/macos/install.sh`
  (aktualizuje závislosti a restartuje agenty).
- **Nový datový zdroj**: kromě workflowu přidat do `SOURCES` (a rozvrhu)
  v `scripts/local/run.py`, závislosti do `deploy/macos/requirements.txt`
  a secrets do `env`.
- **Rotující token přestal platit** (`error` v `netatmo.json` /
  `mstodo.json`): nový seed do `~/.config/home_dashboard/env`, smazat
  `state/<zdroj>_token.enc`, `run.py once <zdroj>`.
- **Expirace**: service token Access (kalendář!), MS refresh token ~90 dní
  nečinnosti (běží každé 2 h, takže se průběžně obnovuje).
- **Záloha**: nic kritického — data se obnoví dalším během, tokeny ze seedů.
  Konfiguraci `env` si ulož do správce hesel.

## 8. Další kroky (mimo rozsah této přípravy)

- **Tuya lokálně přes LAN** ([tinytuya](https://github.com/jasonacox/tinytuya))
  místo Tuya Cloudu: stav brány/garáže přímo ze zařízení v domácí síti, bez
  závislosti na cloudu a jeho kvótách, s možností častějšího dotazování.
  Jednorázově je potřeba získat `local_key` zařízení (`python -m tinytuya
  wizard` přes stávající Tuya IoT účet) a zjistit verzi protokolu (3.3/3.4/3.5).
  Výstup by zůstal ve stejném `tuya.json`.
- **Home Assistant** (na Macu v Dockeru/VM, nebo samostatné zařízení typu
  HA Green / Raspberry Pi): integrace Netatmo, Growatt, Tuya (lokálně), MS To Do
  na jednom místě, historie a automatizace; dashboard by pak četl z REST API
  Home Assistantu místo vlastních fetch skriptů.
- **Hlídání výpadků**: ping na healthchecks.io (nebo podobné) z runneru po
  každém úspěšném slotu → e-mail/notifikace, když Mac přestane posílat.
- **Úklid po přepnutí**: viz bod 9 checklistu.
