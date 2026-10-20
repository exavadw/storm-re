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


def cli(*argv, timeout=900):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "storm_re", *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def cli_json(*argv, timeout=900):
    proc = cli(*argv, "--json", timeout=timeout)
    try:
        return proc, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc, None


@unittest.skipUnless(LIVE, "set STORM_RE_LIVE=1 to run live tests")
class LiveSymbolizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")
        # Populate symbolized text for the input topic.
        proc = cli("index", "--topic", "input", "--build", "s4", "--refresh")
        if proc.returncode != 0:
            raise unittest.SkipTest(f"index failed: {proc.stderr[:400]}")

    def test_symbolize_cache_hit(self):
        proc, data = cli_json(
            "symbolize", "ccPlayer::ChangeAction", "-b", "s4",
            "--mcp", "http://127.0.0.1:9/mcp",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(data["renamed"], 1)
        self.assertIn("void ccPlayer::ChangeAction", data["code"])
        self.assertIn("ccPlayer::ClearAtkHitResult", data["code"])
        self.assertNotIn("void FUN_1407ab468", data["code"])

    def test_symbolize_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "changeaction.c"
            proc = cli(
                "symbolize", "ccPlayer::ChangeAction", "-b", "s4",
                "--write", str(out), "--no-header",
                "--mcp", "http://127.0.0.1:9/mcp",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out.exists())
            self.assertIn("ccPlayer::ChangeAction", out.read_text())

    def test_show_symbolized_is_local(self):
        proc, data = cli_json(
            "show", "input", "--build", "s4", "--symbolized",
            "--mcp", "http://127.0.0.1:9/mcp",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(data["entries"])
        self.assertTrue(any(e["symbolized"] for e in data["entries"]))
        self.assertTrue(any("::" in e["text"] for e in data["entries"]))

    def test_mcp_symbolize(self):
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

            rpc(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            proc.stdin.flush()
            resp = rpc(
                2, "tools/call",
                {"name": "storm_symbolize", "arguments": {"target": "ccPlayer::ChangeAction"}},
            )
            result = resp["result"]
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(result["isError"])
            self.assertIn("ccPlayer::ClearAtkHitResult", data["code"])
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
