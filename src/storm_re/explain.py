"""One-call explanation of a function: resolve, decompile, symbolize, xrefs, map."""

from __future__ import annotations

from . import config
from .db import DB
from .decomp import load_decomp
from .mapper import map_name
from .mcp import MCPClient
from .resolve import resolve
from .summarize import summarize
from .symbolize import symbolize_code
from .text import fmt_addr, truncate


def explain(
    db: DB,
    client: MCPClient | None,
    target: str,
    build: str = "s4",
    *,
    max_bytes: int = 8000,
) -> dict:
    build_alias = config.canonical_build(build)
    res = resolve(db, target, build_alias)
    raw, info = load_decomp(db, client, res)
    summary = summarize(raw, "summary")
    code, mapping, unresolved = symbolize_code(
        db, build_alias, raw.get("code") or "", base=res.base
    )
    shown, truncated = truncate(code, max_bytes)
    name = res.name or target
    maps, missing = [], []
    for other in ("s4-debug", "s4-107", "s1", "s3"):
        if other == build_alias:
            continue
        try:
            mapped = map_name(db, name, build_alias, other)
        except Exception:
            mapped = None
        if mapped:
            maps.append(mapped)
        else:
            missing.append(other)
    return {
        "ok": True,
        "build": build_alias,
        "target": res.as_dict(),
        "signature": summary["signature"],
        "callers": summary["callers"],
        "callees": summary["callees"],
        "caller_count": summary["caller_count"],
        "callee_count": summary["callee_count"],
        "strings": summary["strings"],
        "data_refs": summary["data_refs"],
        "maps": [m.as_dict() for m in maps[:6]],
        "unmapped": missing,
        "code": shown,
        "truncated": truncated,
        "renamed": len(mapping),
        "unresolved": unresolved,
        "mapping": mapping,
        "cache": info,
        "notes": [
            "Static view; confirm runtime behavior with a replay trace/snap.",
            "Prefer this over separate resolve/decomp/symbolize/xrefs calls.",
        ],
    }
