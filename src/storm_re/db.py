"""SQLite store for builds, symbols and the decompile cache."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import zlib
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS build (
    alias       TEXT PRIMARY KEY,
    program     TEXT,
    arch        TEXT,
    base        INTEGER,
    sha256      TEXT,
    source      TEXT,
    indexed     INTEGER DEFAULT 0,
    present     INTEGER DEFAULT 0,
    description TEXT
);
CREATE TABLE IF NOT EXISTS program (
    name          TEXT PRIMARY KEY,
    file_path     TEXT,
    sha256        TEXT,
    host          TEXT,
    base          INTEGER,
    size          INTEGER,
    code_indexed  INTEGER,
    last_seen     INTEGER
);
CREATE TABLE IF NOT EXISTS symbol (
    build_alias  TEXT NOT NULL,
    rva          INTEGER NOT NULL,
    name         TEXT NOT NULL,
    short_name   TEXT,
    namespace    TEXT,
    confidence   TEXT,
    conf_rank    INTEGER DEFAULT 0,
    source       TEXT,
    source_rank  INTEGER DEFAULT 0,
    size         INTEGER,
    evidence     TEXT,
    PRIMARY KEY (build_alias, rva, name)
);
CREATE INDEX IF NOT EXISTS idx_symbol_name ON symbol(build_alias, name);
CREATE INDEX IF NOT EXISTS idx_symbol_short ON symbol(build_alias, short_name);
CREATE INDEX IF NOT EXISTS idx_symbol_rva ON symbol(build_alias, rva);
CREATE TABLE IF NOT EXISTS cache (
    sha256        TEXT NOT NULL,
    rva           INTEGER NOT NULL,
    kind          TEXT NOT NULL,
    params        TEXT NOT NULL,
    name_version  TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    raw           BLOB,
    summary       TEXT,
    raw_chars     INTEGER DEFAULT 0,
    summary_chars INTEGER DEFAULT 0,
    hit_count     INTEGER DEFAULT 0,
    PRIMARY KEY (sha256, rva, kind, params, name_version)
);
CREATE INDEX IF NOT EXISTS idx_cache_rva ON cache(sha256, rva);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS bsim_edge (
    build_alias  TEXT NOT NULL,
    rva          INTEGER NOT NULL,
    target_exe   TEXT,
    target_build TEXT,
    target_rva   INTEGER,
    target_name  TEXT,
    similarity   REAL,
    significance REAL,
    PRIMARY KEY (build_alias, rva, target_exe, target_rva)
);
CREATE INDEX IF NOT EXISTS idx_bsim_target
    ON bsim_edge(build_alias, target_build, target_rva);
CREATE TABLE IF NOT EXISTS build_map (
    name        TEXT NOT NULL,
    from_build  TEXT NOT NULL,
    from_rva    INTEGER NOT NULL,
    to_build    TEXT NOT NULL,
    to_rva      INTEGER NOT NULL,
    method      TEXT,
    confidence  TEXT,
    score       REAL,
    created_at  INTEGER,
    PRIMARY KEY (name, from_build, to_build)
);
CREATE TABLE IF NOT EXISTS index_entry (
    topic         TEXT NOT NULL,
    build_alias   TEXT NOT NULL,
    rva           INTEGER NOT NULL,
    name          TEXT,
    target        TEXT,
    sha256        TEXT,
    name_version  TEXT,
    signature     TEXT,
    summary       TEXT,
    text          TEXT,
    symbolized    TEXT,
    raw_chars     INTEGER,
    summary_chars INTEGER,
    status        TEXT,
    created_at    INTEGER,
    PRIMARY KEY (topic, build_alias, name)
);
CREATE INDEX IF NOT EXISTS idx_index_name ON index_entry(name);
"""


class DBError(RuntimeError):
    pass


