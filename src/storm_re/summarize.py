"""Deterministic, bounded summaries of decompile_function output."""

from __future__ import annotations

import json
from collections import Counter

from .text import truncate

MAX_CALLERS = 40
MAX_CALLEES = 60
MAX_STRINGS = 15

_NON_SYMBOLIC = ("FUN_", "thunk_FUN_", "SUB_", "LAB_", "UNK_")


def _symbolic(name: str) -> bool:
    return not name.startswith(_NON_SYMBOLIC)


def _signature(raw: dict) -> str:
    sig = (raw.get("signature") or "").strip()
    if sig:
        return sig
    code = raw.get("code") or ""
    for line in code.splitlines():
        line = line.strip()
        if line and not line.startswith(("//", "/*", "*")):
            return line.rstrip("{").strip()
    return ""


def summarize(
    raw: dict,
    detail: str = "summary",
    max_bytes: int = 8000,
    head: int = 0,
) -> dict:
    code = raw.get("code") or ""
    callees_all = [c for c in (raw.get("callees") or []) if isinstance(c, str)]
    xrefs = raw.get("xrefs") or []
    strings_raw = raw.get("referenced_strings") or []

    callers: list[str] = []
    seen: set[str] = set()
    data_refs: Counter[str] = Counter()
    for x in xrefs:
        if not isinstance(x, dict):
            continue
        xtype = str(x.get("type") or "").upper()
        fn = x.get("function_name")
        if "CALL" in xtype or xtype in ("UNCONDITIONAL_CALL", "CONDITIONAL_CALL"):
            if fn and fn not in seen:
                seen.add(fn)
                callers.append(fn)
        elif fn is None:
            data_refs[xtype or "OTHER"] += 1

    strings: list[dict] = []
    for s in strings_raw:
        if isinstance(s, dict):
            strings.append(
                {"value": s.get("value", ""), "address": s.get("address", "")}
            )
        elif isinstance(s, str):
            strings.append({"value": s, "address": ""})

    callees_symbolic = sorted({c for c in callees_all if _symbolic(c)})
    fun_count = sum(1 for c in callees_all if not _symbolic(c))

    raw_chars = len(code) + len(
        json.dumps(
            {"callees": callees_all, "xrefs": xrefs, "strings": strings_raw},
            separators=(",", ":"),
        )
    )

    summary: dict = {
        "name": raw.get("name"),
        "signature": _signature(raw),
        "caller_count": len(callers),
        "callers": callers[:MAX_CALLERS],
        "callee_count": len(callees_all),
        "fun_callee_count": fun_count,
        "callees": callees_symbolic[:MAX_CALLEES],
        "string_count": len(strings),
        "strings": strings[:MAX_STRINGS],
        "data_refs": dict(data_refs.most_common()),
        "code_lines": code.count("\n") + 1 if code else 0,
        "code_chars": len(code),
        "raw_chars": raw_chars,
    }

    text = _render(summary, code, detail, max_bytes, head)
    summary["summary_chars"] = len(text)
    summary["saved_pct"] = (
        round(100.0 * (1 - len(text) / raw_chars), 1) if raw_chars else 0.0
    )
    summary["text"] = text
    return summary


def _render(summary: dict, code: str, detail: str, max_bytes: int, head: int) -> str:
    out: list[str] = []
    if summary.get("name"):
        out.append(f"{summary['name']}")
    if summary.get("signature"):
        out.append(f"  {summary['signature']}")

    counts = (
        f"  callers={summary['caller_count']} callees={summary['callee_count']} "
        f"(FUN_ {summary['fun_callee_count']}) strings={summary['string_count']} "
        f"lines={summary['code_lines']}"
    )
    out.append(counts)

    if detail == "sig":
        return "\n".join(out)

    if summary["callers"]:
        out.append(f"callers ({summary['caller_count']}):")
        out.extend(f"  {c}" for c in summary["callers"])
        if summary["caller_count"] > len(summary["callers"]):
            out.append(f"  ... {summary['caller_count'] - len(summary['callers'])} more")

    if summary["callees"]:
        out.append(f"callees ({summary['callee_count']} total):")
        out.extend(f"  {c}" for c in summary["callees"])
        if len(summary["callees"]) < summary["callee_count"] - summary["fun_callee_count"]:
            out.append("  ... more")

    if summary["strings"]:
        out.append(f"strings ({summary['string_count']}):")
        for s in summary["strings"]:
            addr = f" @{s['address']}" if s["address"] else ""
            out.append(f"  {s['value']!r}{addr}")

    if summary["data_refs"]:
        refs = ", ".join(f"{k}={v}" for k, v in summary["data_refs"].items())
        out.append(f"data refs: {refs}")

    if detail in ("code", "full") or head > 0:
        lines = code.splitlines()
        if detail == "full":
            body = code
        elif detail == "code":
            body, _ = truncate(code, max_bytes)
        else:
            body = "\n".join(lines[:head])
        if body:
            out.append("code:")
            out.append(body)
    return "\n".join(out)
