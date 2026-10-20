"""Minimal MCP Streamable-HTTP client (stdlib only).

Enough of the protocol for pyghidra-mcp:
  initialize -> notifications/initialized -> tools/call
Handles both `text/event-stream` and plain JSON responses.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request

PROTOCOL = "2025-06-18"


class MCPError(RuntimeError):
    """Backend/protocol failure. Always fatal for the command."""


def _parse_events(body: str) -> list[dict]:
    body = body.strip()
    if not body:
        return []
    events: list[dict] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    if events:
        return events
    try:
        return [json.loads(body)]
    except json.JSONDecodeError as exc:
        raise MCPError(f"backend returned non-JSON body: {body[:300]!r}") from exc


def _unwrap(event: dict) -> dict:
    if "error" in event:
        err = event["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise MCPError(f"MCP error: {msg}")
    result = event.get("result")
    if result is None:
        return {}
    if not isinstance(result, dict):
        return {"value": result}

    if result.get("isError"):
        text = _content_text(result) or "tool returned isError"
        raise MCPError(f"tool error: {text}")

    # pyghidra-mcp returns the tool value twice: JSON in content[].text and a
    # FastMCP structuredContent wrapper. Prefer the text: it is the exact tool
    # return value, while structuredContent may be {"result": <value>}.
    text = _content_text(result)
    if text is not None:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        if parsed is not None:
            return {"value": parsed}
        structured = _structured(result)
        if structured is not None:
            return structured
        return {"text": text}

    structured = _structured(result)
    if structured is not None:
        return structured
    return result


def _structured(result: dict) -> dict | None:
    value = result.get("structuredContent")
    if not isinstance(value, dict) or not value:
        return None
    if set(value) == {"result"}:
        inner = value["result"]
        return inner if isinstance(inner, dict) else {"value": inner}
    return value


def _content_text(result: dict) -> str | None:
    content = result.get("content")
    if not isinstance(content, list):
        return None
    texts = [
        c.get("text", "")
        for c in content
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    if not texts:
        return None
    return "\n".join(texts)


class MCPClient:
    def __init__(self, url: str, timeout: float = 180.0, retries: int = 1):
        self.url = url
        self.timeout = timeout
        self.retries = max(0, retries)
        self._session: str | None = None
        self._next_id = 1
        self._initialized = False

    # -- transport ---------------------------------------------------------

    def _post(self, payload: dict, timeout: float | None = None) -> tuple[str, dict]:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "storm-re/0.1",
        }
        if self._session:
            headers["mcp-session-id"] = self._session
        req = urllib.request.Request(
            self.url, data=data, headers=headers, method="POST"
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout or self.timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", "replace")
            return body, dict(resp.headers)

    # -- protocol ----------------------------------------------------------

    def initialize(self) -> None:
        if self._initialized:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "storm-re", "version": "0.1"},
            },
        }
        self._next_id += 1
        body, headers = self._with_retry(payload)
        session = _header(headers, "mcp-session-id")
        if session:
            self._session = session
        # Drain the initialize result (errors are fatal).
        for event in _parse_events(body):
            if event.get("id") == 1:
                _unwrap(event)
                break
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            self._post(note, timeout=30)
        except (urllib.error.URLError, socket.timeout) as exc:
            raise MCPError(f"initialized notification failed: {exc}") from exc
        self._initialized = True

    def call_tool(self, name: str, arguments: dict, timeout: float | None = None) -> dict:
        self.initialize()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        req_id = self._next_id
        self._next_id += 1
        body, _ = self._with_retry(payload, timeout=timeout)

        last_error: Exception | None = None
        for event in _parse_events(body):
            if event.get("id") not in (req_id, None):
                continue
            try:
                return _unwrap(event)
            except MCPError as exc:
                last_error = exc
                break
        if last_error:
            raise last_error
        raise MCPError(f"no result for tools/call {name}")

    def _with_retry(self, payload: dict, timeout: float | None = None) -> tuple[str, dict]:
        attempts = self.retries + 1
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._post(payload, timeout=timeout)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                last = MCPError(f"HTTP {exc.code} from {self.url}: {detail or exc.reason}")
                if 400 <= exc.code < 500:
                    raise last from exc
            except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
                last = MCPError(f"cannot reach {self.url}: {exc}")
            except ssl.SSLError as exc:
                last = MCPError(f"TLS error talking to {self.url}: {exc}")
                raise last from exc
            if attempt + 1 < attempts:
                time.sleep(2)
        raise last or MCPError("backend call failed")


def _header(headers: dict, key: str) -> str | None:
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return None
