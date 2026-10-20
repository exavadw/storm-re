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
class LiveInputPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")
        proc = cli("input_path", "-b", "s4")
        if proc.returncode != 0:
            raise unittest.SkipTest(f"input_path warm-up failed: {proc.stderr[:300]}")

    def test_s4(self):
        proc, data = cli_json("input_path", "-b", "s4")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["stats"]["seeds"], 3)
        self.assertEqual(data["stats"]["gates"], 2)
        self.assertGreater(data["stats"]["edges"], 50)
        self.assertEqual(data["stats"]["verified_edges"], data["stats"]["edges"])
        self.assertTrue(data["button_bits"])
        rvas = {g["rva"] for g in data["gates"]}
        self.assertEqual(rvas, {"0x7AD3F8", "0x7AD12C"})
        self.assertTrue(any("vfunc" in w for w in data["warnings"]))

    def test_debug_mapped(self):
        proc, data = cli_json("input_path", "-b", "s4-debug")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        seeds = {s["role"]: s["rva"] for s in data["seeds"]}
        self.assertEqual(seeds["pad-state"], "0x884228")
        self.assertEqual(seeds["ctrl"], "0x88323C")
        self.assertEqual(seeds["action"], "0x84B2F8")
        self.assertTrue(all(g["rva"] for g in data["gates"]))

    def test_mcp_input_path(self):
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
            resp = rpc(2, "tools/call", {"name": "storm_input_path", "arguments": {"build": "s4"}})
            result = resp["result"]
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(result["isError"])
            self.assertEqual(data["stats"]["seeds"], 3)
            self.assertTrue(data["gates"])
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
