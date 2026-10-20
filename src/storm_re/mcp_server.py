"""storm-re MCP server.

Stdio by default, optional Streamable-HTTP JSON endpoint. Every tool call runs
the `storm-re` CLI with `--json`; resources and prompts are native MCP.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import __version__

PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_CHARS = 48 * 1024
ROOT = Path(__file__).resolve().parents[2]
WRITE_LOCK = threading.Lock()

INSTRUCTIONS = """Storm RE server. Use resolve first, then show/symbolize, then
state_surface/write_sites, then decomp/diff. Use full names
(ccPlayer::ChangeAction). Static results are inferred; confirm runtime facts with
a replay trace/snap. resolve/show/stat/builds work with Ghidra down; decomp and
xrefs are cache-first. Use storm_explain for one function and storm_batch for
several read-only calls. storm_asset_find/storm_asset_info search the decrypted
CPK files of every game (xfbin chunk lists included). No write/rename tools."""


def _tool(
    name: str,
    title: str,
    description: str,
    properties: dict | None = None,
    required: tuple[str, ...] = (),
    read_only: bool = True,
) -> dict:
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": list(required),
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "additionalProperties": True,
        },
        "annotations": {
            "readOnlyHint": read_only,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


TOOLS = [
    _tool(
        "storm_resolve", "Storm Resolve",
        "Resolve a VA, RVA or full symbol name in one build. Cheap and local; "
        "returns build/program/sha/rva/va/name/confidence/source.",
        {"target": {"type": "string"}, "build": {"type": "string"},
         "addr_kind": {"type": "string", "enum": ["va", "rva"]}},
        ("target",),
    ),
    _tool(
        "storm_decomp", "Storm Decompile",
        "Bounded decompile summary, cache-first. detail=summary default; sig is "
        "cheapest; full can be large.",
        {"target": {"type": "string"}, "build": {"type": "string"},
         "detail": {"type": "string", "enum": ["sig", "summary", "code", "full"]},
         "max_bytes": {"type": "integer"}, "head": {"type": "integer"},
         "refresh": {"type": "boolean"}},
        ("target",),
    ),
    _tool(
        "storm_xrefs", "Storm Xrefs",
        "Deduplicated callers, callees and data refs for one function.",
        {"target": {"type": "string"}, "build": {"type": "string"},
         "direction": {"type": "string", "enum": ["to", "from", "both"]},
         "limit": {"type": "integer"}},
        ("target",),
    ),
    _tool(
        "storm_diff", "Storm Diff",
        "Compare one function across two builds: signature, similarity, callee delta.",
        {"target": {"type": "string"}, "from_build": {"type": "string"},
         "to_build": {"type": "string"}, "use_map": {"type": "boolean"}},
        ("target", "from_build", "to_build"),
    ),
    _tool(
        "storm_map", "Storm Map",
        "Map a symbol across builds via direct BSim, Trilogy-mediated, name and RVA.",
        {"name": {"type": "string"}, "from_build": {"type": "string"},
         "to_build": {"type": "string"}, "refresh": {"type": "boolean"}},
        ("name",),
    ),
    _tool(
        "storm_find", "Storm Find",
        "Search symbols (local, cheap), strings, or code.",
        {"query": {"type": "string"}, "build": {"type": "string"},
         "mode": {"type": "string", "enum": ["symbol", "string", "code"]},
         "limit": {"type": "integer"}},
        ("query",),
    ),
    _tool(
        "storm_symbolize", "Storm Symbolize",
        "Rewrite FUN_/SUB_/DAT_ placeholders to Storm names with mapping and confidence.",
        {"target": {"type": "string"}, "build": {"type": "string"},
         "addr_kind": {"type": "string", "enum": ["va", "rva"]},
         "max_bytes": {"type": "integer"}},
        ("target",),
    ),
    _tool(
        "storm_show", "Storm Show",
        "Read pre-decompiled hot-set entries from SQLite; no Ghidra call.",
        {"query": {"type": "string"}, "build": {"type": "string"},
         "limit": {"type": "integer"}, "symbolized": {"type": "boolean"},
         "max_bytes": {"type": "integer"}},
        ("query",),
    ),
    _tool(
        "storm_state_surface", "Storm State Surface",
        "Static field-access surface for a root object: offsets, sizes, r/w, "
        "functions, confidence. Static inference only.",
        {"root": {"type": "string"}, "build": {"type": "string"},
         "limit": {"type": "integer"}, "max_offset": {"type": "integer"},
         "param": {"type": "string"}, "seeds": {"type": "string"},
         "min_writes": {"type": "integer"}},
        ("root",),
    ),
    _tool(
        "storm_write_sites", "Storm Write Sites",
        "Who writes an address or root+offset, with evidence and confidence.",
        {"target": {"type": "string"},
         "offset": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
         "root": {"type": "string"}, "build": {"type": "string"},
         "include_reads": {"type": "boolean"}, "include_calls": {"type": "boolean"},
         "limit": {"type": "integer"}, "param": {"type": "string"},
         "seeds": {"type": "string"}},
        ("target",),
    ),
    _tool(
        "storm_input_path", "Storm Input Path",
        "Pad poll -> ccPlayerPad -> CtrlInputPad -> vfunc gates -> ChangeAction.",
        {"build": {"type": "string"}, "depth": {"type": "integer"},
         "limit": {"type": "integer"}},
    ),
    _tool(
        "storm_frame_tick", "Storm Frame Tick",
        "Timer idioms and per-frame constants; flags 60 FPS risks.",
        {"build": {"type": "string"}, "limit": {"type": "integer"},
         "seeds": {"type": "string"}},
    ),
    _tool(
        "storm_net_session", "Storm Net Session",
        "Steam/net-session send/recv/tick surface and Steam imports.",
        {"build": {"type": "string"}, "limit": {"type": "integer"},
         "seeds": {"type": "string"}, "include_imports": {"type": "boolean"}},
    ),
    _tool(
        "storm_scene_dispatch", "Storm Scene Dispatch",
        "Story scene/message dispatch, stage strings and boss ids.",
        {"build": {"type": "string"}, "limit": {"type": "integer"},
         "seeds": {"type": "string"}},
    ),
    _tool(
        "storm_patch_diff", "Storm Patch Diff",
        "Batch function diff between builds; byte mode finds call-site patches.",
        {"from_build": {"type": "string"}, "to_build": {"type": "string"},
         "limit": {"type": "integer"}, "seeds": {"type": "string"},
         "include_same": {"type": "boolean"}, "no_byte_diff": {"type": "boolean"}},
        ("from_build", "to_build"),
    ),
    _tool(
        "storm_export", "Storm Export",
        "Write a compact markdown report from indexed facts.",
        {"topic": {"type": "string"}, "build": {"type": "string"},
         "out": {"type": "string"}, "limit": {"type": "integer"},
         "include_code": {"type": "boolean"}},
        ("topic",), read_only=False,
    ),
    _tool(
        "storm_explain", "Storm Explain",
        "One-call explanation: resolve + decompile + symbolize + xrefs + maps.",
        {"target": {"type": "string"}, "build": {"type": "string"},
         "max_bytes": {"type": "integer"}},
        ("target",),
    ),
    _tool(
        "storm_batch", "Storm Batch",
        "Run several read-only storm-re tools in one call. Excludes export and batch.",
        {"calls": {"type": "array", "items": {"type": "object"}},
         "stop_on_error": {"type": "boolean"}},
        ("calls",),
    ),
    _tool(
        "storm_asset_find", "Storm Asset Find",
        "Search decrypted CPK files of storm1/2/3hd/3fb/rev/4/gen by path substring "
        "or glob. Returns game, cpk, entry, size, magic, path, win_path. "
        "Empty query = per-game/per-CPK overview.",
        {"query": {"type": "string"}, "game": {"type": "string"},
         "ext": {"type": "string"}, "cpk": {"type": "string"},
         "limit": {"type": "integer"}},
    ),
    _tool(
        "storm_asset_info", "Storm Asset Info",
        "One extracted CPK file: paths, same entry in other games, and the xfbin "
        "chunk list (type, name, path) for NUCC files.",
        {"game": {"type": "string"}, "path": {"type": "string"},
         "max_chunks": {"type": "integer"}},
        ("game", "path"),
    ),
    _tool(
        "storm_builds", "Storm Builds",
        "List build aliases, programs, SHA-256, base and counts.",
    ),
    _tool(
        "storm_stat", "Storm Stat",
        "Database, cache, BSim, map and index statistics.",
    ),
]

TOOL_NAMES = {t["name"] for t in TOOLS}
BATCH_TOOLS = TOOL_NAMES - {"storm_batch", "storm_export"}
PROMPTS = [
    {
        "name": "rollback_audit",
        "description": "Audit a rollback surface for a root object.",
        "arguments": [{"name": "root", "required": False}],
    },
    {
        "name": "story_port",
        "description": "Trace a story scene/boss dispatch path.",
        "arguments": [{"name": "scene", "required": False}],
    },
    {
        "name": "clean_vs_mod",
        "description": "Diff a clean exe against a modded build.",
        "arguments": [{"name": "from_build", "required": False},
                      {"name": "to_build", "required": False}],
    },
    {
        "name": "function_explain",
        "description": "Explain one function with names, xrefs and maps.",
        "arguments": [{"name": "target", "required": False}],
    },
]


class ToolError(ValueError):
    pass


def _req(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"missing required string argument {key!r}")
    return value


def build_argv(name: str, args: dict, db: str | None, backend: str | None) -> list[str]:
    if name not in TOOL_NAMES:
        raise KeyError(name)

    if name == "storm_resolve":
        argv = ["resolve", _req(args, "target"), "-b", args.get("build", "s4")]
        if args.get("addr_kind"):
            argv += ["--addr-kind", str(args["addr_kind"])]
    elif name == "storm_decomp":
        argv = ["decomp", _req(args, "target"), "-b", args.get("build", "s4"),
                "--detail", args.get("detail", "summary"),
                "--max-bytes", str(int(args.get("max_bytes", 8000))),
                "--head", str(int(args.get("head", 0)))]
        if args.get("refresh"):
            argv.append("--refresh")
    elif name == "storm_xrefs":
        argv = ["xrefs", _req(args, "target"), "-b", args.get("build", "s4"),
                "--direction", args.get("direction", "to"),
                "--limit", str(int(args.get("limit", 100)))]
    elif name == "storm_diff":
        argv = ["diff", _req(args, "target"), "--from", _req(args, "from_build"),
                "--to", _req(args, "to_build")]
        if args.get("use_map"):
            argv.append("--map")
    elif name == "storm_map":
        argv = ["map", _req(args, "name"), "--from", args.get("from_build", "s4")]
        if args.get("to_build"):
            argv += ["--to", str(args["to_build"])]
        if args.get("refresh"):
            argv.append("--refresh")
    elif name == "storm_find":
        argv = ["find", _req(args, "query"), "-b", args.get("build", "s4"),
                "--mode", args.get("mode", "symbol"), "--limit", str(int(args.get("limit", 25)))]
    elif name == "storm_symbolize":
        argv = ["symbolize", _req(args, "target"), "-b", args.get("build", "s4"),
                "--max-bytes", str(int(args.get("max_bytes", 16000)))]
        if args.get("addr_kind"):
            argv += ["--addr-kind", str(args["addr_kind"])]
    elif name == "storm_show":
        argv = ["show", _req(args, "query"), "--limit", str(int(args.get("limit", 100)))]
        if args.get("build"):
            argv += ["--build", str(args["build"])]
        if args.get("symbolized"):
            argv.append("--symbolized")
        if args.get("max_bytes") is not None:
            argv += ["--max-bytes", str(int(args["max_bytes"]))]
    elif name == "storm_state_surface":
        argv = ["state_surface", _req(args, "root"), "-b", args.get("build", "s4"),
                "--limit", str(int(args.get("limit", 40))),
                "--max-offset", str(int(args.get("max_offset", 0x40000))),
                "--param", args.get("param", "param_1"),
                "--min-writes", str(int(args.get("min_writes", 0)))]
        if args.get("seeds"):
            argv += ["--seeds", str(args["seeds"])]
    elif name == "storm_write_sites":
        argv = ["write_sites", _req(args, "target"), "-b", args.get("build", "s4")]
        if args.get("offset") is not None:
            off = args["offset"]
            off = int(off, 0) if isinstance(off, str) else int(off)
            argv += ["--offset", str(off)]
        if args.get("root"):
            argv += ["--root", str(args["root"])]
        if args.get("seeds"):
            argv += ["--seeds", str(args["seeds"])]
        argv += ["--param", args.get("param", "param_1"), "--limit", str(int(args.get("limit", 100)))]
        if args.get("include_reads"):
            argv.append("--include-reads")
        if args.get("include_calls"):
            argv.append("--include-calls")
    elif name == "storm_input_path":
        argv = ["input_path", "-b", args.get("build", "s4"),
                "--depth", str(int(args.get("depth", 1))),
                "--limit", str(int(args.get("limit", 80)))]
    elif name == "storm_frame_tick":
        argv = ["frame_tick", "-b", args.get("build", "s4"), "--limit", str(int(args.get("limit", 30)))]
        if args.get("seeds"):
            argv += ["--seeds", str(args["seeds"])]
    elif name == "storm_net_session":
        argv = ["net_session", "-b", args.get("build", "s4"), "--limit", str(int(args.get("limit", 25)))]
        if args.get("seeds"):
            argv += ["--seeds", str(args["seeds"])]
        if args.get("include_imports") is False:
            argv.append("--no-imports")
    elif name == "storm_scene_dispatch":
        argv = ["scene_dispatch", "-b", args.get("build", "s4"), "--limit", str(int(args.get("limit", 20)))]
        if args.get("seeds"):
            argv += ["--seeds", str(args["seeds"])]
    elif name == "storm_patch_diff":
        argv = ["patch_diff", "--from", _req(args, "from_build"),
                "--to", _req(args, "to_build"), "--limit", str(int(args.get("limit", 20)))]
        if args.get("seeds"):
            argv += ["--seeds", str(args["seeds"])]
        if args.get("include_same"):
            argv.append("--include-same")
        if args.get("no_byte_diff"):
            argv.append("--no-byte-diff")
    elif name == "storm_export":
        argv = ["export", _req(args, "topic"), "--limit", str(int(args.get("limit", 50)))]
        if args.get("build"):
            argv += ["--build", str(args["build"])]
        if args.get("out"):
            argv += ["--out", str(args["out"])]
        if args.get("include_code"):
            argv.append("--code")
    elif name == "storm_explain":
        argv = ["explain", _req(args, "target"), "-b", args.get("build", "s4"),
                "--max-bytes", str(int(args.get("max_bytes", 8000)))]
    elif name == "storm_asset_find":
        argv = ["asset_find", args.get("query", ""), "--limit", str(int(args.get("limit", 50)))]
        for key in ("game", "ext", "cpk"):
            if args.get(key):
                argv += [f"--{key}", str(args[key])]
    elif name == "storm_asset_info":
        argv = ["asset_info", _req(args, "game"), _req(args, "path"),
                "--max-chunks", str(int(args.get("max_chunks", 200)))]
    elif name == "storm_builds":
        argv = ["builds"]
    else:  # storm_stat
        argv = ["stat"]

    if db:
        argv += ["--db", db]
    if backend:
        argv += ["--mcp", backend]
    return argv


def _env() -> dict:
    env = dict(os.environ)
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def call_cli(
    argv: list[str],
    timeout: float = 600.0,
    progress=None,
    cancel_event: threading.Event | None = None,
) -> dict:
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "storm_re", *argv, "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_env(),
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc), "code": 3}

    start = time.monotonic()
    if progress:
        progress(0.0)
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=2)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - start
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return {"ok": False, "error": "cancelled", "code": -32800}
                if elapsed > timeout:
                    proc.kill()
                    return {"ok": False, "error": f"timed out after {timeout:.0f}s", "code": 3}
                if progress:
                    progress(round(elapsed, 1))
    finally:
        if proc.poll() is None:
            proc.kill()

    text = (out or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        detail = (err or text or "no output").strip()
        return {"ok": False, "error": detail[:2000], "code": 3}
    if proc.returncode != 0 and data.get("ok") is not False:
        data = {"ok": False, "error": (err or text or "storm-re failed").strip()[:2000],
                "code": proc.returncode}
    return data


def cap_response(data: dict) -> dict:
    text = json.dumps(data, separators=(",", ":"))
    if len(text) <= MAX_CHARS:
        return data
    data = dict(data)
    if isinstance(data.get("text"), str):
        data["text"] = data["text"][: MAX_CHARS // 2] + "\n... [truncated]"
        data["truncated"] = True
        if len(json.dumps(data, separators=(",", ":"))) <= MAX_CHARS:
            return data
    return {"ok": bool(data.get("ok")), "truncated": True,
            "error": "response exceeded 48 KB; use detail=sig, a smaller limit, or max_bytes",
            "code": 3}


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_response(data: dict) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(data, separators=(",", ":"))}],
        "structuredContent": data,
        "isError": not bool(data.get("ok")),
    }


def run_tool(
    name: str,
    args: dict,
    db: str | None,
    backend: str | None,
    progress=None,
    cancel_event=None,
) -> dict:
    if name == "storm_batch":
        return run_batch(args, db, backend, progress=progress, cancel_event=cancel_event)
    argv = build_argv(name, args, db, backend)
    return cap_response(call_cli(argv, progress=progress, cancel_event=cancel_event))


def run_batch(args: dict, db, backend, progress=None, cancel_event=None) -> dict:
    calls = args.get("calls")
    if not isinstance(calls, list) or not calls:
        return {"ok": False, "error": "calls must be a non-empty array", "code": 1}
    if len(calls) > 10:
        return {"ok": False, "error": "at most 10 calls per batch", "code": 1}
    stop = bool(args.get("stop_on_error"))
    results = []
    for i, call in enumerate(calls):
        if progress:
            progress(float(i))
        tool = call.get("tool") if isinstance(call, dict) else None
        arguments = call.get("arguments") or {}
        if tool not in BATCH_TOOLS:
            item = {"ok": False, "error": f"tool {tool!r} not allowed in batch", "code": 1}
        else:
            try:
                item = run_tool(tool, arguments, db, backend, cancel_event=cancel_event)
            except (ToolError, KeyError, ValueError) as exc:
                item = {"ok": False, "error": str(exc), "code": 1}
        results.append({"tool": tool, "result": item})
        if stop and not item.get("ok"):
            break
    return {"ok": all(r["result"].get("ok") for r in results), "results": results}


def _resource_text(uri: str, db, backend) -> tuple[str, str]:
    if uri == "storm-re://builds":
        data = run_tool("storm_builds", {}, db, backend)
        return json.dumps(data, indent=2), "application/json"
    if uri == "storm-re://stats":
        data = run_tool("storm_stat", {}, db, backend)
        return json.dumps(data, indent=2), "application/json"
    if uri == "storm-re://assets":
        data = call_cli(["asset_find", "", "--json"] + _common(db, backend))
        if not data.get("ok"):
            raise ToolError(str(data.get("error")))
        return json.dumps(data, indent=2), "application/json"
    if uri.startswith("storm-re://topic/"):
        topic = unquote(uri[len("storm-re://topic/"):])
        argv = ["export", topic, "--out", "-", "--json"] + _common(db, backend)
        data = call_cli(argv)
        if not data.get("ok"):
            raise ToolError(str(data.get("error")))
        return data.get("markdown", ""), "text/markdown"
    if uri.startswith("storm-re://function/"):
        rest = uri[len("storm-re://function/"):]
        parts = rest.split("/", 1)
        if len(parts) != 2:
            raise ToolError("function URI must be storm-re://function/<build>/<rva>")
        build, rva = unquote(parts[0]), unquote(parts[1])
        argv = ["symbolize", rva, "-b", build, "--json"] + _common(db, backend)
        data = call_cli(argv)
        if not data.get("ok"):
            raise ToolError(str(data.get("error")))
        return json.dumps(data, indent=2), "application/json"
    raise ToolError(f"unknown resource {uri!r}")


def _common(db, backend) -> list[str]:
    out = []
    if db:
        out += ["--db", db]
    if backend:
        out += ["--mcp", backend]
    return out


def _prompt_text(name: str, args: dict) -> str:
    if name == "rollback_audit":
        root = args.get("root", "ccPlayer")
        return (
            f"Audit the rollback surface for `{root}`. Use storm_state_surface "
            f"(root={root}, limit=20), then storm_write_sites for the writable "
            "offsets you care about (0xCC0, 0xCC4, 0xC8C, 0x218). Mark static "
            "results inferred and list what a replay trace must confirm."
        )
    if name == "story_port":
        scene = args.get("scene", "boss")
        return (
            f"Trace story dispatch for `{scene}`. Use storm_scene_dispatch, "
            "storm_resolve on the message lookup and Movie::Invoke, and "
            "storm_symbolize before quoting code. Report scene ids 0x5300/0x5301 "
            "as runtime ids, not exe addresses."
        )
    if name == "clean_vs_mod":
        a = args.get("from_build", "s1-clean")
        b = args.get("to_build", "s1")
        return (
            f"Diff `{a}` against `{b}` with storm_patch_diff (byte mode). "
            "Summarize changed functions, show one call-site patch, and note "
            "that s1-clean names are inherited by RVA."
        )
    return (
        f"Explain `{args.get('target', 'ccPlayer::ChangeAction')}` with "
        "storm_explain, then state_surface/write_sites if it touches state. "
        "Use full names and mark static conclusions inferred."
    )


def handle_request(req: dict, db: str | None = None, backend: str | None = None) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")
    is_notification = "id" not in req

    if method == "initialize":
        params = req.get("params") or {}
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else PROTOCOL
        result = {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": {"name": "storm-re", "version": __version__},
            "instructions": INSTRUCTIONS,
        }
        return None if is_notification else _result(req_id, result)

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return None if is_notification else _result(req_id, {})

    if method == "tools/list":
        return None if is_notification else _result(req_id, {"tools": TOOLS})

    if method == "resources/list":
        resources = [
            {"uri": "storm-re://builds", "name": "Builds", "mimeType": "application/json",
             "description": "Build aliases, programs, SHA-256 and counts"},
            {"uri": "storm-re://stats", "name": "Stats", "mimeType": "application/json",
             "description": "Cache, BSim, map and index statistics"},
            {"uri": "storm-re://assets", "name": "Assets", "mimeType": "application/json",
             "description": "Extracted CPK files per game and archive"},
        ]
        return None if is_notification else _result(req_id, {"resources": resources})

    if method == "resources/templates/list":
        templates = [
            {"uriTemplate": "storm-re://topic/{topic}", "name": "Topic report",
             "mimeType": "text/markdown", "description": "Indexed topic report"},
            {"uriTemplate": "storm-re://function/{build}/{rva}", "name": "Function",
             "mimeType": "application/json", "description": "Symbolized function JSON"},
        ]
        return None if is_notification else _result(req_id, {"resourceTemplates": templates})

    if method == "resources/read":
        uri = (req.get("params") or {}).get("uri")
        try:
            text, mime = _resource_text(str(uri), db, backend)
            result = {"contents": [{"uri": uri, "mimeType": mime, "text": text}]}
            return None if is_notification else _result(req_id, result)
        except (ToolError, KeyError, ValueError) as exc:
            return None if is_notification else _error(req_id, -32602, str(exc))

    if method == "prompts/list":
        return None if is_notification else _result(req_id, {"prompts": PROMPTS})

    if method == "prompts/get":
        params = req.get("params") or {}
        name = params.get("name")
        if name not in {p["name"] for p in PROMPTS}:
            return None if is_notification else _error(req_id, -32602, f"unknown prompt {name!r}")
        text = _prompt_text(name, params.get("arguments") or {})
        result = {
            "description": next(p["description"] for p in PROMPTS if p["name"] == name),
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }
        return None if is_notification else _result(req_id, result)

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in TOOL_NAMES:
            return None if is_notification else _error(req_id, -32601, f"unknown tool {name!r}")
        try:
            data = run_tool(name, args, db, backend)
        except ToolError as exc:
            return None if is_notification else _error(req_id, -32602, str(exc))
        except (KeyError, ValueError) as exc:
            return None if is_notification else _error(req_id, -32602, str(exc))
        return None if is_notification else _result(req_id, _tool_response(data))

    return None if is_notification else _error(req_id, -32601, f"unknown method {method!r}")


def _send(message: dict) -> None:
    with WRITE_LOCK:
        print(json.dumps(message, separators=(",", ":")), flush=True)


def _stdio_call(req: dict, db, backend) -> None:
    req_id = req.get("id")
    params = req.get("params") or {}
    token = (params.get("_meta") or {}).get("progressToken")
    cancel_event = threading.Event()

    def progress(value: float) -> None:
        if token is not None:
            _send({"jsonrpc": "2.0", "method": "notifications/progress",
                   "params": {"progressToken": token, "progress": value}})

    try:
        data = run_tool(params.get("name"), params.get("arguments") or {}, db, backend,
                        progress=progress, cancel_event=cancel_event)
        _send(_result(req_id, _tool_response(data)))
    except ToolError as exc:
        _send(_error(req_id, -32602, str(exc)))
    except (KeyError, ValueError) as exc:
        _send(_error(req_id, -32602, str(exc)))
    except Exception as exc:  # keep the server alive
        print(f"storm-re-mcp: {exc!r}", file=sys.stderr, flush=True)
        _send(_error(req_id, -32603, f"internal error: {exc}"))


def _stdio_loop(db, backend, timeout: float) -> int:
    active: dict = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _send(_error(None, -32700, "parse error"))
            continue
        method = req.get("method")
        if method == "notifications/cancelled":
            rid = (req.get("params") or {}).get("requestId")
            entry = active.get(rid)
            if entry:
                entry.set()
            continue
        if method == "tools/call" and "id" in req:
            rid = req["id"]
            active[rid] = threading.Event()

            def worker(req=req, rid=rid, cancel=active[rid]):
                try:
                    _stdio_call(req, db, backend)
                finally:
                    active.pop(rid, None)

            threading.Thread(target=worker, daemon=True).start()
            continue
        response = handle_request(req, db, backend)
        if response is not None:
            _send(response)
    return 0


class _HTTPHandler(BaseHTTPRequestHandler):
    server_version = f"storm-re/{__version__}"

    def log_message(self, fmt, *args):
        print(f"storm-re-mcp http: {fmt % args}", file=sys.stderr, flush=True)

    def _auth(self) -> bool:
        token = getattr(self.server, "token", None)
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {token}"

    def _json(self, code: int, payload: dict, session: str | None = None) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session:
            self.send_header("mcp-session-id", session)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "server": "storm-re"})
        else:
            self.send_response(405)
            self.send_header("Allow", "POST")
            self.end_headers()

    def do_POST(self):
        if self.path not in ("/mcp", "/"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        if not self._auth():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "bad request"})
            return
        response = handle_request(req, getattr(self.server, "db", None), getattr(self.server, "backend", None))
        if response is None:
            self.send_response(202)
            self.end_headers()
            return
        session = str(uuid.uuid4()) if req.get("method") == "initialize" else None
        self._json(200, response, session=session)


def create_http_server(host: str, port: int, db: str | None, backend: str | None,
                       token: str | None = None) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise ValueError("refusing non-loopback bind without --token")
    server = ThreadingHTTPServer((host, port), _HTTPHandler)
    server.db = db
    server.backend = backend
    server.token = token
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="storm-re-mcp", description="storm-re MCP server")
    parser.add_argument("--db", help="SQLite database path")
    parser.add_argument("--backend", "--mcp", dest="backend", help="pyghidra-mcp URL")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--http", help="HOST:PORT for Streamable-HTTP JSON (default stdio)")
    parser.add_argument("--token", default=os.environ.get("STORM_RE_MCP_TOKEN"),
                        help="Bearer token for HTTP")
    args = parser.parse_args(argv)

    if args.http:
        host, _, port = args.http.rpartition(":")
        try:
            server = create_http_server(host or "127.0.0.1", int(port), args.db,
                                        args.backend, args.token)
        except (ValueError, OSError) as exc:
            print(f"storm-re-mcp: {exc}", file=sys.stderr)
            return 1
        print(f"storm-re-mcp {__version__} HTTP on {host}:{port}", file=sys.stderr, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    print(f"storm-re-mcp {__version__} ready (db={args.db or 'default'})",
          file=sys.stderr, flush=True)
    return _stdio_loop(args.db, args.backend, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
