"""Input chain map: poll -> pad -> CtrlInputPad -> gates -> ChangeAction.

Direct call edges come from decompiled code; the vfunc/vtable hop is not a
direct call, so it is reported separately as a knowledge-base note instead of
being invented.
"""

from __future__ import annotations

from collections import deque

from . import config
from .db import DB
from .decomp import load_decomp
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .text import fmt_addr, fun_addr

KNOWN_SEEDS = [
    ("ccPlayerLeader::UpdatePadState", "pad-state"),
    ("ccPlayerLeader::CtrlInputPad", "ctrl"),
    ("ccPlayer::ChangeAction", "action"),
]

# Storm 4 1.09 (docs/reference/storm4-1.09.md). Reached through a vfunc, not a direct call.
KNOWN_GATES = {
    0x7AD3F8: "chakra-dash gate (vfunc+0xE88)",
    0x7AD12C: "cancel-frame gate (vfunc+0xE88)",
}

BUTTON_BITS = {
    "A": 0x4000,
    "B": 0x2000,
    "X": 0x8000,
    "Y": 0x1000,
    "LB": 0x400,
    "RB": 0x800,
    "RT/guard": 0x200,
    "Back": 0x1,
    "Up": 0x10,
    "Right": 0x20,
    "Down": 0x40,
    "Left": 0x80,
    "L3": 0x2,
    "R3": 0x4,
}

KNOWN_CHAIN = [
    "XInput poll, edge/raw input, limiter (identical in 1.06/1.07/1.09)",
    "ccPlayerPad press word at ccPlayerPad+0x404",
    "ccPlayerLeader::CtrlInputPad (0x7E0214)",
    "vfunc+0xE88 gates: 0x7AD3F8 chakra dash, 0x7AD12C cancel frames",
    "ccPlayer::ChangeAction (0x7AB468)",
]

ROLE_ORDER = {"pad-state": 0, "ctrl": 1, "gate": 2, "action": 3, "player": 4, "caller": 5, "neighbor": 6}


def _role(name: str | None, rva: int | None) -> str:
    if rva is not None and rva in KNOWN_GATES:
        return "gate"
    n = name or ""
    if "UpdatePadState" in n:
        return "pad-state"
    if "CtrlInputPad" in n:
        return "ctrl"
    if "ChangeAction" in n:
        return "action"
    if n.startswith("ccPlayer") or "Pad" in n or n.startswith("nuccSys"):
        return "player"
    return "neighbor"


def _symbol(db: DB, build: str, rva: int | None, fallback: str) -> str:
    if rva is None:
        return fallback
    rows = db.symbols_at(build, rva)
    if rows and rows[0]["name"] and not (rows[0]["name"] or "").startswith(("FUN_", "SUB_")):
        return rows[0]["name"]
    return fallback


def _resolve_seed(db: DB, build: str, name: str):
    try:
        return resolve(db, name, build)
    except ResolveError:
        if build != "s4":
            try:
                from .mapper import map_name

                mapped = map_name(db, name, "s4", build)
                if mapped:
                    return resolve(db, fmt_addr(mapped.to_rva), build, addr_kind="rva")
            except ResolveError:
                return None
        return None


