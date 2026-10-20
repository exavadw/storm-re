import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT

from storm_re import config

LIVE = os.environ.get("STORM_RE_LIVE") == "1"


def cli(*argv, timeout=1200):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "storm_re", *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def cli_json(*argv, timeout=1200):
    proc = cli(*argv, "--json", timeout=timeout)
    try:
        return proc, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc, None


@unittest.skipUnless(LIVE, "set STORM_RE_LIVE=1 to run live tests")
class LiveExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")

    def test_export_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "input.md"
            proc, data = cli_json(
                "export", "input", "--out", str(out), "--limit", "5",
                "--mcp", "http://127.0.0.1:9/mcp",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out.exists())
            text = out.read_text()
            self.assertIn("# storm-re: input", text)
            self.assertIn("ccPlayer::ChangeAction", text)
            self.assertGreater(data["bytes"], 0)

    def test_mcp_export(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "storm_re.mcp_server",
                "--db", str(config.db_path()),
                "--backend", "http://127.0.0.1:9/mcp",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            def rpc(i, method, params=None):
                msg = {"jsonrpc": "2.0", "id": i, "method": method}
                if params:
                    msg["params"] = params
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "input.md"
                rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
                proc.stdin.flush()
                resp = rpc(
                    2, "tools/call",
                    {"name": "storm_export",
                     "arguments": {"topic": "input", "out": str(out), "limit": 3}},
                )
                result = resp["result"]
                data = json.loads(result["content"][0]["text"])
                self.assertFalse(result["isError"])
                self.assertTrue(out.exists())
                self.assertIn("storm-re: input", out.read_text())
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            proc.stdout.close()
            proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
