"""Steam/net-session surface: ccNetFreeBattleSync send/recv/tick functions."""

from __future__ import annotations

from . import config
from .db import DB
from .decomp import load_decomp
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .text import fmt_addr, fun_addr

DEFAULT_SEEDS = [
    "ccNetFreeBattleSync::CtrlFighting",
    "ccNetFreeBattleSync::AddNetDataToInputBuffer",
    "ccNetFreeBattleSync::AnalysisFrameDataFromFighter",
    "ccNetInputBuffer::Add",
    "ccNetConvertRTT",
]

DIRECTION_KEYS = [
    ("send", ("Send", "MakeSend", "CreateSendPack", "SetSendData")),
    ("recv", ("Receive", "Analysis", "Recv")),
    ("tick", ("Ctrl", "Update", "Tick")),
    ("init", ("Initialize", "Start", "Reset")),
    ("buffer", ("InputBuffer",)),
]


def direction_of(name: str) -> str:
    short = name.split("::")[-1]
    for label, keys in DIRECTION_KEYS:
        if any(k in short for k in keys):
            return label
    if short == "Add":
        return "buffer"
    return "other"


def layer_of(name: str) -> str:
    if "FreeBattleSync" in name or "InputBuffer" in name:
        return "game-sync"
    if any(k in name for k in ("Steam", "Session", "Socket", "P2P", "Net")):
        return "transport"
    return "other"


def select_net_seeds(db: DB, build: str, limit: int, seeds: str | None = None):
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

    for name in DEFAULT_SEEDS:
        try:
            add(resolve(db, name, build))
        except ResolveError:
            continue

    rows = db.symbols_prefix(build, "ccNetFreeBattleSync::", limit * 4)
    for row in rows:
        if len(out) >= limit:
            break
        try:
            add(resolve(db, fmt_addr(row["rva"]), build, addr_kind="rva"))
        except ResolveError:
            continue
    return out[:limit]


def analyze_net_session(
    db: DB,
    client: MCPClient | None,
    build: str = "s4",
    *,
    limit: int = 25,
    seeds: str | None = None,
    include_imports: bool = True,
) -> dict:
    build_alias = config.canonical_build(build)
    resolutions = select_net_seeds(db, build_alias, limit, seeds)
    warnings: list[str] = []
    functions: list[dict] = []
    edges: list[dict] = []
    analyzed = failed = 0
    program = None

    for res in resolutions:
        name = res.name or fmt_addr(res.rva)
        program = res.program
        try:
            raw, _ = load_decomp(db, client, res)
        except MCPError as exc:
            failed += 1
            warnings.append(f"{name}: {exc}")
            continue
        if not (raw.get("code") or "").strip():
            failed += 1
            continue
        analyzed += 1
        key = fmt_addr(res.rva)
        functions.append(
            {
                "name": name,
                "rva": key,
                "direction": direction_of(name),
                "layer": layer_of(name),
                "callees": len(raw.get("callees") or []),
            }
        )
        for callee in raw.get("callees") or []:
            if not isinstance(callee, str):
                continue
            if not any(k in callee for k in ("ccNet", "Steam", "Socket", "ccSession")):
                continue
            rva = fun_addr(callee)
            target = fmt_addr(rva) if rva is not None else callee
            edges.append(
                {
                    "from": key,
                    "from_name": name,
                    "to": target,
                    "to_name": callee,
                    "kind": "call",
                    "direction": direction_of(callee),
                    "layer": layer_of(callee),
                    "verified": True,
                    "method": "decompile",
                }
            )
        for xref in raw.get("xrefs") or []:
            if not isinstance(xref, dict):
                continue
            if "CALL" not in str(xref.get("type") or "").upper():
                continue
            fn = xref.get("function_name")
            if not fn or not any(k in fn for k in ("ccNet", "Steam", "Socket", "ccSession")):
                continue
            rva = fun_addr(fn)
            edges.append(
                {
                    "from": fmt_addr(rva) if rva is not None else fn,
                    "from_name": fn,
                    "to": key,
                    "to_name": name,
                    "kind": "call",
                    "direction": direction_of(fn),
                    "layer": layer_of(fn),
                    "verified": True,
                    "method": "xref",
                }
            )

    steam_interfaces: list[str] = []
    if include_imports and client is not None and program:
        try:
            data = client.call_tool(
                "list_imports",
                {"binary_name": program, "query": "Steam", "limit": 100},
            )
            names = {
                i.get("name")
                for i in (data.get("imports") or [])
                if isinstance(i, dict) and str(i.get("name", "")).startswith("Steam")
            }
            steam_interfaces = sorted(n for n in names if n)
        except MCPError as exc:
            warnings.append(f"list_imports: {exc}")

    by_direction: dict[str, int] = {}
    for f in functions:
        by_direction[f["direction"]] = by_direction.get(f["direction"], 0) + 1

    functions.sort(key=lambda f: (f["direction"], f["name"]))
    stats = {
        "seeds_requested": len(resolutions),
        "seeds_analyzed": analyzed,
        "seeds_failed": failed,
        "functions": len(functions),
        "edges": len(edges),
        "verified_edges": sum(1 for e in edges if e["verified"]),
        "steam_interfaces": len(steam_interfaces),
        "by_direction": by_direction,
    }
    if not functions:
        warnings.append("no ccNet functions resolved")
    return {
        "ok": True,
        "build": build_alias,
        "functions": functions,
        "edges": edges[:400],
        "steam_interfaces": steam_interfaces,
        "stats": stats,
        "warnings": warnings,
        "notes": [
            "Steam SDK in Storm 4: SteamUser016 / Friends013 / MatchMaking009 / Networking005 / UserStats011.",
            "ccNetFreeBattleSync is the game-sync layer; Steam/Session symbols are transport.",
            "Direction is inferred from the method name; confirm the actual send/recv path with a net trace.",
        ],
    }
