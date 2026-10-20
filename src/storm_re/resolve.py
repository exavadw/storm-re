"""Target resolution: VA/RVA/name -> one symbol in one build."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from . import config
from .db import DB
from .text import fmt_addr, fun_addr, is_hex, parse_addr


class ResolveError(RuntimeError):
    exit_code = 2


class BuildError(ResolveError):
    pass


class NotFound(ResolveError):
    pass


class Ambiguous(ResolveError):
    def __init__(self, message: str, candidates: list[dict]):
        super().__init__(message)
        self.candidates = candidates


@dataclass
class Resolution:
    build: str
    program: str
    sha256: str
    base: int
    rva: int
    name: str | None
    confidence: str
    source: str
    kind: str  # "symbol" | "address"
    candidates: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def va(self) -> int:
        return self.base + self.rva if self.base else self.rva

    def as_dict(self) -> dict:
        return {
            "build": self.build,
            "program": self.program,
            "sha256": self.sha256,
            "base": fmt_addr(self.base),
            "rva": fmt_addr(self.rva),
            "va": fmt_addr(self.va),
            "name": self.name,
            "confidence": self.confidence,
            "source": self.source,
            "kind": self.kind,
            "candidates": self.candidates,
            "conflicts": self.conflicts,
            "notes": self.notes,
        }


def get_build_row(db: DB, alias: str):
    try:
        canonical = config.canonical_build(alias)
    except KeyError as exc:
        known = ", ".join(sorted(config.BUILDS))
        raise BuildError(f"unknown build {alias!r}; known: {known}") from exc
    row = db.get_build(canonical)
    if not row:
        raise BuildError(f"build {canonical!r} is not in the database (run `storm-re init`)")
    if not row["present"]:
        raise BuildError(
            f"build {canonical!r} ({row['program']}) is absent from the Ghidra project"
        )
    if not row["sha256"]:
        raise BuildError(f"build {canonical!r} has no SHA-256; re-run `storm-re init`")
    return canonical, row


def _row_symbol(row) -> dict:
    return {
        "name": row["name"],
        "short_name": row["short_name"],
        "rva": fmt_addr(row["rva"]),
        "confidence": row["confidence"],
        "source": row["source"],
    }


def _pick(rows) -> tuple[object | None, list[dict]]:
    """Best row (already ordered) and the conflicting alternatives."""
    if not rows:
        return None, []
    best = rows[0]
    conflicts = [
        _row_symbol(r)
        for r in rows[1:]
        if r["name"] != best["name"] or r["rva"] != best["rva"]
    ]
    return best, conflicts


def _name_rows(db: DB, build: str, query: str) -> list:
    rows = db.exact_symbols(build, query)
    if rows:
        return rows
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.like_symbols(build, f"%{escaped}%")
    return rows


def _closest(db: DB, build: str, query: str, limit: int = 5) -> list[str]:
    short = query.rpartition("::")[2] or query
    seed = short[:3] if len(short) >= 3 else short
    pattern = f"%{seed}%"
    names = [
        r["name"]
        for r in db.like_symbols(build, pattern, limit=2000)
    ]
    return difflib.get_close_matches(query, names, n=limit, cutoff=0.3)


def _ambiguous(query: str, grouped: dict[int, list]) -> Ambiguous:
    candidates = []
    for rva, rows in sorted(grouped.items()):
        best = rows[0]
        candidates.append(
            {
                "rva": fmt_addr(rva),
                "name": best["name"],
                "confidence": best["confidence"],
                "source": best["source"],
            }
        )
    lines = ", ".join(f"{c['rva']} {c['name']}" for c in candidates)
    return Ambiguous(
        f"{query!r} is ambiguous ({len(candidates)} matches): {lines}", candidates
    )


def resolve(
    db: DB,
    target: str,
    build: str = config.DEFAULT_BUILD,
    addr_kind: str | None = None,
) -> Resolution:
    canonical, row = get_build_row(db, build)
    base = int(row["base"] or 0)
    sha = row["sha256"]
    program = row["program"]

    text = target.strip()
    if not text:
        raise NotFound("empty target")

    addr = fun_addr(text)
    if addr is None and is_hex(text):
        try:
            addr = parse_addr(text)
        except ValueError:
            addr = None

    if addr is not None:
        rva, notes = _choose_address(db, canonical, addr, base, addr_kind)
        rows = db.symbols_at(canonical, rva)
        best, conflicts = _pick(rows)
        if best is None:
            return Resolution(
                build=canonical,
                program=program,
                sha256=sha,
                base=base,
                rva=rva,
                name=None,
                confidence="",
                source="address",
                kind="address",
                conflicts=[],
                notes=notes,
            )
        return Resolution(
            build=canonical,
            program=program,
            sha256=sha,
            base=base,
            rva=rva,
            name=best["name"],
            confidence=best["confidence"],
            source=best["source"],
            kind="symbol",
            conflicts=conflicts,
            notes=notes,
        )

    # Name lookup
    rows = _name_rows(db, canonical, text)
    if not rows:
        near = _closest(db, canonical, text)
        hint = f"; closest: {', '.join(near)}" if near else ""
        raise NotFound(f"{text!r} not found in build {canonical}{hint}")

    grouped: dict[int, list] = {}
    for r in rows:
        grouped.setdefault(int(r["rva"]), []).append(r)

    q = text.casefold()

    def score(row) -> tuple[int, int, int]:
        exact_full = 1 if (row["name"] or "").casefold() == q else 0
        return (exact_full, int(row["source_rank"] or 0), int(row["conf_rank"] or 0))

    scored: list[tuple[tuple[int, int, int], int, list]] = []
    for rva, rrows in grouped.items():
        ranked_rows = sorted(rrows, key=score, reverse=True)
        scored.append((score(ranked_rows[0]), rva, ranked_rows))
    scored.sort(key=lambda t: t[0], reverse=True)

    # A short name may appear in several classes; only pick a winner when the
    # ranking is strict. A tie must be resolved by the caller with a full name.
    if len(scored) > 1 and scored[0][0] <= scored[1][0]:
        raise _ambiguous(text, {rva: rrows for _s, rva, rrows in scored})

    _best_score, rva, _rows = scored[0]
    # Re-read every name at this RVA: a manual rename wins even when the user
    # searched by the old short name.
    rows_at = db.symbols_at(canonical, rva)
    chosen_rows = sorted(rows_at, key=score, reverse=True) if rows_at else _rows
    best, conflicts = _pick(chosen_rows)
    notes = []
    if len(scored) > 1:
        for _s, other_rva, other_rows in scored[1:]:
            alt = other_rows[0]
            notes.append(
                f"also {fmt_addr(other_rva)} {alt['name']} "
                f"[{alt['source']} {alt['confidence']}]"
            )
    return Resolution(
        build=canonical,
        program=program,
        sha256=sha,
        base=base,
        rva=rva,
        name=best["name"],
        confidence=best["confidence"],
        source=best["source"],
        kind="symbol",
        conflicts=conflicts,
        notes=notes,
    )


def _choose_address(
    db: DB, build: str, value: int, base: int, addr_kind: str | None
) -> tuple[int, list[str]]:
    notes: list[str] = []
    if addr_kind == "va":
        if base and value < base:
            raise NotFound(f"{fmt_addr(value)} is below image base {fmt_addr(base)}")
        return value - base, notes
    if addr_kind == "rva":
        return value, notes

    va_rva = value - base if base and value >= base else None
    direct = value

    va_hit = bool(va_rva is not None and db.symbols_at(build, va_rva))
    direct_hit = bool(db.symbols_at(build, direct))

    if va_hit and not direct_hit:
        return va_rva, notes
    if direct_hit and not va_hit:
        return direct, notes
    if va_hit and direct_hit and va_rva != direct:
        notes.append(
            f"address resolves both as VA ({fmt_addr(va_rva)}) and RVA ({fmt_addr(direct)}); "
            "using VA"
        )
        return va_rva, notes
    # No symbol evidence: 64-bit images have a base far above any RVA.
    if va_rva is not None and base >= 0x100000000:
        return va_rva, notes
    return direct, notes


def resolve_pair(
    db: DB, target: str, from_build: str, to_build: str
) -> tuple[Resolution, Resolution, bool]:
    """Resolve a diff target in both builds.

    Names resolve independently (an RVA can move). Raw addresses use the same
    RVA in both builds, because that is what the user asked to compare.
    """
    text = target.strip()
    is_addr = is_hex(text) or fun_addr(text) is not None
    a = resolve(db, text, from_build)
    if is_addr:
        b = resolve(db, fmt_addr(a.rva), to_build, addr_kind="rva")
        return a, b, True
    b = resolve(db, text, to_build)
    return a, b, False
