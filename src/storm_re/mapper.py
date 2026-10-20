"""Cross-build mapping: BSim edges first, names/RVA as fallback."""

from __future__ import annotations

from dataclasses import dataclass

from . import config
from .db import DB
from .resolve import ResolveError, resolve
from .text import fmt_addr

CONF_SCORE = {"high": 0.9, "medium": 0.7, "low": 0.5, "": 0.4}
METHOD_RANK = {"bsim-direct": 4, "bsim-trilogy": 2, "name": 5, "rva": 1}


def _priority(method: str, score: float) -> int:
    """A same-name symbol is ground truth; a low-confidence name is not.

    Direct BSim beats a low-confidence name and any Trilogy-mediated guess.
    """
    if method == "name":
        return METHOD_RANK["name"] if confidence_for(score) in ("high", "medium") else 3
    return METHOD_RANK.get(method, 1)


@dataclass
class MapResult:
    name: str
    from_build: str
    from_rva: int
    to_build: str
    to_rva: int
    to_name: str | None
    method: str
    confidence: str
    score: float

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "from_build": self.from_build,
            "from_rva": fmt_addr(self.from_rva),
            "to_build": self.to_build,
            "to_rva": fmt_addr(self.to_rva),
            "to_name": self.to_name,
            "method": self.method,
            "confidence": self.confidence,
            "score": round(self.score, 4),
        }


def confidence_for(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def map_name(
    db: DB,
    name: str,
    from_build: str,
    to_build: str,
    refresh: bool = False,
) -> MapResult | None:
    from_alias = config.canonical_build(from_build)
    to_alias = config.canonical_build(to_build)
    if from_alias == to_alias:
        return None

    if not refresh:
        cached = db.map_get(name, from_alias, to_alias)
        if cached:
            return MapResult(
                name=cached["name"],
                from_build=cached["from_build"],
                from_rva=int(cached["from_rva"]),
                to_build=cached["to_build"],
                to_rva=int(cached["to_rva"]),
                to_name=_name_at(db, to_alias, int(cached["to_rva"])),
                method=cached["method"],
                confidence=cached["confidence"],
                score=float(cached["score"]),
            )

    a = resolve(db, name, from_alias)
    candidates: list[tuple[int, float, str]] = []

    # Direct edges, forward and reverse.
    for edge in db.bsim_for(from_alias, a.rva):
        if edge["target_build"] == to_alias:
            candidates.append((int(edge["target_rva"]), float(edge["similarity"]), "bsim-direct"))
    for edge in db.bsim_reverse(to_alias, from_alias, a.rva):
        candidates.append((int(edge["rva"]), float(edge["similarity"]), "bsim-direct"))

    # Trilogy-mediated edges.
    trilogy: dict[int, float] = {}
    for edge in db.bsim_for(from_alias, a.rva):
        if edge["target_build"] == "trilogy":
            trilogy[int(edge["target_rva"])] = max(
                trilogy.get(int(edge["target_rva"]), 0.0), float(edge["similarity"])
            )
    if trilogy:
        for edge in db.bsim_by_targets(to_alias, "trilogy", list(trilogy)):
            score = min(trilogy[int(edge["target_rva"])], float(edge["similarity"]))
            candidates.append((int(edge["rva"]), score, "bsim-trilogy"))

    # Same name in the target build (only if it is a real symbol, not a bare
    # address echo). For an address input, use the name resolved in the source
    # build, otherwise this would look up the literal "0x...".
    lookup_name = a.name or name
    try:
        b = resolve(db, lookup_name, to_alias)
        if b.kind == "symbol":
            candidates.append((b.rva, CONF_SCORE.get(b.confidence, 0.4), "name"))
    except ResolveError:
        pass

    # Same RVA, only if the target build actually has a symbol there.
    if db.symbols_at(to_alias, a.rva):
        candidates.append((a.rva, 0.4, "rva"))

    if not candidates:
        return None

    to_rva, score, method = max(
        candidates, key=lambda c: (_priority(c[2], c[1]), c[1])
    )
    result = MapResult(
        name=name,
        from_build=from_alias,
        from_rva=a.rva,
        to_build=to_alias,
        to_rva=to_rva,
        to_name=_name_at(db, to_alias, to_rva),
        method=method,
        confidence=confidence_for(score),
        score=score,
    )
    db.map_put(
        name,
        from_alias,
        a.rva,
        to_alias,
        to_rva,
        method,
        result.confidence,
        score,
    )
    return result


def map_all(db: DB, name: str, from_build: str, refresh: bool = False) -> tuple[list[MapResult], list[str]]:
    from_alias = config.canonical_build(from_build)
    results: list[MapResult] = []
    missing: list[str] = []
    for row in db.list_builds():
        alias = row["alias"]
        if alias == from_alias or not row["present"]:
            continue
        try:
            mapped = map_name(db, name, from_alias, alias, refresh=refresh)
        except ResolveError:
            mapped = None
        if mapped:
            results.append(mapped)
        else:
            missing.append(alias)
    results.sort(key=lambda r: (-r.score, r.to_build))
    return results, missing


def _name_at(db: DB, build: str, rva: int) -> str | None:
    rows = db.symbols_at(build, rva)
    return rows[0]["name"] if rows else None
