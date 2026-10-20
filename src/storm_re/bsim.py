"""Ingest precomputed BSim TSVs into SQLite.

No Ghidra, no BSim client: the BSim exports already contain the queried
function -> target function pairs.
"""

from __future__ import annotations

import glob
from collections import defaultdict
from pathlib import Path

from . import config
from .db import DB

DEFAULT_TOP = 3
DEFAULT_MIN_SIM = 0.5


def build_from_path(path: str | Path) -> str | None:
    name = Path(path).name
    for pattern, alias in config.TARGET_EXE_PATTERNS:
        if pattern in name:
            return alias
    return None


def normalize_target_exe(exe: str) -> str | None:
    for pattern, alias in config.TARGET_EXE_PATTERNS:
        if pattern in exe:
            return alias
    return None


def _bases(db: DB) -> dict[str, int]:
    bases = dict(config.BUILD_BASES)
    for row in db.conn.execute("SELECT alias, base FROM build WHERE base > 0"):
        bases[row["alias"]] = int(row["base"])
    return bases


def _rva(addr: int, base: int) -> int:
    return addr - base if base and addr >= base else addr


def parse_tsv(
    path: Path,
    build: str,
    bases: dict[str, int],
    top_k: int = DEFAULT_TOP,
    min_sim: float = DEFAULT_MIN_SIM,
) -> tuple[list[tuple], int, int]:
    """Return (rows, read, unknown_targets).

    row = (query_rva, target_exe, target_build, target_rva, target_name, sim, sig)
    """
    per_func: dict[int, list[tuple]] = defaultdict(list)
    read = 0
    unknown = 0
    with Path(path).open(errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 7:
                continue
            read += 1
            try:
                q_rva = int(parts[0], 16)
                target_addr = int(parts[3], 16)
                sim = float(parts[5])
                sig = float(parts[6])
            except ValueError:
                continue
            if sim < min_sim:
                continue
            target_build = normalize_target_exe(parts[2])
            if not target_build:
                unknown += 1
                continue
            t_rva = _rva(target_addr, bases.get(target_build, 0))
            per_func[q_rva].append(
                (q_rva, parts[2], target_build, t_rva, parts[4], sim, sig)
            )

    rows: list[tuple] = []
    for candidates in per_func.values():
        candidates.sort(key=lambda r: (-r[5], -r[6]))
        rows.extend(candidates[:top_k])
    return rows, read, unknown


def ingest(
    db: DB,
    root: Path | None = None,
    top_k: int = DEFAULT_TOP,
    min_sim: float = DEFAULT_MIN_SIM,
    quiet: bool = False,
) -> dict:
    root = Path(root or config.bsim_root()).expanduser()
    files = sorted(glob.glob(str(root / "*.bsim.tsv"))) + sorted(
        glob.glob(str(root / "win" / "*.bsim.tsv"))
    )
    bases = _bases(db)
    total_rows = total_read = total_unknown = 0
    per_build: dict[str, int] = {}
    skipped: list[str] = []

    for path_str in files:
        path = Path(path_str)
        build = build_from_path(path)
        if not build:
            skipped.append(path.name)
            continue
        rows, read, unknown = parse_tsv(path, build, bases, top_k, min_sim)
        db.bsim_replace(build, rows)
        per_build[build] = per_build.get(build, 0) + len(rows)
        total_rows += len(rows)
        total_read += read
        total_unknown += unknown
        if not quiet:
            print(
                f"  {build:<12} {path.name:<44} "
                f"read {read:>7} kept {len(rows):>7} unknown {unknown:>6}"
            )

    if not quiet:
        print(f"bsim: {total_rows} edges from {total_read} rows")
        if skipped:
            print(f"skipped (no build): {', '.join(skipped)}")
    return {
        "edges": total_rows,
        "rows": total_read,
        "unknown_targets": total_unknown,
        "per_build": per_build,
        "skipped": skipped,
        "root": str(root),
    }