class DB:
    def __init__(self, path: Path | str, create: bool = True):
        self.path = Path(path).expanduser()
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            raise DBError(f"database not found: {self.path} (run `storm-re init`)")
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(index_entry)")]
        if "target" not in cols:
            self.conn.execute("ALTER TABLE index_entry ADD COLUMN target TEXT")
            cols.append("target")
        if "symbolized" not in cols:
            self.conn.execute("ALTER TABLE index_entry ADD COLUMN symbolized TEXT")
        self.conn.commit()

    def __enter__(self) -> "DB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- meta --------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value)
        )
        self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # -- builds ------------------------------------------------------------

    def upsert_build(
        self,
        alias: str,
        program: str,
        sha256: str = "",
        base: int = 0,
        arch: str = "",
        source: str = "pyghidra",
        indexed: int = 0,
        present: int = 1,
        description: str = "",
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO build
               (alias, program, arch, base, sha256, source, indexed, present, description)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (alias, program, arch, base, sha256, source, indexed, present, description),
        )
        self.conn.commit()

    def upsert_program(
        self,
        name: str,
        file_path: str = "",
        sha256: str = "",
        host: str = "local",
        base: int = 0,
        size: int = 0,
        code_indexed: int = 0,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO program
               (name, file_path, sha256, host, base, size, code_indexed, last_seen)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, file_path, sha256, host, base, size, code_indexed, int(time.time())),
        )
        self.conn.commit()

    def get_build(self, alias: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM build WHERE alias=?", (alias,)).fetchone()

    def list_builds(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT b.*,
                          (SELECT COUNT(*) FROM symbol s WHERE s.build_alias=b.alias) AS symbols,
                          (SELECT COUNT(*) FROM cache c WHERE c.sha256=b.sha256) AS cache_entries
                   FROM build b ORDER BY b.alias"""
            )
        )

    # -- symbols -----------------------------------------------------------

    def clear_symbols(self, build_alias: str) -> None:
        self.conn.execute("DELETE FROM symbol WHERE build_alias=?", (build_alias,))
        self.conn.commit()

    def add_symbols(self, rows: list[tuple], build_alias: str) -> None:
        """rows: (rva, name, short, namespace, confidence, conf_rank,
                  source, source_rank, size, evidence)"""
        payload = [(build_alias, *r) for r in rows]
        self.conn.executemany(
            """INSERT OR REPLACE INTO symbol
               (build_alias, rva, name, short_name, namespace, confidence,
                conf_rank, source, source_rank, size, evidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )
        self.conn.commit()

    def symbol_count(self, build_alias: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT rva) AS n FROM symbol WHERE build_alias=?",
            (build_alias,),
        ).fetchone()
        return int(row["n"] if row else 0)

    def symbol_version(self, build_alias: str) -> str:
        h = hashlib.sha1()
        for row in self.conn.execute(
            "SELECT rva, name FROM symbol WHERE build_alias=? ORDER BY rva, name",
            (build_alias,),
        ):
            h.update(f"{row['rva']}:{row['name']}\n".encode("utf-8"))
        return h.hexdigest()[:16]

    def set_symbol_version(self, build_alias: str) -> str:
        version = self.symbol_version(build_alias)
        self.set_meta(f"name_version:{build_alias}", version)
        return version

    def name_version(self, build_alias: str) -> str:
        return self.get_meta(f"name_version:{build_alias}", "0") or "0"

    def symbols_prefix(
        self, build_alias: str, prefix: str, limit: int = 2000
    ) -> list[sqlite3.Row]:
        escaped = (
            prefix.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        rows = list(
            self.conn.execute(
                """SELECT * FROM symbol
                   WHERE build_alias=? AND name LIKE ? ESCAPE '\\'
                   ORDER BY source_rank DESC, conf_rank DESC,
                            COALESCE(size,0) DESC, name""",
                (build_alias, escaped + "%"),
            )
        )
        out, seen = [], set()
        for row in rows:
            rva = int(row["rva"])
            if rva in seen:
                continue
            seen.add(rva)
            out.append(row)
            if len(out) >= limit:
                break
        return out

    def common_symbols(self, from_build: str, to_build: str, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT a.name AS name
                   FROM symbol a JOIN symbol b ON a.name = b.name
                   WHERE a.build_alias=? AND b.build_alias=?
                     AND a.name NOT LIKE 'FUN_%'
                     AND a.name NOT LIKE '%catch%'
                     AND (a.name LIKE 'cc%' OR a.name LIKE 'Nucc%'
                          OR a.name LIKE 'ns%' OR a.name LIKE 'mm%')
                   GROUP BY a.name
                   ORDER BY COALESCE(MAX(a.size),0) DESC, a.name
                   LIMIT ?""",
                (from_build, to_build, limit),
            )
        )

    def copy_symbols(
        self, from_build: str, to_build: str, source: str, confidence: str = "medium"
    ) -> int:
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO symbol
               (build_alias, rva, name, short_name, namespace, confidence,
                conf_rank, source, source_rank, size, evidence)
               SELECT ?, rva, name, short_name, namespace, ?, 2, ?, 2, size, evidence
               FROM symbol WHERE build_alias=?""",
            (to_build, confidence, source, from_build),
        )
        self.conn.commit()
        return cur.rowcount

    def common_symbol_rows(self, from_build: str, to_build: str, limit: int = 200000):
        return list(
            self.conn.execute(
                """SELECT a.name AS name,
                          MIN(a.rva) AS a_rva, MAX(a.size) AS a_size,
                          MIN(b.rva) AS b_rva, MAX(b.size) AS b_size
                   FROM symbol a JOIN symbol b ON a.name = b.name
                   WHERE a.build_alias=? AND b.build_alias=?
                     AND a.name NOT LIKE 'FUN_%'
                     AND a.name NOT LIKE '%catch%'
                     AND (a.name LIKE 'cc%' OR a.name LIKE 'Nucc%'
                          OR a.name LIKE 'ns%' OR a.name LIKE 'mm%')
                   GROUP BY a.name
                   ORDER BY COALESCE(MAX(a.size),0) DESC, a.name
                   LIMIT ?""",
                (from_build, to_build, limit),
            )
        )

    def symbols_at(self, build_alias: str, rva: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT * FROM symbol WHERE build_alias=? AND rva=?
                   ORDER BY source_rank DESC, conf_rank DESC, name""",
                (build_alias, rva),
            )
        )

    def exact_symbols(self, build_alias: str, query: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT * FROM symbol
                   WHERE build_alias=?
                     AND (name = ? COLLATE NOCASE OR short_name = ? COLLATE NOCASE)
                   ORDER BY source_rank DESC, conf_rank DESC, name LIMIT 100""",
                (build_alias, query, query),
            )
        )

    def like_symbols(self, build_alias: str, pattern: str, limit: int = 200) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT * FROM symbol
                   WHERE build_alias=?
                     AND (name LIKE ? ESCAPE '\\' COLLATE NOCASE
                          OR short_name LIKE ? ESCAPE '\\' COLLATE NOCASE)
                   ORDER BY source_rank DESC, conf_rank DESC, name LIMIT ?""",
                (build_alias, pattern, pattern, limit),
            )
        )

    # -- cache -------------------------------------------------------------

    def cache_get(
        self, sha256: str, rva: int, kind: str, params: str, name_version: str
    ) -> dict | None:
        row = self.conn.execute(
            """SELECT * FROM cache
               WHERE sha256=? AND rva=? AND kind=? AND params=? AND name_version=?""",
            (sha256, rva, kind, params, name_version),
        ).fetchone()
        if not row:
            return None
        self.conn.execute(
            """UPDATE cache SET hit_count=hit_count+1
               WHERE sha256=? AND rva=? AND kind=? AND params=? AND name_version=?""",
            (sha256, rva, kind, params, name_version),
        )
        self.conn.commit()
        try:
            raw = json.loads(zlib.decompress(row["raw"]).decode("utf-8"))
        except Exception as exc:  # corrupt cache entry
            raise DBError(f"corrupt cache entry for rva 0x{rva:X}: {exc}") from exc
        return {
            "raw": raw,
            "summary": json.loads(row["summary"]) if row["summary"] else None,
            "raw_chars": row["raw_chars"],
            "summary_chars": row["summary_chars"],
            "hit_count": row["hit_count"] + 1,
            "created_at": row["created_at"],
        }

    def cache_put(
        self,
        sha256: str,
        rva: int,
        kind: str,
        params: str,
        name_version: str,
        raw: dict,
        summary: dict,
        raw_chars: int,
        summary_chars: int,
    ) -> None:
        blob = zlib.compress(json.dumps(raw, separators=(",", ":")).encode("utf-8"), 6)
        self.conn.execute(
            """INSERT OR REPLACE INTO cache
               (sha256, rva, kind, params, name_version, created_at,
                raw, summary, raw_chars, summary_chars, hit_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
            (
                sha256,
                rva,
                kind,
                params,
                name_version,
                int(time.time()),
                blob,
                json.dumps(summary, separators=(",", ":")),
                raw_chars,
                summary_chars,
            ),
        )
        self.conn.commit()

    def cache_delete(
        self, sha256: str, rva: int, kind: str, params: str, name_version: str
    ) -> int:
        cur = self.conn.execute(
            """DELETE FROM cache
               WHERE sha256=? AND rva=? AND kind=? AND params=? AND name_version=?""",
            (sha256, rva, kind, params, name_version),
        )
        self.conn.commit()
        return cur.rowcount

    def cache_clear(self, sha256: str | None = None) -> int:
        if sha256:
            cur = self.conn.execute("DELETE FROM cache WHERE sha256=?", (sha256,))
        else:
            cur = self.conn.execute("DELETE FROM cache")
        self.conn.commit()
        return cur.rowcount

    # -- bsim edges --------------------------------------------------------

    def bsim_replace(self, build_alias: str, rows: list[tuple]) -> None:
        """rows: (rva, target_exe, target_build, target_rva, target_name, sim, sig)"""
        self.conn.execute("DELETE FROM bsim_edge WHERE build_alias=?", (build_alias,))
        self.conn.executemany(
            """INSERT OR REPLACE INTO bsim_edge
               (build_alias, rva, target_exe, target_build, target_rva,
                target_name, similarity, significance)
               VALUES (?,?,?,?,?,?,?,?)""",
            [(build_alias, *r) for r in rows],
        )
        self.conn.commit()

    def bsim_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM bsim_edge").fetchone()
        return int(row["n"] if row else 0)

    def bsim_for(self, build_alias: str, rva: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT * FROM bsim_edge WHERE build_alias=? AND rva=?
                   ORDER BY similarity DESC, significance DESC""",
                (build_alias, rva),
            )
        )

    def bsim_reverse(
        self, build_alias: str, target_build: str, target_rva: int
    ) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """SELECT * FROM bsim_edge
                   WHERE build_alias=? AND target_build=? AND target_rva=?
                   ORDER BY similarity DESC, significance DESC""",
                (build_alias, target_build, target_rva),
            )
        )

    def bsim_by_targets(
        self, build_alias: str, target_build: str, target_rvas: list[int]
    ) -> list[sqlite3.Row]:
        if not target_rvas:
            return []
        out: list[sqlite3.Row] = []
        for i in range(0, len(target_rvas), 400):
            chunk = target_rvas[i : i + 400]
            marks = ",".join("?" for _ in chunk)
            out.extend(
                self.conn.execute(
                    f"""SELECT * FROM bsim_edge
                        WHERE build_alias=? AND target_build=?
                          AND target_rva IN ({marks})
                        ORDER BY similarity DESC""",
                    (build_alias, target_build, *chunk),
                )
            )
        return out

    # -- build map ---------------------------------------------------------

    def map_put(
        self,
        name: str,
        from_build: str,
        from_rva: int,
        to_build: str,
        to_rva: int,
        method: str,
        confidence: str,
        score: float,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO build_map
               (name, from_build, from_rva, to_build, to_rva, method,
                confidence, score, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                name,
                from_build,
                from_rva,
                to_build,
                to_rva,
                method,
                confidence,
                score,
                int(time.time()),
            ),
        )
        self.conn.commit()

    def map_get(self, name: str, from_build: str, to_build: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT * FROM build_map
               WHERE name=? AND from_build=? AND to_build=?""",
            (name, from_build, to_build),
        ).fetchone()

    def map_list(self, name: str, from_build: str | None = None) -> list[sqlite3.Row]:
        if from_build:
            return list(
                self.conn.execute(
                    """SELECT * FROM build_map WHERE name=? AND from_build=?
                       ORDER BY to_build""",
                    (name, from_build),
                )
            )
        return list(
            self.conn.execute(
                "SELECT * FROM build_map WHERE name=? ORDER BY from_build, to_build",
                (name,),
            )
        )

    def map_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM build_map").fetchone()
        return int(row["n"] if row else 0)

    # -- hot index ---------------------------------------------------------

    def index_put(
        self,
        *,
        topic: str,
        build_alias: str,
        rva: int,
        name: str | None,
        target: str,
        sha256: str,
        name_version: str,
        signature: str,
        summary: str,
        text: str,
        symbolized: str = "",
        raw_chars: int,
        summary_chars: int,
        status: str,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO index_entry
               (topic, build_alias, rva, name, target, sha256, name_version, signature,
                summary, text, symbolized, raw_chars, summary_chars, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                topic,
                build_alias,
                rva,
                name,
                target,
                sha256,
                name_version,
                signature,
                summary,
                text,
                symbolized,
                raw_chars,
                summary_chars,
                status,
                int(time.time()),
            ),
        )
        self.conn.commit()

    def index_get_target(self, topic: str, build_alias: str, target: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT * FROM index_entry
               WHERE topic=? AND build_alias=? AND target=?
               ORDER BY created_at DESC LIMIT 1""",
            (topic, build_alias, target),
        ).fetchone()

    def index_clear(self, topic: str, build_alias: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM index_entry WHERE topic=? AND build_alias=?",
            (topic, build_alias),
        )
        self.conn.commit()
        return cur.rowcount

    def index_delete_target(self, topic: str, build_alias: str, target: str) -> int:
        cur = self.conn.execute(
            """DELETE FROM index_entry
               WHERE topic=? AND build_alias=? AND target=?""",
            (topic, build_alias, target),
        )
        self.conn.commit()
        return cur.rowcount

    def index_get(self, topic: str, build_alias: str, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT * FROM index_entry
               WHERE topic=? AND build_alias=? AND name=?""",
            (topic, build_alias, name),
        ).fetchone()

    def index_list(
        self, topic: str | None = None, build_alias: str | None = None, limit: int = 200
    ) -> list[sqlite3.Row]:
        clauses, params = [], []
        if topic:
            clauses.append("topic=?")
            params.append(topic)
        if build_alias:
            clauses.append("build_alias=?")
            params.append(build_alias)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        return list(
            self.conn.execute(
                f"SELECT * FROM index_entry{where} ORDER BY topic, build_alias, rva LIMIT ?",
                params,
            )
        )

    def index_search(self, query: str, limit: int = 50) -> list[sqlite3.Row]:
        q = f"%{query}%"
        return list(
            self.conn.execute(
                """SELECT * FROM index_entry
                   WHERE name LIKE ? ESCAPE '\\' COLLATE NOCASE
                      OR topic LIKE ? ESCAPE '\\' COLLATE NOCASE
                   ORDER BY topic, build_alias, rva LIMIT ?""",
                (q, q, limit),
            )
        )

    def index_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM index_entry").fetchone()
        return int(row["n"] if row else 0)

    def index_stats(self) -> dict:
        row = self.conn.execute(
            """SELECT COUNT(*) AS n,
                      COALESCE(SUM(raw_chars),0) AS raw_chars,
                      COALESCE(SUM(summary_chars),0) AS summary_chars
               FROM index_entry WHERE status='ok'"""
        ).fetchone()
        raw = int(row["raw_chars"])
        saved = 0.0 if raw == 0 else 100.0 * (1 - row["summary_chars"] / raw)
        return {
            "entries": int(row["n"]),
            "raw_chars": raw,
            "summary_chars": int(row["summary_chars"]),
            "saved_pct": round(saved, 1),
        }

    def stats(self) -> dict:
        row = self.conn.execute(
            """SELECT COUNT(*) AS entries,
                      COALESCE(SUM(raw_chars),0) AS raw_chars,
                      COALESCE(SUM(summary_chars),0) AS summary_chars,
                      COALESCE(SUM(hit_count),0) AS hits,
                      COALESCE(SUM(LENGTH(raw)),0) AS blob_bytes
               FROM cache"""
        ).fetchone()
        sym = self.conn.execute("SELECT COUNT(*) AS n FROM symbol").fetchone()
        raw_chars = int(row["raw_chars"])
        saved = 0.0 if raw_chars == 0 else 100.0 * (1 - row["summary_chars"] / raw_chars)
        return {
            "db": str(self.path),
            "db_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "cache_entries": int(row["entries"]),
            "cache_blob_bytes": int(row["blob_bytes"]),
            "cache_hits": int(row["hits"]),
            "symbols": int(sym["n"]),
            "raw_chars": raw_chars,
            "summary_chars": int(row["summary_chars"]),
            "saved_pct": round(saved, 1),
            "bsim_edges": self.bsim_count(),
            "build_maps": self.map_count(),
            "index_entries": self.index_count(),
        }
