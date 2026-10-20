"""Cache-first decompile fetch, shared by the CLI and the indexer."""

from __future__ import annotations

from .db import DB
from .mcp import MCPClient, MCPError
from .resolve import Resolution
from .summarize import summarize
from .text import fmt_addr

CACHE_KIND = "decompile"
CACHE_PARAMS = "v1:xrefs=1,callees=1,strings=1"


def get_name_version(db: DB, build: str) -> str:
    version = db.name_version(build)
    if not version or version == "0":
        version = db.set_symbol_version(build)
    return version


def has_code(raw: dict) -> bool:
    return bool((raw.get("code") or "").strip() or (raw.get("signature") or "").strip())


def load_decomp(
    db: DB,
    client: MCPClient | None,
    res: Resolution,
    *,
    refresh: bool = False,
    no_cache: bool = False,
) -> tuple[dict, dict]:
    """Return (raw, cache_info). Cache is keyed by sha+rva+name_version."""
    version = get_name_version(db, res.build)
    if not no_cache and not refresh:
        hit = db.cache_get(res.sha256, res.rva, CACHE_KIND, CACHE_PARAMS, version)
        if hit:
            if has_code(hit["raw"]):
                return hit["raw"], {
                    "hit": True,
                    "created_at": hit["created_at"],
                    "hit_count": hit["hit_count"],
                    "name_version": version,
                }
            # Poisoned entry from an older version or a bad address: drop it.
            db.cache_delete(res.sha256, res.rva, CACHE_KIND, CACHE_PARAMS, version)

    if client is None:
        raise MCPError("no backend client (use --refresh/--no-cache only with MCP access)")
    raw = client.call_tool(
        "decompile_function",
        {
            "binary_name": res.program,
            "name_or_address": fmt_addr(res.va),
            "include_xrefs": True,
            "include_callees": True,
            "include_strings": True,
            "timeout_sec": 300,
        },
        timeout=max(float(getattr(client, "timeout", 180)), 300),
    )
    if not isinstance(raw, dict):
        raise MCPError(f"unexpected decompile payload: {type(raw).__name__}")
    if raw.get("error"):
        raise MCPError(f"decompile failed: {raw['error']}")
    # A wrong address can come back as a "successful" empty result. Never cache
    # that: it poisons every later read for the same sha/rva/name_version.
    if not has_code(raw):
        raise MCPError(
            f"decompile returned no code for {fmt_addr(res.va)} "
            f"({res.program}, rva {fmt_addr(res.rva)})"
        )

    default_summary = summarize(raw, "summary")
    if not no_cache:
        db.cache_put(
            res.sha256,
            res.rva,
            CACHE_KIND,
            CACHE_PARAMS,
            version,
            raw,
            default_summary,
            default_summary["raw_chars"],
            default_summary["summary_chars"],
        )
    return raw, {
        "hit": False,
        "created_at": None,
        "hit_count": 0,
        "name_version": version,
    }
