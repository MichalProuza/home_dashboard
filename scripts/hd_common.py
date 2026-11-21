"""
Společné pomocníky fetch skriptů: kam ukládat výstup a režim domácího serveru.

Dva režimy, přepíná je proměnná prostředí HD_MODE:

  (neuvedeno)   GitHub Actions / ruční běh — chování jako dřív: secrets přichází
                v proměnných prostředí, výstup i *_token.enc jdou do data/
                v repozitáři, odkud je publish_data.sh pushne do větve "data".

  HD_MODE=local domácí server (Mac, viz HOMESERVER.md): konfigurace se načte
                ze souboru mimo repo (~/.config/home_dashboard/env, musí mít
                práva 600), JSON se zapisuje do lokálního adresáře mimo repo
                a rotující refresh tokeny do vedlejšího adresáře „state",
                který HTTP server nikdy neservíruje.

Proměnné pro lokální režim (všechny volitelné):
  HD_ENV_FILE   cesta ke konfiguraci (výchozí ~/.config/home_dashboard/env)
  HD_HOME       základní adresář (výchozí ~/Library/Application Support/
                home_dashboard na macOS, jinde ~/.local/share/home_dashboard)
  HD_DATA_DIR   výstupní JSON (výchozí $HD_HOME/data)
  HD_STATE_DIR  tokeny, zámky, stav běhů (výchozí $HD_HOME/state)

Import modulu v lokálním režimu rovnou načte konfiguraci do os.environ, proto
ho skripty importují před čtením svých proměnných prostředí.
"""

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

REPO_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

LOCAL = os.environ.get("HD_MODE", "").strip().lower() == "local"


def default_home() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "home_dashboard"
    return Path.home() / ".local" / "share" / "home_dashboard"


def _dir_from_env(var: str, default: Path) -> Path:
    raw = os.environ.get(var, "").strip()
    return Path(raw).expanduser() if raw else default


HD_HOME = _dir_from_env("HD_HOME", default_home())
ENV_FILE = _dir_from_env("HD_ENV_FILE", Path.home() / ".config" / "home_dashboard" / "env")



def local_data_dir() -> Path:
    return _dir_from_env("HD_DATA_DIR", HD_HOME / "data")


def local_state_dir() -> Path:
    return _dir_from_env("HD_STATE_DIR", HD_HOME / "state")


def ensure_local_dirs() -> None:
    """Vytvoří lokální adresáře; state (tokeny, stav běhů) jen pro vlastníka."""
    local_data_dir().mkdir(parents=True, exist_ok=True)
    state = local_state_dir()
    state.mkdir(parents=True, exist_ok=True)
    os.chmod(state, 0o700)


if LOCAL:
    DATA_DIR = local_data_dir()
    STATE_DIR = local_state_dir()
else:
    # Actions: tokeny leží vedle JSON v data/, publish_data.sh je publikuje
    DATA_DIR = REPO_DATA_DIR
    STATE_DIR = REPO_DATA_DIR


def parse_env_file(text: str) -> dict:
    """KEY=VALUE po řádcích; # komentáře, volitelně `export ` a uvozovky.

    Hodnota se bere celá až do konce řádku (bez inline komentářů) — tokeny
    a hesla mohou obsahovat # i =.
    """
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def check_env_file(path: Path = ENV_FILE):
    """None když je konfigurace použitelná, jinak popis problému."""
    if not path.exists():
        return f"Konfigurace {path} neexistuje (HD_MODE=local). Viz HOMESERVER.md."
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        # Jako ssh: soubor se secrets čitelný pro ostatní raději vůbec nepoužít
        return f"{path} má práva {oct(mode)} – obsahuje secrets, nastav chmod 600."
    return None


def load_env_file(path: Path = ENV_FILE) -> None:
    """Načte konfiguraci do os.environ (proměnné už nastavené v prostředí mají přednost)."""
    problem = check_env_file(path)
    if problem:
        print(f"ERROR: {problem}")
        sys.exit(1)
    for key, value in parse_env_file(path.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)


def _atomic_write(path: Path, data: bytes) -> None:
    """Zápis do dočasného souboru ve stejném adresáři a pak os.replace().

    Čtenář (HTTP server, publish_data.sh) tak nikdy neuvidí napůl zapsaný soubor.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600 if path.suffix == ".enc" else 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: Path, obj) -> None:
    """Zapíše JSON stejně jako dřív write_text(json.dumps(..., indent=2)), jen atomicky."""
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))


def write_bytes(path: Path, data: bytes) -> None:
    _atomic_write(path, data)


if LOCAL:
    load_env_file()

if LOCAL:
    ensure_local_dirs()
else:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
