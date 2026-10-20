"""Story scene dispatch surface: scene manager, message lookup, UI hooks."""

from __future__ import annotations

from . import config
from .db import DB
from .decomp import load_decomp
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .text import fmt_addr, fun_addr

DEFAULT_NAMES = [
    "Movie::Invoke",
    "ccSceneManager::AssignSceneChange",
    "ccSceneManager::AssignSceneChangeAlt",
    "ccSceneManager::ChangeScene",
]

# Storm 4 1.09 anchors (docs/reference/storm4-1.09.md).
DEFAULT_ADDRS = {
    0xABD020: "ccMessageManager::GetMessageParam (message lookup)",
    0xAB93D0: "stage-name lookup (message field +8)",
    0x871310: "Movie::Invoke (Scaleform)",
}

KNOWN_IDS = [
    {"id": "0x5300", "name": "boss root scene", "source": "mod-defined", "confidence": "inferred"},
    {"id": "0x5301", "name": "boss IA", "source": "mod-defined", "confidence": "inferred"},
]

INTERESTING = ("c_sta_", ".gfx", "option", "message", "scene", "quest", "adv")


def role_of(name: str) -> str:
    if "Message" in name:
        return "message"
    if "Movie" in name or "Gfx" in name or "Ui" in name:
        return "ui"
    if "Scene" in name:
        return "scene"
    if "Stage" in name:
        return "stage"
    return "other"


def select_scene_seeds(db: DB, build: str, limit: int, seeds: str | None = None):
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
        if res.rva not in seen:
            seen.add(res.rva)
            out.append(res)

    for name in DEFAULT_NAMES:
        try:
            add(resolve(db, name, build))
        except ResolveError:
            continue
    if build == "s4":
        for addr in DEFAULT_ADDRS:
            try:
                add(resolve(db, fmt_addr(addr), build))
            except ResolveError:
                continue

    rows = db.symbols_prefix(build, "ccSceneManager::", limit * 4)
    rows = [
        r for r in rows
        if any(k in r["name"] for k in ("Change", "Assign", "Scene", "Dispatch", "Load", "Transition"))
    ]
    for row in rows:
        if len(out) >= limit:
            break
        try:
            add(resolve(db, fmt_addr(row["rva"]), build, addr_kind="rva"))
        except ResolveError:
            continue
    return out[:limit]


def analyze_scene_dispatch(
    db: DB,
    client: MCPClient | None,
    build: str = "s4",
    *,
    limit: int = 20,
    seeds: str | None = None,
) -> dict:
    build_alias = config.canonical_build(build)
    resolutions = select_scene_seeds(db, build_alias, limit, seeds)
    warnings: list[str] = []
    functions: list[dict] = []
    edges: list[dict] = []
    analyzed = failed = 0
    message_lookup = None

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
        role = role_of(name)
        strings = [
            s.get("value", "")
            for s in (raw.get("referenced_strings") or [])
            if isinstance(s, dict)
        ]
        interesting = [s for s in strings if any(k in s for k in INTERESTING)][:10]
        stage_names = sorted({s for s in strings if s.startswith("c_sta_")})
        callers = [
            x.get("function_name")
            for x in (raw.get("xrefs") or [])
            if isinstance(x, dict)
            and "CALL" in str(x.get("type") or "").upper()
            and x.get("function_name")
        ]
        entry = {
            "name": name,
            "rva": fmt_addr(res.rva),
            "role": role,
            "strings": interesting,
            "stage_names": stage_names,
            "callers": callers[:10],
        }
        functions.append(entry)
        if role == "message" and "GetMessageParam" in name and message_lookup is None:
            message_lookup = entry

        for callee in raw.get("callees") or []:
            if not isinstance(callee, str):
                continue
            if not any(k in callee for k in ("ccScene", "ccMessage", "Movie", "ccUi")):
                continue
            rva = fun_addr(callee)
            edges.append(
                {
                    "from": fmt_addr(res.rva),
                    "from_name": name,
                    "to": fmt_addr(rva) if rva is not None else callee,
                    "to_name": callee,
                    "role": role_of(callee),
                    "verified": True,
                    "method": "decompile",
                }
            )

    functions.sort(key=lambda f: (f["role"], f["name"]))
    stats = {
        "seeds_requested": len(resolutions),
        "seeds_analyzed": analyzed,
        "seeds_failed": failed,
        "functions": len(functions),
        "edges": len(edges),
        "stage_names": len({s for f in functions for s in f["stage_names"]}),
    }
    if not functions:
        warnings.append("no scene/message functions resolved")
    return {
        "ok": True,
        "build": build_alias,
        "functions": functions,
        "edges": edges[:300],
        "message_lookup": message_lookup,
        "scene_ids": KNOWN_IDS,
        "stats": stats,
        "warnings": warnings,
        "notes": [
            "Boss root scene 0x5300 and boss IA 0x5301 are mod-defined runtime ids, not exe addresses.",
            "Message lookup is ccMessageManager::GetMessageParam; stage names come from c_sta_NN strings.",
            "Scene dispatch is partly vtable-driven; direct edges are verified, the rest is inferred.",
        ],
    }
