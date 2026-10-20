"""Build/program discovery and symbol ingestion."""

from __future__ import annotations

import csv
import glob
from pathlib import Path

from . import config
from .text import split_name

CHUNK = 5000


def _int(value: str | None, default: int = 0) -> int:
    """CSV integer: 0x-prefixed or bare hex, decimal fallback."""
    if value is None:
        return default
    v = value.strip().replace(",", "")
    if not v:
        return default
    try:
        return int(v, 0)
    except ValueError:
        try:
            return int(v, 16)
        except ValueError:
            return default


def _hex_int(value: str | None, default: int = 0) -> int:
    """Ghidra metadata addresses are hex without 0x (e.g. '140000000')."""
    if value is None:
        return default
    v = value.strip().replace(",", "")
    if v.lower().startswith("0x"):
        v = v[2:]
    try:
        return int(v, 16)
    except ValueError:
        return default


def _dec_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    v = value.strip().replace(",", "")
    try:
        return int(v, 10)
    except ValueError:
        return default


def _clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(x) for x in value).strip()
    return str(value).strip()


def _conf_rank(conf: str) -> int:
    return config.CONF_RANK.get((conf or "").strip().lower(), 0)


def discover(db, client, quiet: bool = False) -> dict:
    """Fetch programs + metadata and upsert builds. Returns a summary."""
    listing = client.call_tool("list_project_binaries", {})
    programs = listing.get("programs", listing if isinstance(listing, list) else [])
    by_name = {p.get("name"): p for p in programs if p.get("name")}

    found, missing = [], []
    for alias, meta in config.BUILDS.items():
        program = meta["program"]
        p = by_name.get(program)
        if not p:
            missing.append(alias)
            db.upsert_build(
                alias,
                program,
                present=0,
                description=meta.get("desc", ""),
            )
            continue
        md = client.call_tool(
            "list_project_binary_metadata", {"binary_name": program}
        )
        sha = (md.get("Executable SHA256") or "").strip()
        base = _hex_int(md.get("Minimum Address"), 0)
        size = _dec_int(md.get("# of Bytes"), 0)
        arch = f"{md.get('Processor', '?')}:{md.get('Address Size', '?')}"
        db.upsert_build(
            alias,
            program,
            sha256=sha,
            base=base,
            arch=arch,
            source="pyghidra",
            indexed=1 if p.get("code_indexed") else 0,
            present=1,
            description=meta.get("desc", ""),
        )
        db.upsert_program(
            program,
            file_path=p.get("file_path", ""),
            sha256=sha,
            host=config.host_label(),
            base=base,
            size=size,
            code_indexed=1 if p.get("code_indexed") else 0,
        )
        found.append(alias)
        if not quiet:
            print(f"  {alias:<12} {program:<34} {sha[:12]} base=0x{base:X}")

    if not quiet:
        print(f"programs: {len(found)} found, {len(missing)} absent")
    return {"found": found, "missing": missing}


def ingest_nucc(db, root: Path, quiet: bool = False) -> dict:
    """Ingest every ~/nucc-symbols/games/*/<sha>/functions.csv whose sha is known."""
    sha_to_builds: dict[str, list[str]] = {}
    for row in db.conn.execute("SELECT alias, sha256 FROM build WHERE present=1"):
        if row["sha256"]:
            sha_to_builds.setdefault(row["sha256"], []).append(row["alias"])

    counts: dict[str, int] = {}
    pattern = str(root / "games" / "*" / "*" / "functions.csv")
    for path_str in sorted(glob.glob(pattern)):
        path = Path(path_str)
        sha = path.parent.name
        builds = sha_to_builds.get(sha)
        if not builds:
            if not quiet:
                print(f"  skip nucc (unknown sha): {path}")
            continue
        rows: list[tuple] = []
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for rec in csv.DictReader(fh):
                rva_s = _clean(rec.get("rva"))
                name = _clean(rec.get("name"))
                if not rva_s or not name:
                    continue
                rva = _int(rva_s)
                short = _clean(rec.get("short_name")) or split_name(name)[1]
                ns = _clean(rec.get("namespace")) or split_name(name)[0]
                conf = _clean(rec.get("confidence"))
                rows.append(
                    (
                        rva,
                        name,
                        short,
                        ns,
                        conf,
                        _conf_rank(conf),
                        "nucc",
                        config.SOURCE_RANK["nucc"],
                        _int(_clean(rec.get("size"))),
                        _clean(rec.get("evidence"))[:400],
                    )
                )
        for alias in builds:
            for i in range(0, len(rows), CHUNK):
                db.add_symbols(rows[i : i + CHUNK], alias)
            counts[alias] = len(rows)
            if not quiet:
                print(f"  {alias:<12} {len(rows):>6} nucc symbols")
    return counts


