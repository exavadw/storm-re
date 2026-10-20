"""Frame-tick and timer-idiom scan.

Answers "what runs per frame and which constants break at 60 FPS" as a
heuristic: the state-timer idiom `-(3000/fps)` is correct at 60, while
per-frame `+= c` / `*= k` constants are the real risk.
"""

from __future__ import annotations

import re

from . import config
from .db import DB
from .decomp import load_decomp
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .text import fmt_addr

# Storm 4 1.09 anchors (docs/reference/storm4-1.09.md).
DEFAULT_SEEDS = ["0xA0C290", "ccPlayer::ChangeAction"]
FPS_BYTE = "0x942"

IDIOM_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("state-timer-neg", re.compile(
        r"-\s*\(?\s*(?:int|longlong|undefined[48]|float|double)?\s*\)?\s*\(?\s*(\d+)\s*/\s*\(?[A-Za-z_]"
    )),
    ("scaled-thirty", re.compile(r"(\d+(?:\.\d+)?)\s*/\s*\(\s*(?:30|60)(?:\.0)?\s*/\s*")),
    ("mod-timer", re.compile(r"(\d+)\s*%\s*\(?[A-Za-z_]")),
]
CONST_RE = re.compile(r"(?P<op>\+=|-=|\*=|/=)\s*(?P<val>\d+(?:\.\d+)?)(?P<unit>[fFuU]?)")

PRIORITY = ("Update", "Ctrl", "Frame", "ResetFrame", "Tick", "Step", "ChangeAction")


def _priority(name: str, size: int | None) -> tuple[int, int, str]:
    short = name.split("::")[-1]
    score = 0
    if "ChangeAction" in short:
        score += 50
    if "ResetFrame" in short or "Frame" in short:
        score += 30
    for kw in PRIORITY:
        if kw in short:
            score += 10
    return (-score, -(size or 0), name)


def select_frame_seeds(db: DB, build: str, limit: int, seeds: str | None = None):
    if seeds:
        out = []
        for token in (s.strip() for s in seeds.split(",")):
            if not token:
                continue
            try:
                out.append(resolve(db, token, build))
            except ResolveError:
                continue
        return out

    out, seen = [], set()

    def add(res) -> None:
        if res.rva in seen:
            return
        seen.add(res.rva)
        out.append(res)

    for name in DEFAULT_SEEDS:
        try:
            add(resolve(db, name, build))
        except ResolveError:
            continue

    rows = db.symbols_prefix(build, "nuccSys::", limit * 4) + db.symbols_prefix(
        build, "ccPlayer::", limit * 8
    )
    rows = [r for r in rows if any(k in r["name"] for k in PRIORITY)]
    rows.sort(key=lambda r: _priority(r["name"], r["size"]))
    for row in rows:
        if len(out) >= limit:
            break
        try:
            add(resolve(db, fmt_addr(row["rva"]), build, addr_kind="rva"))
        except ResolveError:
            continue
    return out[:limit]


def scan_code(code: str) -> dict:
    idioms: list[dict] = []
    fps_sources: list[str] = []
    for line in code.splitlines():
        stripped = " ".join(line.split())
        if not stripped:
            continue
        for kind, pattern in IDIOM_PATTERNS:
            m = pattern.search(line)
            if m:
                constant = next((g for g in m.groups() if g), None)
                idioms.append({"kind": kind, "constant": constant, "line": stripped[:200]})
                break
        if FPS_BYTE in stripped:
            if len(fps_sources) < 4:
                fps_sources.append(stripped[:200])

    per_frame: list[dict] = []
    if idioms or fps_sources:
        for line in code.splitlines():
            for m in CONST_RE.finditer(line):
                per_frame.append(
                    {
                        "op": m.group("op"),
                        "value": m.group("val") + m.group("unit"),
                        "line": " ".join(line.split())[:200],
                    }
                )
                if len(per_frame) >= 12:
                    break
            if len(per_frame) >= 12:
                break
    return {
        "idioms": idioms[:12],
        "fps_sources": fps_sources,
        "constants": per_frame,
    }


def analyze_frame_tick(
    db: DB,
    client: MCPClient | None,
    build: str = "s4",
    *,
    limit: int = 30,
    seeds: str | None = None,
) -> dict:
    build_alias = config.canonical_build(build)
    resolutions = select_frame_seeds(db, build_alias, limit, seeds)
    warnings: list[str] = []
    functions: list[dict] = []
    analyzed = failed = 0

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
        found = scan_code(code)
        if not (found["idioms"] or found["fps_sources"]):
            continue
        confidence = "medium" if found["idioms"] else "low"
        functions.append(
            {
                "name": name,
                "rva": fmt_addr(res.rva),
                "idioms": found["idioms"],
                "fps_sources": found["fps_sources"],
                "constants": found["constants"],
                "confidence": confidence,
            }
        )

    functions.sort(key=lambda f: (-len(f["idioms"]), f["name"]))
    stats = {
        "seeds_requested": len(resolutions),
        "seeds_analyzed": analyzed,
        "seeds_failed": failed,
        "functions_with_idioms": len(functions),
        "idioms": sum(len(f["idioms"]) for f in functions),
        "constants": sum(len(f["constants"]) for f in functions),
    }
    if not functions:
        warnings.append("no timer idioms found in the selected seeds")
    return {
        "ok": True,
        "build": build_alias,
        "functions": functions,
        "stats": stats,
        "warnings": warnings,
        "notes": [
            "30 FPS is the correct mode; the 30/fps state-timer idiom (e.g. `-(3000/fps)`) is correct at 60.",
            "Real 60 FPS bugs are per-frame constants (`+= c`, `*= k`), velocity/hit sampling, UI input and substitution.",
            "`nuccSys+0x942` is 30/60 (a scaling factor), not a divisor.",
            "Detection is a heuristic; confirm with a runtime frame trace.",
        ],
    }
