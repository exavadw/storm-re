"""Hot-set indexer and local `show` queries."""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .db import DB
from .decomp import get_name_version, load_decomp
from .mapper import map_name
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .summarize import summarize
from .symbolize import symbolize_code
from .text import fmt_addr, fun_addr, is_hex


def load_hot(path: str | Path | None = None) -> dict:
    path = Path(path or config.hot_json()).expanduser()
    data = json.loads(path.read_text())
    topics: dict[str, dict] = {}
    for name, spec in (data.get("topics") or {}).items():
        if isinstance(spec, dict):
            targets = list(spec.get("targets") or [])
            builds = spec.get("builds")
        else:
            targets = list(spec or [])
            builds = None
        topics[name] = {"targets": targets, "builds": builds}
    defaults = data.get("default_builds") or ["s4", "s4-debug", "s4-107"]
    return {"topics": topics, "default_builds": defaults, "path": str(path)}


def index_topic(
    db: DB,
    client: MCPClient,
    topic: str,
    targets: list[str],
    builds: list[str],
    *,
    default_build: str = "s4",
    limit: int | None = None,
    refresh: bool = False,
) -> list[dict]:
    results: list[dict] = []
    attempts = 0
    for build in builds:
        build_alias = config.canonical_build(build)
        version = get_name_version(db, build_alias)
        build_row = db.get_build(build_alias)
        base = int(build_row["base"] or 0) if build_row else 0
        if refresh:
            db.index_clear(topic, build_alias)
        for target in targets:
            if limit is not None and attempts >= limit:
                return results
            attempts += 1
            via = ""
            is_addr = is_hex(target) or fun_addr(target) is not None
            try:
                if is_addr and build_alias != config.canonical_build(default_build):
                    # An address is build-specific. Only index another build if
                    # BSim maps it; never decompile the same RVA blindly.
                    mapped = map_name(db, target, default_build, build_alias, refresh=refresh)
                    if not mapped:
                        raise ResolveError(
                            f"address target has no map into {build_alias}"
                        )
                    res = resolve(db, fmt_addr(mapped.to_rva), build_alias, addr_kind="rva")
                    via = f"map:{mapped.method}"
                else:
                    res = resolve(db, target, build_alias)
            except ResolveError as exc:
                res = None
                if build_alias != config.canonical_build(default_build):
                    try:
                        mapped = map_name(db, target, default_build, build_alias, refresh=refresh)
                    except ResolveError:
                        mapped = None
                    if mapped:
                        try:
                            res = resolve(db, fmt_addr(mapped.to_rva), build_alias, addr_kind="rva")
                            via = f"map:{mapped.method}"
                        except ResolveError:
                            res = None
                if res is None:
                    db.index_delete_target(topic, build_alias, target)
                    db.index_put(
                        topic=topic,
                        build_alias=build_alias,
                        rva=0,
                        name=target,
                        target=target,
                        sha256="",
                        name_version=version,
                        signature="",
                        summary="{}",
                        text="",
                        raw_chars=0,
                        summary_chars=0,
                        status=f"missing: {exc}",
                    )
                    results.append(
                        {
                            "topic": topic,
                            "build": build_alias,
                            "target": target,
                            "name": target,
                            "rva": "",
                            "status": "missing",
                            "detail": str(exc),
                        }
                    )
                    continue

            entry_name = res.name or target
            existing = db.index_get_target(topic, build_alias, target)
            if (
                existing
                and existing["status"] == "ok"
                and existing["name_version"] == version
                and not refresh
            ):
                results.append(
                    {
                        "topic": topic,
                        "build": build_alias,
                        "target": target,
                        "name": entry_name,
                        "rva": fmt_addr(res.rva),
                        "status": "cached",
                        "detail": "",
                    }
                )
                continue

            try:
                raw, _info = load_decomp(db, client, res)
                summary = summarize(raw, "summary")
                sym_code, _sym_map, _sym_unresolved = symbolize_code(
                    db, build_alias, raw.get("code") or "", base=base
                )
                db.index_delete_target(topic, build_alias, target)
                db.index_put(
                    topic=topic,
                    build_alias=build_alias,
                    rva=res.rva,
                    name=entry_name,
                    target=target,
                    sha256=res.sha256,
                    name_version=version,
                    signature=summary["signature"],
                    summary=json.dumps(
                        {k: v for k, v in summary.items() if k != "text"},
                        separators=(",", ":"),
                    ),
                    text=summary["text"],
                    symbolized=sym_code,
                    raw_chars=summary["raw_chars"],
                    summary_chars=summary["summary_chars"],
                    status="ok",
                )
                results.append(
                    {
                        "topic": topic,
                        "build": build_alias,
                        "target": target,
                        "name": entry_name,
                        "rva": fmt_addr(res.rva),
                        "status": "ok",
                        "detail": via,
                        "saved_pct": summary["saved_pct"],
                    }
                )
            except MCPError as exc:
                db.index_delete_target(topic, build_alias, target)
                db.index_put(
                    topic=topic,
                    build_alias=build_alias,
                    rva=res.rva,
                    name=entry_name,
                    target=target,
                    sha256=res.sha256,
                    name_version=version,
                    signature="",
                    summary="{}",
                    text="",
                    raw_chars=0,
                    summary_chars=0,
                    status=f"error: {exc}",
                )
                results.append(
                    {
                        "topic": topic,
                        "build": build_alias,
                        "target": target,
                        "name": entry_name,
                        "rva": fmt_addr(res.rva),
                        "status": "error",
                        "detail": str(exc),
                    }
                )
    return results


def show_entries(
    db: DB, query: str, build: str | None = None, limit: int = 100
) -> list:
    build_alias = config.canonical_build(build) if build else None
    rows = db.index_list(topic=query, build_alias=build_alias, limit=limit)
    if rows:
        return rows
    rows = db.index_search(query, limit=limit)
    if build_alias:
        rows = [r for r in rows if r["build_alias"] == build_alias]
    return rows[:limit]
