"""Export indexed facts to a compact markdown report."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import config
from .db import DB
from .mapper import map_name
from .resolve import ResolveError
from .text import fmt_addr


def _summary(row) -> dict:
    try:
        return json.loads(row["summary"] or "{}")
    except json.JSONDecodeError:
        return {}


def build_report(
    db: DB,
    topic: str,
    *,
    build: str | None = None,
    limit: int = 50,
    include_code: bool = False,
) -> tuple[str, dict]:
    build_alias = config.canonical_build(build) if build else None
    rows = db.index_list(topic=topic, build_alias=build_alias, limit=limit)
    if not rows:
        rows = db.index_search(topic, limit=limit)
        if build_alias:
            rows = [r for r in rows if r["build_alias"] == build_alias]
    raw_rows = rows[: limit * 2]
    skipped = sum(1 for r in raw_rows if r["status"] != "ok")
    rows = [r for r in raw_rows if r["status"] == "ok"][:limit]

    lines = [
        f"# storm-re: {topic}",
        "",
        f"Generated: {date.today().isoformat()}",
        f"Build filter: {build_alias or 'all'}",
        "",
        "Static facts from `storm-re` (build-verified RVAs and names). "
        "Everything here is `inferred` until a runtime probe confirms it.",
        "",
        f"## Summary",
        "",
        f"- entries: {len(rows)}",
        f"- skipped (missing/error): {skipped}",
    ]
    if rows:
        lines.append(f"- builds: {', '.join(sorted({r['build_alias'] for r in rows}))}")
        lines.append(f"- functions: {', '.join(sorted({r['name'] for r in rows}))[:600]}")
    lines.append("")
    lines.append("## Functions")
    lines.append("")

    entries = []
    for row in rows:
        summary = _summary(row)
        name = row["name"] or "(unnamed)"
        lines.append(f"### `{name}`")
        lines.append("")
        lines.append(
            f"- build: `{row['build_alias']}`  rva: `{fmt_addr(row['rva'])}`  "
            f"status: `{row['status']}`"
        )
        if row["signature"]:
            lines.append(f"- signature: `{row['signature']}`")
        if summary.get("caller_count") is not None:
            lines.append(
                f"- callers: {summary.get('caller_count')}  "
                f"callees: {summary.get('callee_count')}  "
                f"lines: {summary.get('code_lines')}"
            )
        callers = summary.get("callers") or []
        if callers:
            lines.append("- callers: " + ", ".join(f"`{c}`" for c in callers[:10]))
        callees = summary.get("callees") or []
        if callees:
            lines.append("- callees: " + ", ".join(f"`{c}`" for c in callees[:10]))

        maps = []
        for target in ("s4-debug", "s4-107"):
            if target == row["build_alias"]:
                continue
            try:
                m = map_name(db, name, row["build_alias"], target)
            except ResolveError:
                m = None
            if m:
                maps.append(
                    f"`{target}` `{fmt_addr(m.to_rva)}` "
                    f"({m.method}, {m.score:.2f}, {m.confidence})"
                )
        if maps:
            lines.append("- cross-build: " + "; ".join(maps))

        if include_code:
            code = row["symbolized"] or row["text"]
            if code:
                lines.append("")
                lines.append("```c")
                lines.append(code[:6000])
                lines.append("```")
        lines.append("")
        entries.append(
            {
                "name": name,
                "build": row["build_alias"],
                "rva": fmt_addr(row["rva"]),
                "status": row["status"],
            }
        )

    lines.append("## Caveats")
    lines.append("")
    lines.append("- Static inference; confirm rollback/runtime fields with a replay trace/snap or in-game probe.")
    lines.append("- Symbol names can be wrong despite confidence; check `source`/`confidence`.")
    lines.append("- `diff`/`patch_diff` similarity is line-based decompiled text.")
    lines.append("")

    markdown = "\n".join(lines)
    return markdown, {
        "topic": topic,
        "build": build_alias,
        "entries": entries,
        "skipped": skipped,
        "bytes": len(markdown),
    }


def write_report(markdown: str, out: str) -> str:
    if out == "-":
        return "-"
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown)
    return str(path)
