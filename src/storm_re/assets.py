"""Index and inspect extracted Storm CPK trees.

Layout: <root>/<game>/<cpk dir>/<cpk name>/<entry path>. <root>/CPKS.tsv
(game, cpk) names the archive roots; files outside them are loose disc files.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path, PurePosixPath

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS asset (
    game   TEXT NOT NULL,
    rel    TEXT NOT NULL,
    cpk    TEXT NOT NULL,
    entry  TEXT NOT NULL,
    ext    TEXT,
    size   INTEGER,
    magic  TEXT,
    PRIMARY KEY (game, rel)
);
CREATE INDEX IF NOT EXISTS idx_asset_entry ON asset(entry);
CREATE INDEX IF NOT EXISTS idx_asset_ext ON asset(game, ext);
"""

ROW_KEYS = ("game", "rel", "cpk", "entry", "ext", "size", "magic")


def magic_of(head: bytes) -> str:
    head = head[:4]
    if len(head) == 4 and all(32 <= b < 127 for b in head):
        return head.decode("ascii")
    return head.hex()


def load_cpks(root: Path) -> dict[str, list[str]]:
    """game -> archive dirs (cpk path without .cpk), longest first."""
    out: dict[str, list[str]] = {}
    path = root / "CPKS.tsv"
    if not path.is_file():
        raise ValueError(f"missing {path} (game<TAB>cpk rows)")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith(("#", "game\t")):
            continue
        game, cpk = line.split("\t")[:2]
        out.setdefault(game, []).append(cpk[:-4] if cpk.lower().endswith(".cpk") else cpk)
    for dirs in out.values():
        dirs.sort(key=len, reverse=True)
    return out


def split_rel(rel: str, cpk_dirs: list[str]) -> tuple[str, str]:
    for d in cpk_dirs:
        if rel.startswith(d + "/"):
            return d + ".cpk", rel[len(d) + 1:]
    return "", rel


def scan(root: Path, games: list[str] | None = None):
    cpks = load_cpks(root)
    for game in sorted(cpks):
        if games and game not in games:
            continue
        base = root / game
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name.endswith(".tmp") or ".tmp/" in path.as_posix():
                continue
            rel = path.relative_to(base).as_posix()
            cpk, entry = split_rel(rel, cpks[game])
            with path.open("rb") as fh:
                head = fh.read(4)
            yield {
                "game": game, "rel": rel, "cpk": cpk, "entry": entry,
                "ext": PurePosixPath(entry).suffix.lower(),
                "size": path.stat().st_size, "magic": magic_of(head),
            }


def init_schema(db) -> None:
    db.conn.executescript(SCHEMA)


def index(db, root: Path, games: list[str] | None = None) -> dict:
    init_schema(db)
    t0 = time.time()
    rows = list(scan(root, games))
    done = sorted({r["game"] for r in rows} | set(games or []))
    with db.conn:
        for game in done:
            db.conn.execute("DELETE FROM asset WHERE game = ?", (game,))
        db.conn.executemany(
            f"INSERT INTO asset ({', '.join(ROW_KEYS)}) VALUES ({', '.join('?' * len(ROW_KEYS))})",
            [tuple(r[k] for k in ROW_KEYS) for r in rows],
        )
        db.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('assets_root', ?)", (str(root),)
        )
    return {"root": str(root), "games": done, "files": len(rows),
            "bytes": sum(r["size"] for r in rows), "sec": round(time.time() - t0, 1)}


def _paths(row: dict) -> dict:
    root = config.assets_root()
    win = config.assets_win_root().rstrip("\\")
    return {
        "path": str(root / row["game"] / row["rel"]),
        "win_path": (win + "\\" + row["game"] + "\\" + row["rel"].replace("/", "\\"))
                    if win else "",
    }


