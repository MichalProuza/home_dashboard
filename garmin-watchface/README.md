# Home Dashboard — Garmin Watchface

Ciferník pro hodinky Garmin vytvořený v Connect IQ (Monkey C).

## Funkce

- **Čas** — velký digitální formát (24h / 12h podle nastavení hodinek)
- **Datum** — den v týdnu a datum v češtině (Po 25. úno)
- **Baterie** — ikona + procenta s barevným indikátorem (zelená > 50%, žlutá > 20%, červená)
- **Kroky** — denní počet kroků
- **Tepová frekvence** — aktuální tep (pokud je k dispozici)
- **Bluetooth** — indikátor připojení telefonu

## Podporovaná zařízení

- Fenix 7 / 7S / 7X
- Forerunner 255 / 255S / 265 / 265S / 955 / 965
- Venu 2 / 2S / 3 / 3S / Sq 2 / Sq 2 Music
- Epix 2 / Epix Pro (42/47/51 mm)
- Approach S70 (42/47 mm)
- D2 Air X10

## Požadavky

- [Garmin Connect IQ SDK](https://developer.garmin.com/connect-iq/sdk/) (verze 6.x+)
- Java JDK 8+

## Sestavení

```bash
# Pomocí Connect IQ SDK CLI
monkeyc -d fenix7 -f monkey.jungle -o bin/HomeDashboard.prg -y developer_key.der
```

Nebo otevřete projekt ve **Visual Studio Code** s rozšířením
[Monkey C](https://marketplace.visualstudio.com/items?itemName=garmin.monkey-c)
a spusťte build přes paletu příkazů.

## Struktura projektu

```
garmin-watchface/
├── manifest.xml                     # Manifest aplikace (ID, typ, zařízení)
├── monkey.jungle                    # Build konfigurace
├── source/
│   ├── HomeDashboardApp.mc          # Vstupní bod aplikace
│   └── HomeDashboardView.mc         # Vykreslování ciferníku
├── resources/
│   ├── strings/strings.xml          # Textové řetězce
│   ├── drawables/drawables.xml      # Deklarace grafických zdrojů
│   ├── drawables/launcher_icon.png  # Ikona aplikace
│   └── layouts/layout.xml           # Layout (prázdný — vykreslujeme ručně)
└── .gitignore
```

## Licence

Soukromý projekt.
