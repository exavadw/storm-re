import json
import os
import subprocess
import sys
import unittest

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
class LiveFrameTickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")
        proc = cli("frame_tick", "-b", "s4", "--limit", "20")
        if proc.returncode != 0:
            raise unittest.SkipTest(f"frame_tick warm-up failed: {proc.stderr[:300]}")

    def test_changeaction_idiom(self):
        proc, data = cli_json("frame_tick", "-b", "s4", "--limit", "20")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(data["stats"]["idioms"], 1)
        by_name = {f["name"]: f for f in data["functions"]}
        self.assertIn("ccPlayer::ChangeAction", by_name)
        kinds = {i["kind"] for i in by_name["ccPlayer::ChangeAction"]["idioms"]}
        self.assertIn("state-timer-neg", kinds)

    def test_notes(self):
        proc, data = cli_json("frame_tick", "-b", "s4", "--limit", "10")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(any("30 FPS" in n for n in data["notes"]))

    def test_mcp_frame_tick(self):
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
            resp = rpc(2, "tools/call", {"name": "storm_frame_tick", "arguments": {"limit": 10}})
            result = resp["result"]
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(result["isError"])
            self.assertGreaterEqual(data["stats"]["idioms"], 1)
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
