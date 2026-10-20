"""Static configuration: builds, aliases, symbol sources.

Everything here is data. Change a row, re-run `storm-re init`, done.
"""

from __future__ import annotations

import os
import tomllib
from functools import cache
from pathlib import Path

DEFAULT_MCP = "http://127.0.0.1:8770/mcp"
DEFAULT_BUILD = "s4"

# canonical alias -> Ghidra project program name
BUILDS: dict[str, dict] = {
    "s4": {
        "program": "/NSUNS4_release.exe-75912b",
        "aliases": ["s4-109", "s4-release", "storm4"],
        "game": "storm4",
        "desc": "Storm 4 1.09 Steam release",
    },
    "s4-debug": {
        "program": "/NSUNS4_debug_1.06.exe-bc53b3",
        "aliases": ["s4-106", "storm4-debug"],
        "game": "storm4",
        "desc": "Storm 4 debug 1.06",
    },
    "s4-107": {
        "program": "/NSUNS4_1.07.exe-da7563",
        "aliases": ["storm4-107"],
        "game": "storm4",
        "desc": "Storm 4 1.07",
    },
    "s3": {
        "program": "/NSUNS3.exe-a7124b",
        "aliases": ["s3hd", "storm3"],
        "game": "storm3",
        "desc": "Storm 3 Full Burst HD 64-bit",
    },
    "s3fb": {
        "program": "/NS3FB.exe-62ad97",
        "aliases": ["storm3fb"],
        "game": "storm3fb",
        "desc": "Storm 3 Full Burst 2014 32-bit",
    },
    "s2": {
        "program": "/NSUNS2.exe-abf2b6",
        "aliases": ["storm2"],
        "game": "storm2",
        "desc": "Storm 2",
    },
    "s1": {
        "program": "/NSUNS1.exe-a9fe00",
        "aliases": ["storm1"],
        "game": "storm1",
        "desc": "Storm 1 (modded import)",
    },
    "s1-clean": {
        "program": "/NSUNS1_steam_a68ea53d.exe-92b38e",
        "aliases": ["s1-steam", "storm1-clean"],
        "game": "storm1",
        "desc": "Storm 1 clean Steam exe (a68ea53d), names inherited from s1 by RVA",
        "symbol_fallback": "s1",
    },
    "s1-debug": {
        "program": "/NSUNS1_debug.exe-52c7ee",
        "aliases": [],
        "game": "storm1",
        "desc": "Storm 1 debug",
    },
    "connections": {
        "program": "/NSUNSC.exe-4749b3",
        "aliases": ["nsc", "storm-connections"],
        "game": "connections",
        "desc": "Storm Connections",
    },
    "revolution": {
        "program": "/NSUNSR.exe-4e31c2",
        "aliases": ["rev", "storm-revolution"],
        "game": "revolution",
        "desc": "Storm Revolution",
    },
    "trilogy": {
        "program": "/main-69612a",
        "aliases": ["switch", "switch-trilogy"],
        "game": None,
        "desc": "Switch Storm Trilogy NSO (arm64, full symbols)",
    },
}

# Manual name CSVs. Build attribution is explicit: NSUNS4.manual.csv disagrees
# with 1.09 at 0x82320 and is treated as 1.07.
MANUAL_SOURCES: list[tuple[str, str]] = [
    ("NSUNS4.manual.csv", "s4-107"),
    ("NSUNS4_1.09.manual.csv", "s4"),
    ("NSUNS4_release_109.manual.csv", "s4"),
    ("s4-1.09.manual.csv", "s4"),
    ("s4-1.09-adventure.manual.csv", "s4"),
]

SOURCE_RANK = {"manual": 3, "nucc": 2, "trilogy": 2, "ghidra": 1}
CONF_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}

# BSim TSV target executable -> build alias. Order matters (debug before plain).
TARGET_EXE_PATTERNS: list[tuple[str, str]] = [
    ("NSUNS4_debug_1.06", "s4-debug"),
    ("NSUNS4_release", "s4"),
    ("NSUNS4_1.07", "s4-107"),
    ("NSUNS1_debug", "s1-debug"),
    ("NSUNS1_steam", "s1-clean"),
    ("NSUNS1.exe", "s1"),
    ("NSUNS2.exe", "s2"),
    ("NSUNS3.exe", "s3"),
    ("NS3FB", "s3fb"),
    ("NSUNSC", "connections"),
    ("NSUNSR", "revolution"),
    ("main-69612a", "trilogy"),
]

