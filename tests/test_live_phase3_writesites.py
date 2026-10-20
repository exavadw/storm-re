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
class LiveWriteSitesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")
        proc = cli("write_sites", "ccPlayer", "--offset", "0xCC0", "--limit", "20")
        if proc.returncode != 0:
            raise unittest.SkipTest(f"write_sites warm-up failed: {proc.stderr[:300]}")

    def test_offset_writer(self):
        proc, data = cli_json(
            "write_sites", "ccPlayer", "--offset", "0xCC0", "-b", "s4", "--limit", "20"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(data["stats"]["writes"], 1)
        names = {s["function"] for s in data["sites"] if s["kind"] == "write"}
        self.assertIn("ccPlayer::ChangeAction", names)

    def test_offset_reads(self):
        proc, data = cli_json(
            "write_sites", "ccPlayer", "--offset", "0xC8C", "-b", "s4",
            "--include-reads", "--limit", "20",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(data["stats"]["reads"], 1)
        names = {s["function"] for s in data["sites"] if s["kind"] == "read"}
        self.assertIn("ccPlayer::ChangeAction", names)

    def test_address_mode(self):
        proc, data = cli_json(
            "write_sites", "0x1416663c8", "-b", "s4",
            "--include-reads", "--limit", "50",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["mode"], "address")
        self.assertGreater(data["stats"]["xrefs_total"], 100)
        self.assertTrue(data["sites"])
        kinds = {s["kind"] for s in data["sites"]}
        self.assertIn("write", kinds)

    def test_dead_backend_offset(self):
        proc, data = cli_json(
            "write_sites", "ccPlayer", "--offset", "0xCC0", "--limit", "20",
            "--mcp", "http://127.0.0.1:9/mcp",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["stats"]["seeds_failed"], 0)

    def test_mcp_write_sites(self):
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
                {"name": "storm_write_sites",
                 "arguments": {"target": "ccPlayer", "offset": "0xCC0", "limit": 5}},
            )
            result = resp["result"]
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(result["isError"])
            self.assertTrue(data["sites"])
            self.assertGreaterEqual(data["stats"]["writes"], 1)
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
