"""Batch function diff between two builds, with PE byte-level change detection."""

from __future__ import annotations

import difflib
import os
import struct

from . import config
from .db import DB
from .decomp import load_decomp
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .summarize import summarize
from .text import fmt_addr


class PE:
    """Minimal PE reader: RVA -> file bytes, enough for function comparison."""

    def __init__(self, path: str):
        with open(path, "rb") as fh:
            self.data = fh.read()
        e = struct.unpack_from("<I", self.data, 0x3C)[0]
        if self.data[e : e + 4] != b"PE\0\0":
            raise ValueError(f"not a PE file: {path}")
        coff = e + 4
        nsec = struct.unpack_from("<H", self.data, coff + 2)[0]
        opt_size = struct.unpack_from("<H", self.data, coff + 16)[0]
        sect = coff + 20 + opt_size
        self.sections: list[tuple[int, int, int]] = []
        for i in range(nsec):
            _name, vsize, va, rawsize, rawptr = struct.unpack_from(
                "<8sIIII", self.data, sect + 40 * i
            )
            self.sections.append((va, max(vsize, rawsize), rawptr))

    def read(self, rva: int, size: int) -> bytes:
        size = max(16, min(size or 16, 8192))
        for va, span, rawptr in self.sections:
            if va <= rva < va + span:
                off = rawptr + (rva - va)
                return self.data[off : off + size]
        if 0 <= rva and rva + size <= len(self.data):
            return self.data[rva : rva + size]
        return b""


def _lines(code: str, cap: int = 2000) -> list[str]:
    return code.splitlines()[:cap]


def _file_for(db: DB, build: str) -> str | None:
    row = db.get_build(build)
    if not row:
        return None
    prog = db.conn.execute(
        "SELECT file_path FROM program WHERE name=?", (row["program"],)
    ).fetchone()
    if prog and prog["file_path"] and os.path.isfile(prog["file_path"]):
        return prog["file_path"]
    return None


def _symbolic(names_list) -> set[str]:
    return {
        n for n in names_list
        if not n.startswith(("FUN_", "thunk_FUN_", "SUB_", "LAB_"))
    }


def _pair_from_rows(
    db: DB,
    client: MCPClient | None,
    name: str,
    a,
    b,
    warnings: list[str],
) -> tuple[dict | None, bool]:
    try:
        raw_a, _ = load_decomp(db, client, a)
        raw_b, _ = load_decomp(db, client, b)
    except MCPError as exc:
        warnings.append(f"{name}: {exc}")
        return None, False
    code_a = raw_a.get("code") or ""
    code_b = raw_b.get("code") or ""
    if not code_a.strip() or not code_b.strip():
        warnings.append(f"{name}: no code in one build")
        return None, False
    sig_a = summarize(raw_a, "sig")["signature"]
    sig_b = summarize(raw_b, "sig")["signature"]
    similarity = difflib.SequenceMatcher(
        None, _lines(code_a), _lines(code_b), autojunk=False
    ).ratio()
    cal_a = _symbolic(raw_a.get("callees") or [])
    cal_b = _symbolic(raw_b.get("callees") or [])
    return {
        "name": name,
        "from": {"build": a.build, "rva": fmt_addr(a.rva), "signature": sig_a},
        "to": {"build": b.build, "rva": fmt_addr(b.rva), "signature": sig_b},
        "similarity": round(similarity, 4),
        "signature_equal": sig_a == sig_b,
        "changed": sig_a != sig_b or similarity < 0.995,
        "callees_only_from": sorted(cal_a - cal_b)[:12],
        "callees_only_to": sorted(cal_b - cal_a)[:12],
    }, True


