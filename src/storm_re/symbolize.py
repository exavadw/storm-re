"""Rewrite Ghidra placeholder names using the build's symbol table."""

from __future__ import annotations

import re

from . import config
from .db import DB
from .text import fmt_addr

TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:(?P<thunk>thunk_))?"
    r"(?P<kind>FUN|SUB|DAT)_(?P<addr>[0-9a-fA-F]{4,16})\b"
)
_SAFE = re.compile(r"[^A-Za-z0-9_:~]")
_DUNDER = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)__([A-Za-z_][A-Za-z0-9_]*)\b"
)


def sanitize(name: str) -> str:
    """Make a symbol readable in C-like text, not necessarily compilable."""
    cleaned = _SAFE.sub("_", name.strip())
    return cleaned or name


def _placeholder(name: str) -> bool:
    return name.startswith(("FUN_", "SUB_", "LAB_", "UNK_", "DAT_", "thunk_FUN_"))


def symbolize_code(
    db: DB,
    build: str,
    code: str,
    base: int | None = None,
) -> tuple[str, list[dict], int]:
    """Return (rewritten_code, mapping, unresolved_unique_tokens)."""
    build_alias = config.canonical_build(build)
    if base is None:
        row = db.get_build(build_alias)
        if not row:
            raise KeyError(f"build {build_alias!r} is not initialized")
        base = int(row["base"] or 0)

    mapping: dict[str, dict] = {}
    unresolved: set[str] = set()

    def repl(match: re.Match) -> str:
        token = match.group(0)
        kind = match.group("kind")
        value = int(match.group("addr"), 16)
        rva = value - base if base and value >= base else value
        rows = db.symbols_at(build_alias, rva)
        if not rows:
            unresolved.add(token)
            return token
        best = rows[0]
        name = best["name"] or ""
        if not name or _placeholder(name):
            unresolved.add(token)
            return token
        shown = sanitize(name)
        if match.group("thunk"):
            shown = "thunk_" + shown
        mapping[token] = {
            "from": token,
            "to": shown,
            "rva": fmt_addr(rva),
            "name": name,
            "source": best["source"],
            "confidence": best["confidence"],
        }
        return shown

    rewritten = TOKEN_RE.sub(repl, code)

    # Ghidra sometimes stores a C++ name as Class__Method. Promote it to
    # Class::Method only when that exact name exists in the symbol table.
    def dunder(match: re.Match) -> str:
        token = match.group(0)
        candidate = f"{match.group(1)}::{match.group(2)}"
        rows = db.exact_symbols(build_alias, candidate)
        if not rows:
            return token
        best = rows[0]
        if (best["name"] or "") != candidate:
            return token
        mapping[token] = {
            "from": token,
            "to": candidate,
            "rva": fmt_addr(int(best["rva"])),
            "name": candidate,
            "source": best["source"],
            "confidence": best["confidence"],
        }
        return candidate

    rewritten = _DUNDER.sub(dunder, rewritten)
    return rewritten, list(mapping.values()), len(unresolved)
