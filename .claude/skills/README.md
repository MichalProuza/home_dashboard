# Skills pro home_dashboard

Projektové skilly pro Claude Code. Claude si je natáhne sám podle `description`
v hlavičce každého `SKILL.md` — psané jsou tak, aby se spustily i když je
nezmíníš jménem. Vyvolat ručně jde přes `/<název>`.

Vznikly ze vzorů opakovaných v prvních ~60 PR: co se muselo dělat pořád dokola
a kde se nejčastěji chybovalo.

| Skill | Kdy se použije | Řeší opakovanou chybu |
|-------|----------------|------------------------|
| `kiosk-safari12` | jakákoli změna v `kiosk*.html` | Safari 12 padá tiše — jeden `?.` shodí celý script, jeden flex `gap` zruší layout |
| `dashboard-frontend` | přidání/změna sekce dashboardu | feature přistane jen v 1 ze 3 frontendů a na zdi visí neúplný dashboard |
| `dashboard-data-source` | nový nebo měněný datový zdroj | zapomenutý seed JSON, kiosk sekce, rotující token, historie mezi běhy |
| `dashboard-actions-debug` | workflow padá / data nepřitékají | diagnostické commity do mainu místo čtení logů |
| `dashboard-scraper-repair` | rozbitý jídelníček / plán akcí ZŠ | škola změní markup; parser musí být tolerantní a nesmí smazat stará data |
| `dashboard-ship` | commit, push, PR | zapomenutá aktualizace `CLAUDE.md`, testovací JSON v commitu |

## Kontrolní skripty

Fungují i samostatně, bez Claude:

```bash
# Safari 12 / iPad Air 1 — kontrola kiosk*.html (exit 1 = problém)
bash .claude/skills/kiosk-safari12/scripts/check_compat.sh

# obálka a povinné klíče v data/*.json (--live pro čerstvý výstup skriptu)
python3 .claude/skills/dashboard-data-source/scripts/validate_data_json.py

# je novinka ve všech třech frontendech?
bash .claude/skills/dashboard-frontend/scripts/check_parity.sh [výraz…]
```

Skripty jsou lintery, ne parsery — hlídají doložené opakované chyby. Když
narazíš na nový případ, přidej si jeho vzor do skriptu, ať je příště pokrytý.
`REQUIRED` ve validátoru a seznam vzorů v `check_compat.sh` jsou k tomu určené.
