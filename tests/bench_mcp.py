"""Latency benchmark for the MCP stdio server. Run on the Ghidra host."""
import json, os, statistics, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ)
env["PYTHONPATH"] = str(ROOT / "src")
proc = subprocess.Popen(
    [sys.executable, "-m", "storm_re.mcp_server"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=env,
)

def rpc(i, method, params=None):
    msg = {"jsonrpc": "2.0", "id": i, "method": method}
    if params:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())

rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
proc.stdin.flush()

def bench(name, args, n=20):
    times = []
    for i in range(n):
        start = time.perf_counter()
        resp = rpc(100 + i, "tools/call", {"name": name, "arguments": args})
        times.append((time.perf_counter() - start) * 1000)
        if resp.get("result", {}).get("isError"):
            print(name, "error", resp)
            break
    times.sort()
    p50 = times[len(times) // 2]
    p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
    print(f"{name:<22} p50={p50:7.1f} ms  p95={p95:7.1f} ms  n={len(times)}")

bench("storm_resolve", {"target": "ccPlayer::ChangeAction"})
bench("storm_show", {"query": "input", "limit": 3})
bench("storm_explain", {"target": "ccPlayer::ChangeAction"})
proc.stdin.close()
proc.wait(timeout=10)
