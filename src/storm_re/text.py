"""Address and name helpers. No third-party imports."""

from __future__ import annotations

import re

_HEX = re.compile(r"^(?:0[xX])?[0-9a-fA-F]+$")
_FUN = re.compile(r"^(?:thunk_)?FUN_([0-9a-fA-F]+)$", re.IGNORECASE)


def is_hex(text: str) -> bool:
    return bool(_HEX.match(text.strip()))


def parse_addr(text: str) -> int:
    """Parse 0x-prefixed or bare hex. Bare values are hex (Storm addresses)."""
    t = text.strip()
    if not _HEX.match(t):
        raise ValueError(f"not an address: {text!r}")
    if t.lower().startswith("0x"):
        t = t[2:]
    return int(t, 16)


def fmt_addr(value: int) -> str:
    return f"0x{value:X}"


def fun_addr(name: str) -> int | None:
    """FUN_1407ab468 / thunk_FUN_1407ab468 -> integer address."""
    m = _FUN.match(name.strip())
    return int(m.group(1), 16) if m else None


def split_name(name: str) -> tuple[str, str]:
    """'ns3::ccPlayer::ChangeAction' -> ('ns3::ccPlayer', 'ChangeAction')."""
    if "::" in name:
        ns, _, short = name.rpartition("::")
        return ns, short
    if "." in name:
        ns, _, short = name.rpartition(".")
        return ns, short
    return "", name


def norm(text: str) -> str:
    return text.strip().casefold()


def truncate(text: str, max_bytes: int) -> tuple[str, bool]:
    """Byte-bounded truncation that does not split a UTF-8 sequence."""
    raw = text.encode("utf-8", "replace")
    if max_bytes <= 0 or len(raw) <= max_bytes:
        return text, False
    cut = raw[:max_bytes].decode("utf-8", "ignore")
    return cut + "\n... [truncated]\n", True


def one_line(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."
