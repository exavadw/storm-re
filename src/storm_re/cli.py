"""storm-re command line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, commands
from .db import DBError
from .mcp import MCPError
from .resolve import ResolveError

EXIT = {"usage": 1, "resolve": 2, "backend": 3, "diff": 4, "db": 5}


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--db", help="SQLite database path (default ~/.local/share/storm-re/storm-re.db)")
    p.add_argument("--mcp", help="pyghidra-mcp URL (default STORM_RE_MCP, config file, or http://127.0.0.1:8770/mcp)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--quiet", action="store_true", help="less progress output")
    p.add_argument("--timeout", type=float, default=180.0, help="backend timeout seconds")
    p.add_argument("--no-cache", action="store_true", help="bypass the decompile cache")
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    p = argparse.ArgumentParser(
        prog="storm-re",
        description="Storm-aware resolver and decompile cache in front of pyghidra-mcp.",
        parents=[common],
    )
    p.add_argument("--version", action="version", version=f"storm-re {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", parents=[common], help="discover builds and ingest symbols")
    sp.add_argument("--refresh", action="store_true", help="(accepted for symmetry; init always refreshes)")
    sp.set_defaults(func=commands.cmd_init)

    sp = sub.add_parser("builds", parents=[common], help="list builds, programs and shas")
    sp.set_defaults(func=commands.cmd_builds)

    sp = sub.add_parser("resolve", parents=[common], help="resolve VA, RVA or name in a build")
    sp.add_argument("target")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--addr-kind", choices=["va", "rva"], default=None)
    sp.set_defaults(func=commands.cmd_resolve)

    sp = sub.add_parser("decomp", parents=[common], help="bounded decompile summary")
    sp.add_argument("target")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--addr-kind", choices=["va", "rva"], default=None)
    sp.add_argument("--detail", choices=["sig", "summary", "code", "full"], default="summary")
    sp.add_argument("--max-bytes", type=int, default=8000)
    sp.add_argument("--head", type=int, default=0, help="include the first N source lines")
    sp.add_argument("--refresh", action="store_true", help="ignore the cache and re-fetch")
    sp.set_defaults(func=commands.cmd_decomp)

    sp = sub.add_parser("xrefs", parents=[common], help="callers, callees and data refs")
    sp.add_argument("target")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--addr-kind", choices=["va", "rva"], default=None)
    sp.add_argument("--direction", choices=["to", "from", "both"], default="to")
    sp.add_argument("--limit", type=int, default=100)
    sp.set_defaults(func=commands.cmd_xrefs)

    sp = sub.add_parser("diff", parents=[common], help="compare one target across two builds")
    sp.add_argument("target")
    sp.add_argument("--from", dest="from_build", required=True)
    sp.add_argument("--to", dest="to_build", required=True)
    sp.add_argument("--map", dest="use_map", action="store_true",
                    help="pick the counterpart RVA from build_map")
    sp.set_defaults(func=commands.cmd_diff)

    sp = sub.add_parser("find", parents=[common], help="search symbols, strings or code")
    sp.add_argument("query")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--mode", choices=["symbol", "string", "code"], default="symbol")
    sp.add_argument("--semantic", action="store_true", help="semantic code search")
    sp.add_argument("--limit", type=int, default=25)
    sp.set_defaults(func=commands.cmd_find)

    sp = sub.add_parser("state_surface", parents=[common], help="static field-access surface for a root")
    sp.add_argument("root", help="class prefix (ccPlayer), function name, or address")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--limit", type=int, default=40, help="max seed functions")
    sp.add_argument("--max-offset", type=lambda s: int(s, 0), default=0x40000)
    sp.add_argument("--param", default="param_1")
    sp.add_argument("--seeds", help="comma-separated explicit functions (replaces prefix seeds)")
    sp.add_argument("--min-writes", type=int, default=0)
    sp.add_argument("--max-fields", type=int, default=120)
    sp.set_defaults(func=commands.cmd_state_surface)

    sp = sub.add_parser("write_sites", parents=[common], help="who writes an address or root+offset")
    sp.add_argument("target", help="address, or root class when --offset is used")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--offset", type=lambda s: int(s, 0), default=None, help="byte offset, e.g. 0xCC0")
    sp.add_argument("--root", help="root class/function for offset mode")
    sp.add_argument("--seeds", help="comma-separated explicit functions")
    sp.add_argument("--param", default="param_1")
    sp.add_argument("--include-reads", action="store_true")
    sp.add_argument("--include-calls", action="store_true")
    sp.add_argument("--limit", type=int, default=100)
    sp.set_defaults(func=commands.cmd_write_sites)

    sp = sub.add_parser("input_path", parents=[common], help="map the pad input chain")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--depth", type=int, default=1)
    sp.add_argument("--limit", type=int, default=80)
    sp.set_defaults(func=commands.cmd_input_path)

    sp = sub.add_parser("frame_tick", parents=[common], help="timer idioms and per-frame constants")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--limit", type=int, default=30)
    sp.add_argument("--seeds", help="comma-separated explicit functions")
    sp.set_defaults(func=commands.cmd_frame_tick)

    sp = sub.add_parser("net_session", parents=[common], help="Steam/net-session surface")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--limit", type=int, default=25)
    sp.add_argument("--seeds", help="comma-separated explicit functions")
    sp.add_argument("--no-imports", action="store_true")
    sp.set_defaults(func=commands.cmd_net_session)

    sp = sub.add_parser("scene_dispatch", parents=[common], help="story scene/message dispatch")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--seeds", help="comma-separated explicit functions")
    sp.set_defaults(func=commands.cmd_scene_dispatch)

    sp = sub.add_parser("patch_diff", parents=[common], help="batch function diff between builds")
    sp.add_argument("--from", dest="from_build", required=True)
    sp.add_argument("--to", dest="to_build", required=True)
    sp.add_argument("--limit", type=int, default=20)
    sp.add_argument("--seeds", help="comma-separated explicit functions")
    sp.add_argument("--include-same", action="store_true")
    sp.add_argument("--no-byte-diff", action="store_true", help="use decompiled text instead of PE bytes")
    sp.set_defaults(func=commands.cmd_patch_diff)

    sp = sub.add_parser("export", parents=[common], help="write a markdown report from indexed facts")
    sp.add_argument("topic")
    sp.add_argument("-b", "--build")
    sp.add_argument("--out", help="output path, or - for stdout")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--code", action="store_true", help="include symbolized/text code")
    sp.set_defaults(func=commands.cmd_export)

    sp = sub.add_parser("explain", parents=[common], help="one-call function explanation")
    sp.add_argument("target")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--max-bytes", type=int, default=8000)
    sp.set_defaults(func=commands.cmd_explain)

    sp = sub.add_parser("stat", parents=[common], help="database and cache statistics")
    sp.set_defaults(func=commands.cmd_stat)

    sp = sub.add_parser("bsim", parents=[common], help="ingest or inspect BSim TSVs")
    sp.add_argument("action", choices=["ingest", "stat"])
    sp.add_argument("--root", help="directory with *.bsim.tsv (default ~/ghidra/match/out)")
    sp.add_argument("--top", type=int, default=3, help="keep top K targets per function")
    sp.add_argument("--min-sim", type=float, default=0.5)
    sp.set_defaults(func=commands.cmd_bsim)

    sp = sub.add_parser("map", parents=[common], help="map a symbol across builds")
    sp.add_argument("name")
    sp.add_argument("--from", dest="from_build", default="s4")
    sp.add_argument("--to", help="comma-separated target builds (default: all)")
    sp.add_argument("--refresh", action="store_true")
    sp.set_defaults(func=commands.cmd_map)

    sp = sub.add_parser("index", parents=[common], help="pre-decompile the hot set")
    sp.add_argument("--topic", help="one topic from hot.json (default: all)")
    sp.add_argument("--build", action="append", help="build alias (repeatable)")
    sp.add_argument("--limit", type=int, help="max targets per topic")
    sp.add_argument("--refresh", action="store_true")
    sp.set_defaults(func=commands.cmd_index)

    sp = sub.add_parser("show", parents=[common], help="read indexed entries (no backend)")
    sp.add_argument("query", help="topic or name substring")
    sp.add_argument("--build")
    sp.add_argument("--limit", type=int, default=100)
    sp.add_argument("--symbolized", action="store_true", help="show the symbolized code")
    sp.add_argument("--max-bytes", type=int, default=12000)
    sp.set_defaults(func=commands.cmd_show)

    sp = sub.add_parser("symbolize", parents=[common], help="rewrite FUN_/DAT_ names in decompiled code")
    sp.add_argument("target")
    sp.add_argument("-b", "--build", default="s4")
    sp.add_argument("--addr-kind", choices=["va", "rva"], default=None)
    sp.add_argument("--max-bytes", type=int, default=16000)
    sp.add_argument("--no-header", action="store_true")
    sp.add_argument("--write", help="write the full symbolized code to this path")
    sp.add_argument("--refresh", action="store_true", help="ignore the decompile cache")
    sp.set_defaults(func=commands.cmd_symbolize)

    sp = sub.add_parser("asset_index", parents=[common], help="index extracted CPK trees")
    sp.add_argument("--root", help="extraction root (default STORM_RE_ASSETS or ~/storm-cpk-extracted)")
    sp.add_argument("--game", action="append", help="only these games (repeatable)")
    sp.set_defaults(func=commands.cmd_asset_index)

    sp = sub.add_parser("asset_find", parents=[common], help="search extracted CPK files")
    sp.add_argument("query", help="path substring, or glob with * ? [; empty = per-CPK overview")
    sp.add_argument("-g", "--game")
    sp.add_argument("--ext")
    sp.add_argument("--cpk", help="archive path substring, e.g. sim/data")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=commands.cmd_asset_find)

    sp = sub.add_parser("asset_info", parents=[common], help="inspect one extracted file")
    sp.add_argument("game")
    sp.add_argument("path", help="path under the game root, or entry path inside its CPK")
    sp.add_argument("--max-chunks", type=int, default=200)
    sp.set_defaults(func=commands.cmd_asset_info)

    return p


def _fail(args, code: int, message: str, extra: dict | None = None) -> int:
    if getattr(args, "json", False):
        payload = {"ok": False, "error": message, "code": code}
        if extra:
            payload.update(extra)
        print(json.dumps(payload, indent=2))
    else:
        print(f"storm-re: {message}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ResolveError as exc:
        extra = {}
        if hasattr(exc, "candidates"):
            extra["candidates"] = exc.candidates
        return _fail(args, getattr(exc, "exit_code", EXIT["resolve"]), str(exc), extra)
    except commands.DiffMissing as exc:
        return _fail(args, EXIT["diff"], str(exc))
    except MCPError as exc:
        return _fail(args, EXIT["backend"], str(exc))
    except DBError as exc:
        return _fail(args, EXIT["db"], str(exc))
    except KeyError as exc:
        return _fail(args, EXIT["usage"], f"unknown build {exc}")
    except ValueError as exc:
        return _fail(args, EXIT["usage"], str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
