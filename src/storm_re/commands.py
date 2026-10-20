"""CLI command implementations."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from . import assets, config, registry
from . import bsim as bsim_mod
from . import indexer
from .db import DB
from .mcp import MCPClient, MCPError
from .mapper import map_all, map_name
from .resolve import (
    NotFound,
    Resolution,
    get_build_row,
    resolve,
    resolve_pair,
)
from .summarize import summarize
from .surface import analyze as analyze_surface
from .writesites import write_sites as analyze_write_sites
from .inputpath import analyze_input_path
from .frametick import analyze_frame_tick
from .netsession import analyze_net_session
from .scenedispatch import analyze_scene_dispatch
from .patchdiff import analyze_patch_diff
from .export import build_report, write_report
from .explain import explain
from .symbolize import symbolize_code
from .text import fmt_addr, one_line, truncate
from .decomp import load_decomp


class DiffMissing(RuntimeError):
    exit_code = 4


# -- helpers ---------------------------------------------------------------


def emit(args, payload: dict, text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, **payload}, indent=2))
    else:
        print(text)


def open_db(args, create: bool = False) -> DB:
    path = config.db_path(getattr(args, "db", None))
    db = DB(path, create=create)
    db.init_schema()
    return db


def make_client(args) -> MCPClient:
    return MCPClient(
        config.mcp_url(getattr(args, "mcp", None)),
        timeout=float(getattr(args, "timeout", 180)),
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [fmt.format(*headers), fmt.format(*["-" * w for w in widths])]
    out.extend(fmt.format(*[str(c) for c in row]) for row in rows)
    return "\n".join(out)


def _resolution_text(res: Resolution) -> str:
    lines = [
        f"build    {res.build}  {res.program}",
        f"sha      {res.sha256[:12]}",
        f"rva      {fmt_addr(res.rva)}",
        f"va       {fmt_addr(res.va)}",
        f"name     {res.name or '(no symbol)'}",
        f"source   {res.source}" + (f" ({res.confidence})" if res.confidence else ""),
    ]
    if res.conflicts:
        lines.append("conflicts:")
        for c in res.conflicts:
            lines.append(
                f"  {c['rva']}  {c['name']}  [{c['source']} {c['confidence']}]"
            )
    for note in res.notes:
        lines.append(f"note     {note}")
    return "\n".join(lines)


def cmd_init(args) -> int:
    db = open_db(args, create=True)
    db.init_schema()
    client = make_client(args)
    if not getattr(args, "quiet", False):
        print(f"backend  {client.url}")
        print(f"database {db.path}")
    result = registry.init_registry(db, client, quiet=getattr(args, "quiet", False))
    rows = []
    for b in db.list_builds():
        rows.append(
            [
                b["alias"],
                b["program"],
                (b["sha256"] or "")[:12],
                fmt_addr(b["base"] or 0),
                b["symbols"],
                b["cache_entries"],
                "yes" if b["present"] else "absent",
            ]
        )
    text = _table(
        ["alias", "program", "sha", "base", "symbols", "cache", "present"], rows
    )
    emit(args, {"builds": [dict(b) for b in db.list_builds()], "init": result}, text)
    return 0


def cmd_builds(args) -> int:
    db = open_db(args)
    rows = []
    for b in db.list_builds():
        rows.append(
            [
                b["alias"],
                b["program"],
                (b["sha256"] or "")[:12],
                fmt_addr(b["base"] or 0),
                b["symbols"],
                b["cache_entries"],
                "yes" if b["present"] else "absent",
            ]
        )
    text = _table(
        ["alias", "program", "sha", "base", "symbols", "cache", "present"], rows
    )
    emit(args, {"builds": [dict(b) for b in db.list_builds()]}, text)
    return 0


def cmd_resolve(args) -> int:
    db = open_db(args)
    res = resolve(db, args.target, args.build, getattr(args, "addr_kind", None))
    emit(args, res.as_dict(), _resolution_text(res))
    return 0


def cmd_decomp(args) -> int:
    db = open_db(args)
    client = make_client(args)
    res = resolve(db, args.target, args.build, getattr(args, "addr_kind", None))
    raw, info = load_decomp(
        db,
        client,
        res,
        refresh=getattr(args, "refresh", False),
        no_cache=getattr(args, "no_cache", False),
    )
    summary = summarize(
        raw,
        detail=args.detail,
        max_bytes=args.max_bytes,
        head=args.head,
    )
    cache_line = (
        f"cache    {'hit' if info['hit'] else 'miss'}"
        f" (name_version {info['name_version']}, hits {info['hit_count']})"
    )
    text = "\n".join([_resolution_text(res), cache_line, "", summary["text"]])
    payload = {
        **res.as_dict(),
        "detail": args.detail,
        "signature": summary["signature"],
        "cache": info,
        "summary": {k: v for k, v in summary.items() if k != "text"},
        "text": summary["text"],
    }
    emit(args, payload, text)
    return 0


def cmd_xrefs(args) -> int:
    db = open_db(args)
    client = make_client(args)
    res = resolve(db, args.target, args.build, getattr(args, "addr_kind", None))
    raw, _ = load_decomp(db, client, res, no_cache=getattr(args, "no_cache", False))
    limit = max(1, args.limit)

    entries: list[dict] = []
    seen: set[tuple] = set()
    if args.direction in ("to", "both"):
        for x in raw.get("xrefs") or []:
            if not isinstance(x, dict):
                continue
            fn = x.get("function_name")
            xtype = str(x.get("type") or "")
            key = ("call", fn) if fn else ("data", x.get("from_address"), xtype)
            if key in seen:
                continue
            seen.add(key)
            if fn:
                entries.append(
                    {
                        "kind": "caller",
                        "function": fn,
                        "from": x.get("from_address"),
                        "type": xtype,
                    }
                )
            else:
                entries.append(
                    {
                        "kind": "data",
                        "from": x.get("from_address"),
                        "type": xtype,
                    }
                )
    if args.direction in ("from", "both"):
        for c in raw.get("callees") or []:
            key = ("callee", c)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"kind": "callee", "function": c})

    total = len(entries)
    entries = entries[:limit]
    lines = [_resolution_text(res), f"xrefs    {args.direction} ({total} unique, showing {len(entries)})"]
    for e in entries:
        if e["kind"] == "callee":
            lines.append(f"  -> {e['function']}")
        elif e["kind"] == "caller":
            lines.append(f"  <- {e['function']}  [{e['type']} @{e['from']}]")
        else:
            lines.append(f"  <- data {e['type']} @{e['from']}")
    emit(
        args,
        {**res.as_dict(), "direction": args.direction, "total": total, "xrefs": entries},
        "\n".join(lines),
    )
    return 0


def _lines(code: str, cap: int = 2000) -> list[str]:
    lines = code.splitlines()
    return lines[:cap]


def cmd_diff(args) -> int:
    db = open_db(args)
    client = make_client(args)
    mapping = None
    try:
        if getattr(args, "use_map", False):
            a = resolve(db, args.target, args.from_build)
            mapping = map_name(db, a.name or args.target, args.from_build, args.to_build)
            if not mapping:
                raise DiffMissing(
                    f"no map for {args.target!r} from {args.from_build} to {args.to_build}"
                )
            b = resolve(
                db, fmt_addr(mapping.to_rva), args.to_build, addr_kind="rva"
            )
            by_addr = False
        else:
            a, b, by_addr = resolve_pair(db, args.target, args.from_build, args.to_build)
    except NotFound as exc:
        raise DiffMissing(str(exc)) from exc
    try:
        raw_a, _ = load_decomp(db, client, a, no_cache=getattr(args, "no_cache", False))
    except (NotFound, MCPError) as exc:
        raise DiffMissing(f"{a.build}: {exc}") from exc
    try:
        raw_b, _ = load_decomp(db, client, b, no_cache=getattr(args, "no_cache", False))
    except (NotFound, MCPError) as exc:
        raise DiffMissing(f"{b.build}: {exc}") from exc

    sig_a = summarize(raw_a, "sig")["signature"]
    sig_b = summarize(raw_b, "sig")["signature"]
    code_a = raw_a.get("code") or ""
    code_b = raw_b.get("code") or ""
    if not code_a.strip() or not code_b.strip():
        raise DiffMissing(
            f"no code to compare: {a.build} {len(code_a)} chars, "
            f"{b.build} {len(code_b)} chars (name may be a false positive; "
            "try the alternative RVA from `resolve`)"
        )
    lines_a, lines_b = _lines(code_a), _lines(code_b)
    similarity = (
        difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False).ratio()
        if lines_a and lines_b
        else 0.0
    )

    def symbolic(names) -> set[str]:
        return {n for n in names if not n.startswith(("FUN_", "thunk_FUN_", "SUB_", "LAB_"))}

    cal_a = symbolic(raw_a.get("callees") or [])
    cal_b = symbolic(raw_b.get("callees") or [])
    only_a = sorted(cal_a - cal_b)
    only_b = sorted(cal_b - cal_a)

    changed: list[str] = []
    diff = difflib.unified_diff(
        lines_a, lines_b, fromfile=a.build, tofile=b.build, lineterm="", n=0
    )
    for line in diff:
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            changed.append(line)
        if len(changed) >= 20:
            break

    payload = {
        "target": args.target,
        "by_address": by_addr,
        "map": mapping.as_dict() if mapping else None,
        "from": a.as_dict(),
        "to": b.as_dict(),
        "signature_equal": sig_a == sig_b,
        "signature_from": sig_a,
        "signature_to": sig_b,
        "similarity": round(similarity, 4),
        "code_lines_from": len(lines_a),
        "code_lines_to": len(lines_b),
        "callees_only_from": only_a,
        "callees_only_to": only_b,
        "changed_preview": changed,
    }
    lines = [
        f"target   {args.target}" + ("  (same RVA in both builds)" if by_addr else "  (resolved by name in each build)"),
        f"from     {a.build}  {fmt_addr(a.rva)}  {a.name or '(no symbol)'}  sha {a.sha256[:12]}",
        f"to       {b.build}  {fmt_addr(b.rva)}  {b.name or '(no symbol)'}  sha {b.sha256[:12]}",
        *(
            [f"map      {mapping.method} score {mapping.score:.3f} ({mapping.confidence})"]
            if mapping
            else []
        ),
        f"signature {'same' if sig_a == sig_b else 'DIFFERENT'}",
        f"similarity {similarity:.3f}  lines {len(lines_a)} -> {len(lines_b)}",
    ]
    if only_a:
        lines.append(f"only in {a.build}: " + ", ".join(only_a[:15]))
    if only_b:
        lines.append(f"only in {b.build}: " + ", ".join(only_b[:15]))
    if changed:
        lines.append("changed lines:")
        lines.extend(f"  {c}" for c in changed[:20])
    emit(args, payload, "\n".join(lines))
    return 0


def cmd_find(args) -> int:
    db = open_db(args)
    build = config.canonical_build(args.build)
    query = args.query.strip()
    if not query:
        raise NotFound("empty query")
    limit = max(1, args.limit)

    if args.mode == "symbol":
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = db.like_symbols(build, f"%{escaped}%", limit=500)
        q = query.casefold()
        ranked = []
        for r in rows:
            name = (r["name"] or "").casefold()
            short = (r["short_name"] or "").casefold()
            if name == q:
                rank = 0
            elif short == q:
                rank = 1
            elif name.startswith(q):
                rank = 2
            elif short.startswith(q):
                rank = 3
            else:
                rank = 4
            ranked.append((rank, -int(r["source_rank"] or 0), -int(r["conf_rank"] or 0), r))
        ranked.sort(key=lambda t: t[:3])
        out, seen = [], set()
        for rank, _s, _c, r in ranked:
            key = (r["rva"], r["name"])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "rva": fmt_addr(r["rva"]),
                    "name": r["name"],
                    "confidence": r["confidence"],
                    "source": r["source"],
                }
            )
            if len(out) >= limit:
                break
        rows_text = [f"  {x['rva']}  {x['name']}  [{x['source']} {x['confidence']}]" for x in out]
        text = "\n".join([f"build    {build}", f"find     {query} ({len(out)} shown)"] + rows_text)
        emit(args, {"build": build, "query": query, "mode": "symbol", "results": out}, text)
        return 0

    client = make_client(args)
    program = _program(db, build)
    if args.mode == "string":
        data = client.call_tool(
            "search_strings",
            {"binary_name": program, "query": query, "limit": limit},
        )
        results = data.get("strings", [])
        text = "\n".join(
            [f"build    {build}", f"strings  {query} ({len(results)})"]
            + [f"  {s.get('value')!r} @{s.get('address')}" for s in results]
        )
        emit(args, {"build": build, "query": query, "mode": "string", "results": results}, text)
        return 0

    if args.mode == "code":
        data = client.call_tool(
            "search_code",
            {
                "binary_name": program,
                "query": query,
                "search_mode": "semantic" if args.semantic else "literal",
                "include_full_code": False,
                "limit": limit,
            },
        )
        results = data.get("results", [])
        text = "\n".join(
            [f"build    {build}", f"code     {query} ({len(results)})"]
            + [
                f"  {r.get('function_name') or r.get('name') or '?'}  "
                f"{r.get('address', '')}  {str(r.get('preview') or r.get('snippet') or '')[:120]}"
                for r in results
            ]
        )
        emit(args, {"build": build, "query": query, "mode": "code", "results": results}, text)
        return 0

    raise ValueError(f"unknown mode {args.mode!r}")


def _program(db: DB, build: str) -> str:
    _canonical, row = get_build_row(db, build)
    return row["program"]


def cmd_bsim(args) -> int:
    db = open_db(args)
    if args.action == "ingest":
        result = bsim_mod.ingest(
            db,
            args.root,
            top_k=args.top,
            min_sim=args.min_sim,
            quiet=getattr(args, "quiet", False),
        )
        rows = [
            [b, n]
            for b, n in sorted(result.get("per_build", {}).items())
        ]
        text = _table(["build", "bsim edges"], rows) if rows else "no BSim TSVs found"
        emit(args, result, text)
        return 0

    rows = db.conn.execute(
        """SELECT build_alias, COUNT(*) AS n, AVG(similarity) AS avg_sim
           FROM bsim_edge GROUP BY build_alias ORDER BY build_alias"""
    ).fetchall()
    table_rows = [
        [r["build_alias"], r["n"], f"{r['avg_sim']:.3f}" if r["avg_sim"] else ""]
        for r in rows
    ]
    text = _table(["build", "edges", "avg similarity"], table_rows)
    emit(
        args,
        {
            "action": "stat",
            "edges": db.bsim_count(),
            "builds": [dict(r) for r in rows],
        },
        text,
    )
    return 0


def cmd_map(args) -> int:
    db = open_db(args)
    if args.to:
        targets = [x.strip() for x in args.to.split(",") if x.strip()]
        results, missing = [], []
        for target in targets:
            mapped = map_name(
                db, args.name, args.from_build, target, refresh=getattr(args, "refresh", False)
            )
            if mapped:
                results.append(mapped)
            else:
                missing.append(target)
        results.sort(key=lambda r: -r.score)
    else:
        results, missing = map_all(
            db, args.name, args.from_build, refresh=getattr(args, "refresh", False)
        )

    rows = [
        [
            r.to_build,
            fmt_addr(r.to_rva),
            r.to_name or "",
            r.method,
            f"{r.score:.3f}",
            r.confidence,
        ]
        for r in results
    ]
    lines = [
        f"name     {args.name}",
        f"from     {config.canonical_build(args.from_build)}  {fmt_addr(results[0].from_rva) if results else '?'}",
        "",
        _table(["to", "rva", "name", "method", "score", "conf"], rows)
        if rows
        else "no map candidates",
    ]
    if missing:
        lines.append(f"unmapped: {', '.join(missing)}")
    emit(
        args,
        {
            "name": args.name,
            "from_build": config.canonical_build(args.from_build),
            "maps": [r.as_dict() for r in results],
            "unmapped": missing,
        },
        "\n".join(lines),
    )
    return 0


def cmd_index(args) -> int:
    db = open_db(args)
    hot = indexer.load_hot()
    topic_names = [args.topic] if args.topic else list(hot["topics"])
    if args.topic and args.topic not in hot["topics"]:
        raise ValueError(
            f"unknown topic {args.topic!r}; known: {', '.join(hot['topics'])}"
        )
    client = make_client(args)
    results: list[dict] = []
    for topic in topic_names:
        spec = hot["topics"][topic]
        builds = args.build or spec.get("builds") or hot["default_builds"]
        results.extend(
            indexer.index_topic(
                db,
                client,
                topic,
                spec["targets"],
                builds,
                default_build=hot["default_builds"][0],
                limit=args.limit,
                refresh=getattr(args, "refresh", False),
            )
        )

    rows = [
        [
            r["topic"],
            r["build"],
            r.get("name", ""),
            r.get("rva", ""),
            r["status"],
            one_line(r.get("detail", ""), 80),
        ]
        for r in results
    ]
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    text = _table(["topic", "build", "name", "rva", "status", "detail"], rows)
    text += "\n" + "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    emit(args, {"results": results, "counts": counts}, text)
    return 0


def cmd_show(args) -> int:
    db = open_db(args)
    rows = indexer.show_entries(db, args.query, args.build, args.limit)
    if not rows:
        raise NotFound(f"no indexed entries for {args.query!r} (run `storm-re index`)")
    entries = []
    blocks = []
    for r in rows:
        saved = (
            round(100.0 * (1 - r["summary_chars"] / r["raw_chars"]), 1)
            if r["raw_chars"]
            else 0.0
        )
        use_symbolized = bool(getattr(args, "symbolized", False) and r["symbolized"])
        body = r["symbolized"] if use_symbolized else r["text"]
        body, truncated = truncate(body, getattr(args, "max_bytes", 12000))
        entries.append(
            {
                "topic": r["topic"],
                "build": r["build_alias"],
                "rva": fmt_addr(r["rva"]),
                "name": r["name"],
                "status": r["status"],
                "signature": r["signature"],
                "saved_pct": saved,
                "symbolized": use_symbolized,
                "truncated": truncated,
                "text": body,
            }
        )
        blocks.append(
            f"[{r['topic']}] {r['build_alias']} {fmt_addr(r['rva'])} "
            f"{r['name']}  ({r['status']}, saved {saved}%)"
            + ("  [symbolized]" if use_symbolized else "")
        )
        if body:
            blocks.append(body)
        blocks.append("")
    emit(args, {"entries": entries}, "\n".join(blocks).rstrip())
    return 0


def cmd_symbolize(args) -> int:
    db = open_db(args)
    client = make_client(args)
    res = resolve(db, args.target, args.build, getattr(args, "addr_kind", None))
    raw, info = load_decomp(
        db,
        client,
        res,
        refresh=getattr(args, "refresh", False),
        no_cache=getattr(args, "no_cache", False),
    )
    code = raw.get("code") or ""
    if not code.strip():
        raise MCPError(f"no code for {args.target!r}")
    symbolized, mapping, unresolved = symbolize_code(db, res.build, code, base=res.base)
    shown, truncated = truncate(symbolized, args.max_bytes)
    if args.write:
        path = Path(args.write).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(symbolized)
    header = "\n".join(
        [
            f"build    {res.build}  {res.program}",
            f"rva      {fmt_addr(res.rva)}",
            f"name     {res.name or '(no symbol)'}",
            f"renamed  {len(mapping)}   unresolved {unresolved}"
            + ("   (truncated)" if truncated else ""),
        ]
    )
    text = shown if getattr(args, "no_header", False) else header + "\n\n" + shown
    payload = {
        **res.as_dict(),
        "renamed": len(mapping),
        "unresolved": unresolved,
        "mapping": mapping,
        "truncated": truncated,
        "code": shown,
        "write": args.write,
        "cache": info,
    }
    emit(args, payload, text)
    return 0


def cmd_state_surface(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = analyze_surface(
        db,
        client,
        args.root,
        args.build,
        limit=args.limit,
        max_offset=args.max_offset,
        param=args.param,
        seeds=args.seeds,
        min_writes=args.min_writes,
    )
    fields = result["fields"][: args.max_fields]
    rows = []
    for f in fields:
        size = f["size"]
        if isinstance(size, list):
            size = "/".join(str(x) for x in size) if size else "?"
        elif size is None:
            size = "?"
        rows.append(
            [
                f["offset"],
                size,
                f["kind"],
                len(f["functions"]),
                f["confidence"],
                one_line(f["sample"], 90),
            ]
        )
    stats = result["stats"]
    lines = [
        f"root     {result['root']}",
        f"build    {result['build']}  ({result.get('param') or 'param_1'})",
        f"seeds    {stats['seeds_analyzed']} analyzed, "
            f"{stats.get('seeds_matched', 0)} matched, {stats['seeds_failed']} failed",
        f"fields   {stats['fields_total']} total, {stats['writable']} writable, "
        f"{stats['read_only']} read-only  ({stats['reads']} reads, {stats['writes']} writes)",
        "",
        _table(["offset", "size", "r/w", "funcs", "conf", "sample"], rows)
        if rows
        else "no fields found",
    ]
    if result["warnings"]:
        lines.append(f"warnings: {len(result['warnings'])} (see --json)")
    lines.append("note: static inference; confirm with a replay trace/snap.")
    emit(args, {**result, "shown": len(fields)}, "\n".join(lines))
    return 0


def cmd_write_sites(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = analyze_write_sites(
        db,
        client,
        args.target,
        args.build,
        offset=args.offset,
        root=args.root,
        include_reads=args.include_reads,
        include_calls=args.include_calls,
        limit=args.limit,
        seeds=args.seeds,
        param=args.param,
    )
    rows = []
    for s in result["sites"]:
        size = s["size"]
        if isinstance(size, list):
            size = "/".join(str(x) for x in size) if size else "?"
        elif size is None:
            size = "?"
        rows.append(
            [
                s["kind"],
                s["function"],
                s["function_rva"],
                size,
                s["count"],
                s["confidence"],
                one_line(s["sample"], 80),
            ]
        )
    stats = result["stats"]
    if result["mode"] == "offset":
        header = [
            f"root     {result['root']}  + {result['offset']}",
            f"build    {result['build']}  ({result.get('param') or 'param_1'})",
        ]
        detail = (
            f"seeds    {stats['seeds_analyzed']} analyzed, "
            f"{stats.get('seeds_matched', 0)} matched, {stats['seeds_failed']} failed"
        )
    else:
        t = result["target"]
        header = [
            f"target   {t['build']}  {t['rva']}  {t['name'] or '(no symbol)'}",
            f"build    {result['build']}",
        ]
        detail = f"xrefs    {stats['xrefs_total']} total"
    lines = header + [
        detail,
        f"sites    {stats['sites']}  (writers {stats['writers']}, readers {stats['readers']})",
        "",
        _table(["kind", "function", "rva", "size", "n", "conf", "sample"], rows)
        if rows
        else "no sites found",
    ]
    if result["warnings"]:
        lines.append(f"warnings: {'; '.join(result['warnings'][:3])}")
    emit(args, result, "\n".join(lines))
    return 0


def cmd_input_path(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = analyze_input_path(
        db, client, args.build, depth=args.depth, limit=args.limit
    )
    stats = result["stats"]
    lines = [
        f"build    {result['build']}",
        f"graph    {stats['seeds']} seeds, {stats['nodes']} nodes, "
        f"{stats['edges']} edges ({stats['verified_edges']} verified), {stats['gates']} gates",
        "",
        "seeds:",
    ]
    for s in result["seeds"]:
        lines.append(f"  {s['role']:<10} {s['rva']:<10} {s['name']}")
    lines.append("gates:")
    for g in result["gates"]:
        loc = g["rva"] or "(not in this build)"
        lines.append(f"  {loc:<10} {g['name'] or ''}  {g['note']}")
    lines.append("button bits: " + ", ".join(f"{k}={v:#x}" for k, v in result["button_bits"].items()))
    lines.append("known chain (docs/reference, inferred):")
    for i, step in enumerate(result["known_chain"], 1):
        lines.append(f"  {i}. {step}")
    if result["paths"]:
        lines.append("verified direct paths:")
        for path in result["paths"]:
            lines.append("  " + " -> ".join(path))
    if result["warnings"]:
        lines.append(f"warnings: {len(result['warnings'])} (see --json)")
    emit(args, result, "\n".join(lines))
    return 0


def cmd_frame_tick(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = analyze_frame_tick(db, client, args.build, limit=args.limit, seeds=args.seeds)
    stats = result["stats"]
    rows = []
    for f in result["functions"]:
        sample = f["idioms"][0]["line"] if f["idioms"] else (f["fps_sources"][0] if f["fps_sources"] else "")
        rows.append(
            [
                f["name"],
                f["rva"],
                len(f["idioms"]),
                len(f["constants"]),
                f["confidence"],
                one_line(sample, 80),
            ]
        )
    lines = [
        f"build    {result['build']}",
        f"scan     {stats['seeds_analyzed']} analyzed, {stats['seeds_failed']} failed; "
        f"{stats['functions_with_idioms']} functions with idioms, {stats['idioms']} idioms, "
        f"{stats['constants']} per-frame constants",
        "",
        _table(["function", "rva", "idioms", "consts", "conf", "sample"], rows)
        if rows
        else "no timer idioms found",
    ]
    for note in result["notes"]:
        lines.append(f"note: {note}")
    if result["warnings"]:
        lines.append(f"warnings: {len(result['warnings'])} (see --json)")
    emit(args, result, "\n".join(lines))
    return 0


def cmd_net_session(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = analyze_net_session(
        db, client, args.build, limit=args.limit, seeds=args.seeds,
        include_imports=not args.no_imports,
    )
    rows = [
        [f["direction"], f["layer"], f["name"], f["rva"], f["callees"]]
        for f in result["functions"]
    ]
    stats = result["stats"]
    lines = [
        f"build    {result['build']}",
        f"scan     {stats['seeds_analyzed']} analyzed, {stats['seeds_failed']} failed; "
        f"{stats['functions']} functions, {stats['edges']} edges, "
        f"{stats['steam_interfaces']} Steam imports",
        "by direction: " + ", ".join(f"{k}={v}" for k, v in sorted(stats["by_direction"].items())),
        "",
        _table(["dir", "layer", "function", "rva", "callees"], rows)
        if rows
        else "no ccNet functions found",
    ]
    if result["steam_interfaces"]:
        lines.append("steam imports: " + ", ".join(result["steam_interfaces"][:20]))
    for note in result["notes"]:
        lines.append(f"note: {note}")
    emit(args, result, "\n".join(lines))
    return 0


def cmd_scene_dispatch(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = analyze_scene_dispatch(db, client, args.build, limit=args.limit, seeds=args.seeds)
    rows = [
        [f["role"], f["name"], f["rva"], len(f["strings"]), len(f["stage_names"]), len(f["callers"])]
        for f in result["functions"]
    ]
    stats = result["stats"]
    lines = [
        f"build    {result['build']}",
        f"scan     {stats['seeds_analyzed']} analyzed, {stats['seeds_failed']} failed; "
        f"{stats['functions']} functions, {stats['stage_names']} stage names",
        "",
        _table(["role", "function", "rva", "strings", "stages", "callers"], rows)
        if rows
        else "no scene functions found",
    ]
    if result["message_lookup"]:
        ml = result["message_lookup"]
        lines.append(f"message  {ml['name']}  {ml['rva']}  callers={len(ml['callers'])}")
    for sid in result["scene_ids"]:
        lines.append(f"scene id {sid['id']}  {sid['name']}  ({sid['source']}, {sid['confidence']})")
    for note in result["notes"]:
        lines.append(f"note: {note}")
    emit(args, result, "\n".join(lines))
    return 0


def cmd_patch_diff(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = analyze_patch_diff(
        db, client, args.from_build, args.to_build,
        limit=args.limit, seeds=args.seeds, include_same=args.include_same,
        no_byte_diff=args.no_byte_diff,
    )
    rows = [
        [
            p["name"],
            p["from"]["rva"],
            p["to"]["rva"],
            f"{p['similarity']:.3f}",
            "yes" if p["signature_equal"] else "no",
            "CHANGED" if p["changed"] else "same",
        ]
        for p in result["pairs"]
    ]
    stats = result["stats"]
    lines = [
        f"from     {result['from_build']}",
        f"to       {result['to_build']}",
        f"mode     {stats['mode']}  (byte compared {stats['byte_compared']})",
        f"compared {stats['compared']}  changed {stats['changed']}  same {stats['same']}  failed {stats['failed']}",
        "",
        _table(["function", "from", "to", "sim", "sig", "state"], rows)
        if rows
        else "no common functions compared",
    ]
    for note in result["notes"]:
        lines.append(f"note: {note}")
    emit(args, result, "\n".join(lines))
    return 0


def cmd_export(args) -> int:
    db = open_db(args)
    markdown, meta = build_report(
        db, args.topic, build=args.build, limit=args.limit, include_code=args.code
    )
    out = args.out or f"storm-re-{args.topic}.md"
    path = write_report(markdown, out)
    payload = {**meta, "path": path}
    if out == "-":
        payload["markdown"] = markdown
        if getattr(args, "json", False):
            emit(args, payload, "")
        else:
            print(markdown)
        return 0
    if getattr(args, "json", False):
        emit(args, payload, "")
    else:
        print(f"wrote {path} ({meta['bytes']} bytes, {len(meta['entries'])} entries)")
    return 0


def cmd_explain(args) -> int:
    db = open_db(args)
    client = make_client(args)
    result = explain(db, client, args.target, args.build, max_bytes=args.max_bytes)
    lines = [
        f"build    {result['build']}  {result['target']['program']}",
        f"rva      {result['target']['rva']}  va {result['target']['va']}",
        f"name     {result['target']['name'] or '(no symbol)'}",
        f"signature {result['signature']}",
        f"callers  {result['caller_count']}  callees {result['callee_count']}  "
        f"renamed {result['renamed']}  unresolved {result['unresolved']}",
    ]
    if result["maps"]:
        lines.append("maps:")
        for m in result["maps"]:
            lines.append(f"  {m['to_build']:<10} {m['to_rva']:<10} {m['method']:<12} {m['score']:.2f} {m['confidence']}")
    if result["unmapped"]:
        lines.append("unmapped: " + ", ".join(result["unmapped"]))
    lines.append("")
    lines.append(result["code"])
    emit(args, result, "\n".join(lines))
    return 0


def cmd_stat(args) -> int:
    db = open_db(args)
    stats = db.stats()
    stats["builds"] = len(db.list_builds())
    text = "\n".join(
        [
            f"database       {stats['db']}",
            f"size           {stats['db_bytes'] / 1e6:.1f} MB",
            f"builds         {stats['builds']}",
            f"symbols        {stats['symbols']}",
            f"cache entries  {stats['cache_entries']}  ({stats['cache_blob_bytes'] / 1e6:.1f} MB raw)",
            f"cache hits     {stats['cache_hits']}",
            f"raw chars      {stats['raw_chars']}",
            f"summary chars  {stats['summary_chars']}",
            f"saved          {stats['saved_pct']}%",
            f"bsim edges     {stats['bsim_edges']}",
            f"build maps     {stats['build_maps']}",
            f"index entries  {stats['index_entries']}",
        ]
    )
    emit(args, stats, text)
    return 0


def cmd_asset_index(args) -> int:
    db = open_db(args, create=True)
    games = [config.asset_game(g) for g in args.game] if args.game else None
    root = Path(args.root).expanduser() if args.root else config.assets_root()
    result = assets.index(db, root, games)
    emit(args, result, f"indexed {result['files']} files ({result['bytes'] / 1e9:.1f} GB) "
                       f"for {', '.join(result['games'])} from {result['root']} in {result['sec']}s")
    return 0


def cmd_asset_find(args) -> int:
    db = open_db(args)
    if not args.query.strip():
        result = assets.summary(db)
        rows = [[g, c["cpk"], c["files"], f"{c['bytes'] / 1e6:.0f} MB"]
                for g, v in result["games"].items() for c in v["cpks"]]
        emit(args, result, _table(["game", "cpk", "files", "size"], rows))
        return 0
    result = assets.find(db, args.query, game=args.game, ext=args.ext, cpk=args.cpk,
                         limit=args.limit)
    rows = [[r["game"], r["cpk"] or "(loose)", r["entry"], r["size"], r["magic"]]
            for r in result["results"]]
    text = _table(["game", "cpk", "entry", "size", "magic"], rows)
    emit(args, result, f"{text}\n{len(rows)} of {result['total']}")
    return 0


def cmd_asset_info(args) -> int:
    db = open_db(args)
    result = assets.info(db, args.game, args.path, max_chunks=args.max_chunks)
    lines = [f"{k:<12} {result[k]}" for k in
             ("game", "cpk", "entry", "size", "magic", "path", "win_path")]
    for o in result["other_games"]:
        lines.append(f"also in      {o['game']}  {o['rel']}  {o['size']}"
                     + ("" if o["same_size"] else "  (size differs)"))
    if "xfbin" in result:
        x = result["xfbin"]
        lines.append(f"xfbin        {x['chunk_count']} chunks")
        lines += [f"  {c['type']:<24} {c['name']:<32} {c['path']}" for c in x["chunks"]]
    if "xfbin_error" in result:
        lines.append(f"xfbin error  {result['xfbin_error']}")
    emit(args, result, "\n".join(lines))
    return 0
