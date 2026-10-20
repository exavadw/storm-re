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
class LiveSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")
        # Warm the seed cache so the dead-backend test is deterministic.
        proc = cli("state_surface", "ccPlayer", "-b", "s4", "--limit", "20")
        if proc.returncode != 0:
            raise unittest.SkipTest(f"surface warm-up failed: {proc.stderr[:300]}")

    def test_ccplayer_surface(self):
        proc, data = cli_json("state_surface", "ccPlayer", "-b", "s4", "--limit", "20")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(data["stats"]["seeds_analyzed"], 10)
        by_off = {f["offset"]: f for f in data["fields"]}
        for off in ("0xCC0", "0xCC4", "0xC8C"):
            self.assertIn(off, by_off)
        self.assertGreater(by_off["0xCC0"]["writes"], 0)
        self.assertGreater(by_off["0xCC4"]["writes"], 0)
        names = {f["name"] for f in by_off["0xCC0"]["functions"]}
        self.assertIn("ccPlayer::ChangeAction", names)

    def test_explicit_seed(self):
        proc, data = cli_json(
            "state_surface", "ccPlayer", "-b", "s4",
            "--seeds", "ccPlayer::ChangeAction",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["stats"]["seeds_analyzed"], 1)
        by_off = {f["offset"] for f in data["fields"]}
        self.assertIn("0xCC0", by_off)
        self.assertIn("0xCC4", by_off)

    def test_second_run_with_dead_backend(self):
        # The first test warms the cache for the same seed set.
        proc, data = cli_json(
            "state_surface", "ccPlayer", "-b", "s4", "--limit", "20",
            "--mcp", "http://127.0.0.1:9/mcp",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["stats"]["seeds_failed"], 0)
        self.assertGreaterEqual(data["stats"]["seeds_analyzed"], 10)

    def test_mcp_state_surface(self):
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
                {"name": "storm_state_surface",
                 "arguments": {"root": "ccPlayer", "limit": 5}},
            )
            result = resp["result"]
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(result["isError"])
            self.assertTrue(data["fields"])
            self.assertGreaterEqual(data["stats"]["seeds_analyzed"], 1)
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