def ingest_manual(db, root: Path, quiet: bool = False) -> dict:
    counts: dict[str, int] = {}
    for filename, alias in config.MANUAL_SOURCES:
        path = root / filename
        if not path.exists():
            if not quiet:
                print(f"  manual missing: {path}")
            continue
        rows: list[tuple] = []
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for raw in csv.DictReader(fh):
                rec = {}
                for k, v in raw.items():
                    if k is None:
                        continue
                    rec[k.strip()] = _clean(v)
                rva_s = rec.get("rva", "")
                name = rec.get("name", "")
                if not rva_s or not name:
                    continue
                rva = _int(rva_s)
                short = split_name(name)[1]
                ns = split_name(name)[0]
                conf = rec.get("confidence", "")
                rows.append(
                    (
                        rva,
                        name,
                        short,
                        ns,
                        conf,
                        _conf_rank(conf),
                        f"manual:{filename}",
                        config.SOURCE_RANK["manual"],
                        None,
                        rec.get("evidence", "")[:400],
                    )
                )
        for i in range(0, len(rows), CHUNK):
            db.add_symbols(rows[i : i + CHUNK], alias)
        counts[alias] = counts.get(alias, 0) + len(rows)
        if not quiet:
            print(f"  {alias:<12} {len(rows):>6} manual symbols ({filename})")
    return counts


def ingest_trilogy(db, path: Path, quiet: bool = False) -> int:
    if not path.exists():
        if not quiet:
            print(f"  trilogy tsv missing: {path}")
        return 0
    rows: list[tuple] = []
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                continue
            name = parts[-1].strip()
            if not name:
                continue
            rva = _int(parts[0])
            if rva == 0:
                continue
            short = split_name(name)[1]
            ns = split_name(name)[0]
            rows.append(
                (
                    rva,
                    name,
                    short,
                    ns,
                    "high",
                    _conf_rank("high"),
                    "trilogy",
                    config.SOURCE_RANK["trilogy"],
                    None,
                    "",
                )
            )
    db.clear_symbols("trilogy")
    for i in range(0, len(rows), CHUNK):
        db.add_symbols(rows[i : i + CHUNK], "trilogy")
    if not quiet:
        print(f"  {'trilogy':<12} {len(rows):>6} switch symbols")
    return len(rows)


def ingest_symbols(db, quiet: bool = False) -> dict:
    # Full rebuild: a build whose nucc CSV disappeared must not keep stale rows.
    for alias in config.BUILDS:
        db.clear_symbols(alias)
    nucc = ingest_nucc(db, config.nucc_root(), quiet=quiet)
    manual = ingest_manual(db, config.manual_root(), quiet=quiet)
    trilogy = ingest_trilogy(db, config.trilogy_tsv(), quiet=quiet)

    inherited = {}
    for alias, meta in config.BUILDS.items():
        fallback = meta.get("symbol_fallback")
        if not fallback:
            continue
        n = db.copy_symbols(fallback, alias, source=f"inherited:{fallback}")
        inherited[alias] = n
        if not quiet:
            print(f"  {alias:<12} {n:>6} inherited symbols ({fallback})")

    versions = {}
    for alias in config.BUILDS:
        versions[alias] = db.set_symbol_version(alias)
    db.set_meta("symbols_updated_at", str(__import__("time").time()))

    if not quiet:
        total = db.conn.execute("SELECT COUNT(*) AS n FROM symbol").fetchone()["n"]
        print(f"symbols total: {total}")
    return {
        "nucc": nucc,
        "manual": manual,
        "trilogy": trilogy,
        "inherited": inherited,
        "versions": versions,
    }


def init_registry(db, client, quiet: bool = False) -> dict:
    db.init_schema()
    discovered = discover(db, client, quiet=quiet)
    symbols = ingest_symbols(db, quiet=quiet)
    return {"builds": discovered, "symbols": symbols}
