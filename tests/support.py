"""Shared test helpers."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from storm_re.db import DB  # noqa: E402


def make_db(tmpdir) -> DB:
    db = DB(pathlib.Path(tmpdir) / "test.db")
    db.init_schema()
    db.upsert_build(
        "s4", "/NSUNS4_release.exe-test", sha256="a" * 64,
        base=0x140000000, arch="x86:64", present=1, description="1.09",
    )
    db.upsert_build(
        "s4-debug", "/NSUNS4_debug.exe-test", sha256="b" * 64,
        base=0x140000000, arch="x86:64", present=1, description="1.06",
    )
    db.upsert_build(
        "s4-107", "/NSUNS4_107.exe-test", sha256="c" * 64,
        base=0x140000000, arch="x86:64", present=1, description="1.07",
    )
    return db


def add_symbol(
    db: DB,
    build: str,
    rva: int,
    name: str,
    source: str = "nucc",
    conf: str = "high",
    source_rank: int | None = None,
) -> None:
    ns, _, short = name.rpartition("::")
    rank = source_rank if source_rank is not None else {"manual": 3, "nucc": 2, "ghidra": 1}[source]
    conf_rank = {"high": 3, "medium": 2, "low": 1}.get(conf, 0)
    db.add_symbols(
        [(rva, name, short, ns, conf, conf_rank, source, rank, None, "")],
        build,
    )


def decompile_payload(code: str, callers: int = 2, callees: list[str] | None = None) -> dict:
    xrefs = [
        {
            "function_name": f"caller_{i}",
            "from_address": f"1400{i:04X}",
            "to_address": "1407AB468",
            "type": "UNCONDITIONAL_CALL",
        }
        for i in range(callers)
    ]
    xrefs.append(
        {"function_name": None, "from_address": "148DAC5A0", "to_address": "1407AB468", "type": "DATA"}
    )
    return {
        "name": "FUN_1407ab468-1407ab468",
        "code": code,
        "signature": "void FUN_1407ab468(longlong *param_1,int param_2);",
        "error": None,
        "callees": callees or ["ccPlayer::ResetBunshinState", "FUN_14076b4b0"],
        "referenced_strings": [{"value": "ccPlayerGrp::Ctrl", "address": "140EF3558"}],
        "xrefs": xrefs,
    }