def analyze_patch_diff(
    db: DB,
    client: MCPClient | None,
    from_build: str,
    to_build: str,
    *,
    limit: int = 20,
    seeds: str | None = None,
    include_same: bool = False,
    no_byte_diff: bool = False,
) -> dict:
    from_alias = config.canonical_build(from_build)
    to_alias = config.canonical_build(to_build)
    warnings: list[str] = []
    pairs: list[dict] = []

    file_a = None if no_byte_diff else _file_for(db, from_alias)
    file_b = None if no_byte_diff else _file_for(db, to_alias)
    byte_mode = bool(file_a and file_b)
    pe_a = pe_b = None
    if byte_mode:
        try:
            pe_a, pe_b = PE(file_a), PE(file_b)
        except (ValueError, OSError, struct.error) as exc:
            warnings.append(f"byte diff disabled: {exc}")
            byte_mode = False

    if seeds:
        names = [s.strip() for s in seeds.split(",") if s.strip()]
    else:
        names = [
            r["name"]
            for r in db.common_symbol_rows(
                from_alias, to_alias, limit * 1000 if byte_mode else limit * 3
            )
        ]

    stats = {
        "mode": "byte" if byte_mode else "text",
        "requested": len(names),
        "compared": 0,
        "byte_compared": 0,
        "changed": 0,
        "same": 0,
        "failed": 0,
    }

    if byte_mode:
        changed_rows = []
        rows = db.common_symbol_rows(from_alias, to_alias, 200000)
        if seeds:
            wanted = set(names)
            rows = [r for r in rows if r["name"] in wanted]
        stats["requested"] = len(rows)
        for row in rows:
            a_rva, b_rva = int(row["a_rva"]), int(row["b_rva"])
            a_bytes = pe_a.read(a_rva, int(row["a_size"] or 16))
            b_bytes = pe_b.read(b_rva, int(row["b_size"] or 16))
            if not a_bytes or not b_bytes:
                stats["failed"] += 1
                continue
            stats["byte_compared"] += 1
            if a_bytes == b_bytes:
                stats["same"] += 1
                if include_same and len(pairs) < limit:
                    pairs.append(
                        {
                            "name": row["name"],
                            "from": {"build": from_alias, "rva": fmt_addr(a_rva), "signature": ""},
                            "to": {"build": to_alias, "rva": fmt_addr(b_rva), "signature": ""},
                            "similarity": 1.0,
                            "signature_equal": True,
                            "changed": False,
                            "callees_only_from": [],
                            "callees_only_to": [],
                            "byte_diff": False,
                        }
                    )
            else:
                changed_rows.append((row, a_rva, b_rva))

        stats["changed"] = len(changed_rows)
        for row, a_rva, b_rva in changed_rows:
            if len(pairs) >= limit:
                break
            try:
                a = resolve(db, fmt_addr(a_rva), from_alias, addr_kind="rva")
                b = resolve(db, fmt_addr(b_rva), to_alias, addr_kind="rva")
            except ResolveError as exc:
                stats["failed"] += 1
                warnings.append(f"{row['name']}: {exc}")
                continue
            pair, ok = _pair_from_rows(db, client, row["name"], a, b, warnings)
            if pair is None:
                stats["failed"] += 1
                continue
            pair["byte_diff"] = True
            pairs.append(pair)
            if ok:
                stats["compared"] += 1
    else:
        if not seeds:
            names = names[:limit]
        compared = failed = 0
        for name in names:
            try:
                a = resolve(db, name, from_alias)
                b = resolve(db, name, to_alias)
            except ResolveError as exc:
                failed += 1
                warnings.append(f"{name}: {exc}")
                continue
            pair, ok = _pair_from_rows(db, client, name, a, b, warnings)
            if pair is None:
                failed += 1
                continue
            compared += 1
            if not pair["changed"] and not include_same:
                continue
            pairs.append(pair)
        stats["compared"] = compared
        stats["failed"] = failed
        stats["changed"] = sum(1 for p in pairs if p["changed"])
        stats["same"] = sum(1 for p in pairs if not p["changed"])

    pairs.sort(key=lambda p: (not p["changed"], p["name"]))
    stats["shown"] = len(pairs)
    return {
        "ok": True,
        "from_build": from_alias,
        "to_build": to_alias,
        "pairs": pairs,
        "stats": stats,
        "warnings": warnings,
        "notes": [
            "Byte mode compares function bytes at each common symbol's RVA, so call-site patches are found even when decompiled text is similar.",
            "For clean-vs-modded exe, both programs must be registered and their file paths present; s1-clean is the clean Steam exe.",
            "Text mode compares decompiled code when files are unavailable or --no-byte-diff is set.",
            "Similarity is line-based decompiled text, so renamed locals lower it.",
        ],
    }
