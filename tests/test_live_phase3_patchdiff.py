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
class LivePatchDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")
        proc = cli("patch_diff", "--from", "s4", "--to", "s4-debug", "--limit", "5")
        if proc.returncode != 0:
            raise unittest.SkipTest(f"patch_diff warm-up failed: {proc.stderr[:300]}")

    def test_batch(self):
        proc, data = cli_json("patch_diff", "--from", "s4", "--to", "s4-debug", "--limit", "5")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(data["stats"]["compared"], 1)
        self.assertTrue(data["pairs"])
        self.assertTrue(data["notes"])

    def _has_clean(self):
        _, data = cli_json("builds")
        return bool(data) and any(
            b["alias"] == "s1-clean" and b["present"] for b in data["builds"]
        )

    def test_clean_vs_mod_byte_diff(self):
        if not self._has_clean():
            self.skipTest("s1-clean is not registered")
        proc, data = cli_json(
            "patch_diff", "--from", "s1-clean", "--to", "s1", "--limit", "5"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["stats"]["mode"], "byte")
        self.assertGreater(data["stats"]["byte_compared"], 1000)
        self.assertGreater(data["stats"]["changed"], 0)
        self.assertTrue(any(p.get("byte_diff") for p in data["pairs"]))
        self.assertTrue(any(p["name"].startswith("ccPlayerRpg::") for p in data["pairs"]))

    def test_clean_vs_mod_seed(self):
        if not self._has_clean():
            self.skipTest("s1-clean is not registered")
        proc, data = cli_json(
            "patch_diff", "--from", "s1-clean", "--to", "s1",
            "--seeds", "ccPlayerRpg::CtrlAct_RPG_DASH",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["stats"]["changed"], 1)
        self.assertEqual(data["pairs"][0]["name"], "ccPlayerRpg::CtrlAct_RPG_DASH")
        self.assertLess(data["pairs"][0]["similarity"], 1.0)

    def test_clean_vs_mod_mcp(self):
        if not self._has_clean():
            self.skipTest("s1-clean is not registered")
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
                {"name": "storm_patch_diff",
                 "arguments": {"from_build": "s1-clean", "to_build": "s1", "limit": 3}},
            )
            result = resp["result"]
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(result["isError"])
            self.assertGreater(data["stats"]["changed"], 0)
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            proc.stdout.close()
            proc.stderr.close()

    def test_mcp_patch_diff(self):
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
                {"name": "storm_patch_diff",
                 "arguments": {"from_build": "s4", "to_build": "s4-debug", "limit": 3}},
            )
            result = resp["result"]
            data = json.loads(result["content"][0]["text"])
            self.assertFalse(result["isError"])
            self.assertGreaterEqual(data["stats"]["compared"], 1)
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
