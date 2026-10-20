"""Who writes an address or a root+offset, with evidence."""

from __future__ import annotations

from collections import defaultdict

from . import config
from .db import DB
from .decomp import load_decomp
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .surface import parse_surface, select_seeds
from .text import fmt_addr, fun_addr

KIND_ORDER = {"write": 0, "read": 1, "call": 2, "data": 3, "other": 4}


def _kind(xref_type: str) -> str:
    t = (xref_type or "").upper()
    if "WRITE" in t:
        return "write"
    if "READ" in t:
        return "read"
    if "CALL" in t:
        return "call"
    if t == "DATA":
        return "data"
    return "other"


def analyze_address(
    db: DB,
    client: MCPClient,
    target: str,
    build: str,
    *,
    include_reads: bool = False,
    include_calls: bool = False,
    limit: int = 100,
) -> dict:
    build_alias = config.canonical_build(build)
    res = resolve(db, target, build_alias)
    data = client.call_tool(
        "list_xrefs",
        {"binary_name": res.program, "name_or_address": fmt_addr(res.va)},
    )
    xrefs = data.get("cross_references", []) or []

    groups: dict[tuple, dict] = {}
    for x in xrefs:
        if not isinstance(x, dict):
            continue
        kind = _kind(str(x.get("type") or ""))
        if kind == "write":
            pass
        elif kind == "read" and not include_reads:
            continue
        elif kind == "call" and not include_calls:
            continue
        elif kind in ("data", "other") and not include_reads:
            continue
        fn = x.get("function_name")
        key = (kind, fn or x.get("from_address") or "?")
        g = groups.setdefault(
            key,
            {
                "kind": kind,
                "function": fn,
                "function_rva": "",
                "count": 0,
                "samples": [],
            },
        )
        g["count"] += 1
        addr = x.get("from_address")
        if addr and len(g["samples"]) < 2:
            g["samples"].append(f"@{addr}")
        if fn and not g["function_rva"]:
            rva = fun_addr(fn)
            if rva is not None:
                g["function_rva"] = fmt_addr(rva)

    sites = []
    for (kind, _key), g in groups.items():
        sites.append(
            {
                "kind": kind,
                "function": g["function"] or "(data)",
                "function_rva": g["function_rva"],
                "size": None,
                "count": g["count"],
                "confidence": "high",
                "confirmed_by": "ghidra-xref",
                "sample": " ".join(g["samples"]),
            }
        )
    sites.sort(key=lambda s: (KIND_ORDER.get(s["kind"], 9), -s["count"], s["function"]))
    sites = sites[:limit]

    stats = {
        "xrefs_total": len(xrefs),
        "sites": len(sites),
        "writers": sum(1 for s in sites if s["kind"] == "write"),
        "readers": sum(1 for s in sites if s["kind"] == "read"),
        "calls": sum(1 for s in sites if s["kind"] == "call"),
    }
    warnings = []
    if not sites:
        warnings.append(
            "no matching xrefs; try --include-reads, --include-calls, or the offset mode"
        )
    return {
        "ok": True,
        "mode": "address",
        "build": build_alias,
        "target": res.as_dict(),
        "root": None,
        "offset": None,
        "param": None,
        "sites": sites,
        "stats": stats,
        "warnings": warnings,
    }


def analyze_offset(
    db: DB,
    client: MCPClient | None,
    root: str,
    offset: int,
    build: str,
    *,
    include_reads: bool = False,
    limit: int = 100,
    seeds: str | None = None,
    param: str = "param_1",
) -> dict:
    build_alias = config.canonical_build(build)
    resolutions = select_seeds(db, build_alias, root, limit, seeds)
    groups: dict[tuple, dict] = {}
    warnings: list[str] = []
    analyzed = failed = matched = 0

    for res in resolutions:
        name = res.name or fmt_addr(res.rva)
        try:
            raw, _ = load_decomp(db, client, res)
        except MCPError as exc:
            failed += 1
            warnings.append(f"{name}: {exc}")
            continue
        code = raw.get("code") or ""
        if not code.strip():
            failed += 1
            continue
        analyzed += 1
        parsed, scale_unknown = parse_surface(code, param)
        if scale_unknown:
            warnings.append(f"{name}: unknown {param} element size; some accesses skipped")
        found = False
        for access in parsed:
            if access.offset != offset:
                continue
            found = True
            kind = "write" if access.write else "read"
            if kind == "read" and not include_reads:
                continue
            key = (kind, res.rva)
            g = groups.setdefault(
                key,
                {
                    "kind": kind,
                    "function": name,
                    "function_rva": fmt_addr(res.rva),
                    "sizes": set(),
                    "unknown": False,
                    "count": 0,
                    "samples": [],
                },
            )
            g["count"] += 1
            if access.size is None:
                g["unknown"] = True
            else:
                g["sizes"].add(access.size)
            if access.sample and len(g["samples"]) < 2:
                g["samples"].append(access.sample)
            if not access.scale_known:
                g["unknown"] = True
        if found:
            matched += 1

    sites = []
    for (kind, _rva), g in groups.items():
        sizes = sorted(g["sizes"])
        if len(sizes) == 1 and not g["unknown"]:
            size = sizes[0]
            confidence = "high"
        elif sizes:
            size = sizes
            confidence = "medium" if not g["unknown"] else "low"
        else:
            size = None
            confidence = "low"
        sites.append(
            {
                "kind": kind,
                "function": g["function"],
                "function_rva": g["function_rva"],
                "size": size,
                "count": g["count"],
                "confidence": confidence,
                "confirmed_by": "decompiled-pattern",
                "sample": " ".join(g["samples"]),
            }
        )
    sites.sort(key=lambda s: (KIND_ORDER.get(s["kind"], 9), -s["count"], s["function"]))
    sites = sites[:limit]

    if not sites:
        warnings.append(
            f"no {param} access at {fmt_addr(offset)} in the analysed seeds"
        )
    stats = {
        "seeds_requested": len(resolutions),
        "seeds_analyzed": analyzed,
        "seeds_matched": matched,
        "seeds_failed": failed,
        "sites": len(sites),
        "writers": sum(1 for s in sites if s["kind"] == "write"),
        "readers": sum(1 for s in sites if s["kind"] == "read"),
        "writes": sum(s["count"] for s in sites if s["kind"] == "write"),
        "reads": sum(s["count"] for s in sites if s["kind"] == "read"),
    }
    return {
        "ok": True,
        "mode": "offset",
        "build": build_alias,
        "root": root,
        "offset": fmt_addr(offset),
        "param": param,
        "target": None,
        "sites": sites,
        "stats": stats,
        "warnings": warnings,
    }


def write_sites(
    db: DB,
    client: MCPClient | None,
    target: str,
    build: str = "s4",
    *,
    offset: int | None = None,
    root: str | None = None,
    include_reads: bool = False,
    include_calls: bool = False,
    limit: int = 100,
    seeds: str | None = None,
    param: str = "param_1",
) -> dict:
    if offset is not None:
        if root is None:
            root = target
        return analyze_offset(
            db,
            client,
            root,
            offset,
            build,
            include_reads=include_reads,
            limit=limit,
            seeds=seeds,
            param=param,
        )
    return analyze_address(
        db,
        client,
        target,
        build,
        include_reads=include_reads,
        include_calls=include_calls,
        limit=limit,
    )