def analyze_input_path(
    db: DB,
    client: MCPClient | None,
    build: str = "s4",
    *,
    depth: int = 1,
    limit: int = 80,
) -> dict:
    build_alias = config.canonical_build(build)
    warnings: list[str] = []
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seeds: list[dict] = []

    def add_node(key: str, name: str | None, rva: int | None, role: str, kind: str = "function") -> None:
        if key in nodes:
            return
        nodes[key] = {
            "key": key,
            "name": name,
            "rva": fmt_addr(rva) if rva is not None else None,
            "role": role,
            "kind": kind,
        }

    for name, role in KNOWN_SEEDS:
        res = _resolve_seed(db, build_alias, name)
        if res is None:
            warnings.append(f"seed {name}: not resolved in {build_alias}")
            continue
        try:
            raw, _ = load_decomp(db, client, res)
        except MCPError as exc:
            warnings.append(f"{name}: {exc}")
            continue

        key = fmt_addr(res.rva)
        add_node(key, res.name or name, res.rva, role)
        seeds.append({"name": res.name or name, "rva": key, "role": role})

        for callee in raw.get("callees") or []:
            if not isinstance(callee, str):
                continue
            rva = fun_addr(callee)
            resolved = _symbol(db, build_alias, rva, callee)
            target = fmt_addr(rva) if rva is not None else callee
            add_node(target, resolved, rva, _role(resolved, rva))
            edges.append(
                {
                    "from": key,
                    "from_name": res.name or name,
                    "to": target,
                    "to_name": resolved,
                    "kind": "call",
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
            if not fn:
                continue
            rva = fun_addr(fn)
            target = fmt_addr(rva) if rva is not None else fn
            add_node(target, fn, rva, _role(fn, rva))
            edges.append(
                {
                    "from": target,
                    "from_name": fn,
                    "to": key,
                    "to_name": res.name or name,
                    "kind": "call",
                    "verified": True,
                    "method": "xref",
                }
            )

    # Gates are indirect (vfunc targets); report them with a mapping when the
    # build is not 1.09.
    gates = []
    for addr, note in KNOWN_GATES.items():
        rva = addr
        mapped = None
        if build_alias != "s4":
            try:
                from .mapper import map_name

                m = map_name(db, fmt_addr(addr), "s4", build_alias)
                if m:
                    rva, mapped = m.to_rva, m.method
            except ResolveError:
                rva, mapped = None, None
        if rva is None:
            gates.append({"rva": None, "name": None, "note": note, "mapped": mapped})
            continue
        name = _symbol(db, build_alias, rva, "")
        add_node(fmt_addr(rva), name or None, rva, "gate", kind="gate")
        gates.append(
            {
                "rva": fmt_addr(rva),
                "name": name or None,
                "note": note,
                "mapped": mapped,
                "reached_by": "vfunc+0xE88 (indirect; not a direct call)",
            }
        )

    node_list = sorted(
        nodes.values(),
        key=lambda n: (ROLE_ORDER.get(n["role"], 9), n["name"] or "", n["rva"] or ""),
    )[:limit]

    # Paths only over verified direct edges. The real hop is indirect, so this
    # is usually empty; that is the honest result.
    adjacency: dict[str, list[str]] = {}
    for e in edges:
        adjacency.setdefault(e["from"], []).append(e["to"])
    start_keys = [s["rva"] for s in seeds if s["role"] in ("pad-state", "ctrl")]
    action_keys = [s["rva"] for s in seeds if s["role"] == "action"]
    paths: list[list[str]] = []
    for start in start_keys:
        queue = deque([[start]])
        seen = {start}
        while queue and len(paths) < 5:
            path = queue.popleft()
            if len(path) > depth + 2:
                continue
            last = path[-1]
            if last in action_keys and len(path) > 1:
                paths.append([nodes[k]["name"] or k for k in path if k in nodes])
                continue
            for nxt in adjacency.get(last, []):
                if nxt in seen:
                    continue
                seen.add(nxt)
                queue.append(path + [nxt])

    if not paths:
        warnings.append(
            "no direct call path from the input seeds to ChangeAction; the "
            "link is a vfunc/vtable hop. See known_chain."
        )

    stats = {
        "seeds": len(seeds),
        "nodes": len(node_list),
        "edges": len(edges),
        "verified_edges": sum(1 for e in edges if e["verified"]),
        "gates": len(gates),
        "paths": len(paths),
    }
    return {
        "ok": True,
        "build": build_alias,
        "seeds": seeds,
        "nodes": node_list,
        "edges": edges[: max(limit * 4, 200)],
        "gates": gates,
        "button_bits": BUTTON_BITS,
        "paths": paths,
        "known_chain": KNOWN_CHAIN,
        "stats": stats,
        "warnings": warnings,
    }