def find(db, query: str, game: str | None = None, ext: str | None = None,
         cpk: str | None = None, limit: int = 50) -> dict:
    init_schema(db)
    where, params = [], []
    q = query.strip()
    if any(c in q for c in "*?["):
        where.append("lower(rel) GLOB ?")
        params.append(("*" if not q.startswith("*") else "") + q.lower())
    elif q:
        where.append("instr(lower(rel), ?) > 0")
        params.append(q.lower())
    if game:
        where.append("game = ?")
        params.append(config.asset_game(game))
    if ext:
        where.append("ext = ?")
        params.append(ext.lower() if ext.startswith(".") else "." + ext.lower())
    if cpk:
        where.append("instr(lower(cpk), ?) > 0")
        params.append(cpk.lower())
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.conn.execute(f"SELECT COUNT(*) FROM asset{sql_where}", params).fetchone()[0]
    rows = db.conn.execute(
        f"SELECT {', '.join(ROW_KEYS)} FROM asset{sql_where} ORDER BY game, rel LIMIT ?",
        params + [int(limit)],
    ).fetchall()
    return {"query": query, "total": total,
            "results": [{**dict(r), **_paths(dict(r))} for r in rows]}


def summary(db) -> dict:
    init_schema(db)
    rows = db.conn.execute(
        """SELECT game, cpk, COUNT(*) AS files, SUM(size) AS bytes
           FROM asset GROUP BY game, cpk ORDER BY game, cpk"""
    ).fetchall()
    games: dict[str, dict] = {}
    for r in rows:
        g = games.setdefault(r["game"], {"files": 0, "bytes": 0, "cpks": []})
        g["files"] += r["files"]
        g["bytes"] += r["bytes"]
        g["cpks"].append({"cpk": r["cpk"] or "(loose)", "files": r["files"], "bytes": r["bytes"]})
    root = db.conn.execute("SELECT value FROM meta WHERE key = 'assets_root'").fetchone()
    return {"root": root[0] if root else None, "games": games}


def parse_xfbin(data: bytes) -> dict:
    """NUCC chunk table: types, paths, names and (type, path, name) chunk maps."""
    if data[:4] != b"NUCC":
        raise ValueError("not an xfbin (no NUCC magic)")
    (type_n, type_sz, path_n, path_sz, name_n, name_sz,
     map_n, _map_sz, _idx_n, _extra_n) = struct.unpack_from(">10I", data, 0x1C)
    pos = 0x44

    def strings(count: int, size: int) -> list[str]:
        nonlocal pos
        blob = data[pos:pos + size]
        pos += size
        out = [s.decode("utf-8", "replace") for s in blob.split(b"\0")[:count]]
        if len(out) != count:
            raise ValueError("xfbin string table truncated")
        return out

    types = strings(type_n, type_sz)
    paths = strings(path_n, path_sz)
    names = strings(name_n, name_sz)
    pos = (pos + 3) & ~3
    chunks = []
    for i in range(map_n):
        t, p, n = struct.unpack_from(">3I", data, pos + 12 * i)
        chunks.append({"type": types[t], "path": paths[p], "name": names[n]})
    return {"version": struct.unpack_from(">I", data, 4)[0], "types": types,
            "chunks": [c for c in chunks if c["type"] != "nuccChunkNull"]}


def info(db, game: str, path: str, max_chunks: int = 200) -> dict:
    init_schema(db)
    game = config.asset_game(game)
    path = path.replace("\\", "/").strip("/")
    rows = db.conn.execute(
        f"SELECT {', '.join(ROW_KEYS)} FROM asset WHERE game = ? AND (rel = ? OR entry = ?)",
        (game, path, path),
    ).fetchall()
    if not rows:
        raise ValueError(f"no asset {path!r} in {game} (try storm_asset_find)")
    if len(rows) > 1:
        raise ValueError(f"{path!r} is ambiguous in {game}: "
                         + ", ".join(r["rel"] for r in rows) + " (pass the full rel path)")
    row = dict(rows[0])
    out = {**row, **_paths(row)}
    others = db.conn.execute(
        "SELECT game, rel, size FROM asset WHERE entry = ? AND game != ? ORDER BY game",
        (row["entry"], game),
    ).fetchall()
    out["other_games"] = [{**dict(r), "same_size": r["size"] == row["size"]} for r in others]
    local = Path(out["path"])
    if row["magic"] == "NUCC" and local.is_file():
        try:
            x = parse_xfbin(local.read_bytes())
            out["xfbin"] = {**x, "chunk_count": len(x["chunks"]),
                            "chunks": x["chunks"][:max_chunks]}
        except (ValueError, struct.error, IndexError) as exc:
            out["xfbin_error"] = str(exc)
    return out