# Fallback image bases if the DB row is missing.
BUILD_BASES: dict[str, int] = {
    "s4": 0x140000000,
    "s4-debug": 0x140000000,
    "s4-107": 0x140000000,
    "s3": 0x140000000,
    "s2": 0x140000000,
    "s1": 0x140000000,
    "s1-debug": 0x140000000,
    "s1-clean": 0x140000000,
    "connections": 0x140000000,
    "s3fb": 0x400000,
    "revolution": 0x400000,
    "trilogy": 0x7100000000,
}



def config_path() -> Path:
    env = os.environ.get("STORM_RE_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "storm-re" / "config.toml"


@cache
def file_config() -> dict:
    """Optional TOML config. Precedence: CLI flag > env var > this file > default."""
    path = config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _setting(env: str, key: str, default: str) -> str:
    return os.environ.get(env) or file_config().get(key) or default


# Ghidra program names carry a per-project hash suffix; [builds.<alias>] program
# in the config file points an alias at your own import.
for _alias, _over in file_config().get("builds", {}).items():
    if _alias in BUILDS:
        BUILDS[_alias].update(_over)

ALIASES: dict[str, str] = {}
for _canon, _meta in BUILDS.items():
    ALIASES[_canon] = _canon
    for _a in _meta["aliases"]:
        ALIASES[_a] = _canon


def canonical_build(name: str | None) -> str:
    if not name:
        return DEFAULT_BUILD
    key = name.strip().lower()
    if key not in ALIASES:
        raise KeyError(name)
    return ALIASES[key]


def mcp_url(override: str | None = None) -> str:
    return override or _setting("STORM_RE_MCP", "mcp_url", DEFAULT_MCP)


def db_path(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    env = _setting("STORM_RE_DB", "db", "")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return root / "storm-re" / "storm-re.db"


def nucc_root() -> Path:
    return Path(_setting("STORM_RE_NUCC", "nucc_root", "~/nucc-symbols")).expanduser()


def manual_root() -> Path:
    return Path(_setting("STORM_RE_MANUAL", "manual_root", "~/ghidra/storm-research")).expanduser()


def trilogy_tsv() -> Path:
    return Path(_setting("STORM_RE_TRILOGY_TSV", "trilogy_tsv", "~/ghidra/trilogy-dynsym.tsv")).expanduser()


def bsim_root() -> Path:
    return Path(_setting("STORM_RE_BSIM", "bsim_root", "~/ghidra/match/out")).expanduser()


def hot_json() -> Path:
    env = _setting("STORM_RE_HOT", "hot_json", "")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "hot.json"


# extracted CPK trees: <root>/<game>/<cpk dir relative to exe root>/<cpk name>/<entries>
ASSET_GAMES: dict[str, list[str]] = {
    "storm1": ["s1", "s1-clean"],
    "storm2": ["s2"],
    "storm3hd": ["s3", "s3hd", "storm3"],
    "storm3fb": ["s3fb"],
    "stormrev": ["rev", "revolution"],
    "storm4": ["s4", "s4-109", "s4-release"],
    "stormgen": ["gen", "generations"],
}


def asset_game(name: str) -> str:
    key = name.strip().lower()
    for game, aliases in ASSET_GAMES.items():
        if key == game or key in aliases:
            return game
    raise ValueError(f"unknown asset game {name!r} (use {', '.join(ASSET_GAMES)})")


def assets_root() -> Path:
    return Path(_setting("STORM_RE_ASSETS", "assets_root", "~/storm-cpk-extracted")).expanduser()


def assets_win_root() -> str:
    """Optional Windows mirror of assets_root, reported as win_path ("" = off)."""
    return _setting("STORM_RE_ASSETS_WIN", "assets_win_root", "")


def host_label() -> str:
    """Label stored with indexed programs (where the Ghidra project lives)."""
    return _setting("STORM_RE_HOST", "host", "local")
