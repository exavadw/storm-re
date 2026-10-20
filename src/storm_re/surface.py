"""Static field-access extraction for rollback state surfaces."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config
from .db import DB
from .decomp import load_decomp
from .mcp import MCPClient, MCPError
from .resolve import ResolveError, resolve
from .text import fmt_addr, fun_addr, is_hex

SIZE_MAP = {
    "byte": 1, "char": 1, "undefined1": 1, "bool": 1,
    "short": 2, "undefined2": 2, "ushort": 2,
    "int": 4, "undefined4": 4, "uint": 4, "float": 4, "long": 4, "ulong": 4,
    "longlong": 8, "undefined8": 8, "ulonglong": 8, "double": 8,
}

SCALE_MAP = {
    "longlong": 8, "undefined8": 8, "ulonglong": 8, "double": 8,
    "int": 4, "undefined4": 4, "uint": 4, "float": 4, "long": 4, "ulong": 4,
    "short": 2, "undefined2": 2, "ushort": 2,
    "char": 1, "byte": 1, "undefined1": 1, "void": 1, "bool": 1,
}

CAST_RE = re.compile(r"\*\(\s*([A-Za-z_][A-Za-z0-9_ ]*?)\s*\*\s*\)\s*\(?\s*$")


@dataclass
class Access:
    offset: int
    size: int | None
    write: bool
    function: str
    function_rva: int
    sample: str
    scale_known: bool = True


def signature_of(code: str) -> str:
    for line in code.splitlines():
        s = line.split("{", 1)[0].strip()
        if s and "(" in s and ")" in s and not s.startswith(("//", "/*", "*")):
            return s
    return ""


def param_scale(signature: str, param: str = "param_1") -> int | None:
    m = re.search(
        rf"([A-Za-z_][A-Za-z0-9_ ]*?)\s*\*+\s*{re.escape(param)}\b", signature
    )
    if not m:
        return None
    type_name = m.group(1).strip().lower()
    if type_name.endswith("*"):
        return None
    return SCALE_MAP.get(type_name)


def _cast_size(prefix: str) -> int | None:
    if re.search(r"\*\s*\*\s*\)\s*\(?\s*$", prefix):
        return 8  # pointer to pointer
    m = CAST_RE.search(prefix)
    if not m:
        return None
    type_name = m.group(1).strip().lower()
    if type_name.endswith("*"):
        return 8
    return SIZE_MAP.get(type_name)


def _is_write(tail: str) -> bool:
    t = tail.lstrip()
    t = re.sub(r"^[\)\]]+", "", t).lstrip()
    if re.match(r"=(?!=)", t):
        return True
    if re.match(r"(?:\+=|-=|\*=|/=|\|=|&=|\^=|<<=|>>=)", t):
        return True
    return t.startswith("++") or t.startswith("--")


def parse_surface(
    code: str, param: str = "param_1"
) -> tuple[list[Access], bool]:
    """Return (accesses, scale_unknown)."""
    signature = signature_of(code)
    scale = param_scale(signature, param)
    p = re.escape(param)
    pattern = re.compile(
        rf"(?P<byte>\((?:longlong|char\s*\*|byte\s*\*|undefined1\s*\*)\)\s*"
        rf"{p}\s*\+\s*(?P<byteoff>0x[0-9a-fA-F]+))"
        rf"|(?P<idx>{p}\[(?P<idxoff>0x[0-9a-fA-F]+)\])"
        rf"|(?P<ptr>{p}\s*\+\s*(?P<ptroff>0x[0-9a-fA-F]+))"
    )

    accesses: list[Access] = []
    scale_unknown = False
    for m in pattern.finditer(code):
        raw_off = m.group("byteoff") or m.group("idxoff") or m.group("ptroff")
        if not raw_off:
            continue
        if m.group("byte"):
            offset = int(raw_off, 16)
            unit = 1
            known = True
        else:
            if scale is None:
                scale_unknown = True
                continue
            offset = int(raw_off, 16) * scale
            unit = scale
            known = True

        cast = _cast_size(code[max(0, m.start() - 48) : m.start()])
        if cast is not None:
            size = cast
        elif m.group("idx"):
            size = unit
        else:
            size = None

        line_start = code.rfind("\n", 0, m.start()) + 1
        line_end = code.find("\n", m.end())
        if line_end == -1:
            line_end = len(code)
        sample = " ".join(code[line_start:line_end].split())[:220]

        accesses.append(
            Access(
                offset=offset,
                size=size,
                write=_is_write(code[m.end() : m.end() + 40]),
                function="",
                function_rva=0,
                sample=sample,
                scale_known=known,
            )
        )
    return accesses, scale_unknown


def _priority(name: str, size: int | None) -> tuple[int, int, str]:
    short = name.split("::")[-1]
    score = 0
    if short in ("ChangeAction", "UpdatePadState", "CtrlInputPad"):
        score += 100
    for kw, pts in (
        ("Update", 20), ("Ctrl", 18), ("Change", 16), ("Init", 14),
        ("Reset", 12), ("Set", 10), ("On", 8), ("Action", 6), ("State", 4),
    ):
        if kw in short:
            score += pts
    return (-score, -(size or 0), name)


def select_seeds(
    db: DB, build: str, root: str, limit: int = 40, seeds: str | None = None
):
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

    if is_hex(root) or fun_addr(root) is not None:
        return [resolve(db, root, build)]

    if "::" in root:
        try:
            res = resolve(db, root, build)
            if res.kind == "symbol":
                return [res]
        except ResolveError:
            pass

    prefix = root if root.endswith("::") else root + "::"
    rows = db.symbols_prefix(build, prefix, limit * 8)
    rows = sorted(rows, key=lambda r: _priority(r["name"], r["size"]))[:limit]

    out = []
    for row in rows:
        try:
            out.append(resolve(db, fmt_addr(row["rva"]), build, addr_kind="rva"))
        except ResolveError:
            continue
    return out


def _aggregate(accesses: list[Access], max_offset: int, min_writes: int) -> list[dict]:
    fields: dict[int, dict] = {}
    for a in accesses:
        if a.offset < 0 or a.offset > max_offset:
            continue
        f = fields.setdefault(
            a.offset,
            {
                "offset": a.offset,
                "read_sizes": set(),
                "write_sizes": set(),
                "reads": 0,
                "writes": 0,
                "funcs": {},
                "samples": [],
                "unknown_scale": False,
                "unknown_size": False,
            },
        )
        if a.size is None:
            f["unknown_size"] = True
        else:
            (f["write_sizes"] if a.write else f["read_sizes"]).add(a.size)
        if a.write:
            f["writes"] += 1
        else:
            f["reads"] += 1
        if a.function:
            f["funcs"][a.function] = a.function_rva
        if a.sample and len(f["samples"]) < 2 and a.sample not in f["samples"]:
            f["samples"].append(a.sample)
        if not a.scale_known:
            f["unknown_scale"] = True

    out = []
    for off, f in fields.items():
        if f["writes"] < min_writes:
            continue
        all_sizes = sorted(f["read_sizes"] | f["write_sizes"])
        chosen = sorted(f["write_sizes"] or f["read_sizes"])
        exact = (
            not f["unknown_scale"]
            and not f["unknown_size"]
            and len(chosen) == 1
        )
        if f["writes"]:
            kind = "rw" if f["reads"] else "w"
        else:
            kind = "r"
        if exact and f["writes"] and (len(f["funcs"]) >= 2 or f["writes"] >= 2):
            confidence = "high"
        elif exact:
            confidence = "medium"
        else:
            confidence = "low"
        out.append(
            {
                "offset": fmt_addr(off),
                "offset_int": off,
                "size": chosen[0] if len(chosen) == 1 else (chosen or None),
                "sizes": all_sizes,
                "read_sizes": sorted(f["read_sizes"]),
                "write_sizes": sorted(f["write_sizes"]),
                "kind": kind,
                "reads": f["reads"],
                "writes": f["writes"],
                "functions": [
                    {"name": name, "rva": fmt_addr(rva)}
                    for name, rva in sorted(f["funcs"].items())
                ][:12],
                "confidence": confidence,
                "sample": f["samples"][0] if f["samples"] else "",
            }
        )
    out.sort(key=lambda x: (-x["writes"], -x["reads"], x["offset_int"]))
    return out


def analyze(
    db: DB,
    client: MCPClient | None,
    root: str,
    build: str = "s4",
    *,
    limit: int = 40,
    max_offset: int = 0x40000,
    param: str = "param_1",
    seeds: str | None = None,
    min_writes: int = 0,
) -> dict:
    build_alias = config.canonical_build(build)
    resolutions = select_seeds(db, build_alias, root, limit, seeds)
    warnings: list[str] = []
    seed_info: list[dict] = []
    accesses: list[Access] = []
    analyzed = failed = 0

    for res in resolutions:
        name = res.name or fmt_addr(res.rva)
        try:
            raw, _ = load_decomp(db, client, res)
        except MCPError as exc:
            failed += 1
            seed_info.append(
                {"name": name, "rva": fmt_addr(res.rva), "status": "error", "detail": str(exc)}
            )
            warnings.append(f"{name}: {exc}")
            continue

        code = raw.get("code") or ""
        if not code.strip():
            failed += 1
            seed_info.append(
                {"name": name, "rva": fmt_addr(res.rva), "status": "empty", "detail": ""}
            )
            continue

        parsed, scale_unknown = parse_surface(code, param)
        if scale_unknown:
            warnings.append(
                f"{name}: unknown {param} element size; only byte-cast accesses used"
            )
        for access in parsed:
            access.function = name
            access.function_rva = res.rva
            accesses.append(access)
        analyzed += 1
        seed_info.append(
            {
                "name": name,
                "rva": fmt_addr(res.rva),
                "status": "ok",
                "accesses": len(parsed),
            }
        )

    fields = _aggregate(accesses, max_offset, min_writes)
    stats = {
        "seeds_requested": len(resolutions),
        "seeds_analyzed": analyzed,
        "seeds_failed": failed,
        "fields_total": len(fields),
        "writable": sum(1 for f in fields if f["writes"] > 0),
        "read_only": sum(1 for f in fields if f["writes"] == 0),
        "reads": sum(f["reads"] for f in fields),
        "writes": sum(f["writes"] for f in fields),
    }
    return {
        "ok": True,
        "root": root,
        "build": build_alias,
        "param": param,
        "seeds": seed_info,
        "fields": fields,
        "stats": stats,
        "warnings": warnings,
    }
