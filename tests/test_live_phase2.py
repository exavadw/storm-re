import json
import os
import subprocess
import sys
import unittest

from support import ROOT

from storm_re import config

LIVE = os.environ.get("STORM_RE_LIVE") == "1"


@unittest.skipUnless(LIVE, "set STORM_RE_LIVE=1 to run live tests")
class LiveMCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = config.db_path()
        if not db.exists():
            raise unittest.SkipTest(f"no database at {db}")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        cls.proc = subprocess.Popen(
            [
                sys.executable, "-m", "storm_re.mcp_server",
                "--db", str(db),
                "--backend", "http://127.0.0.1:9/mcp",  # deliberately dead
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        cls.next_id = 0

    @classmethod
    def tearDownClass(cls):
        cls.proc.stdin.close()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.proc.stdout.close()
        cls.proc.stderr.close()

    @classmethod
    def rpc(cls, method, params=None):
        cls.next_id += 1
        msg = {"jsonrpc": "2.0", "id": cls.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        cls.proc.stdin.write(json.dumps(msg) + "\n")
        cls.proc.stdin.flush()
        line = cls.proc.stdout.readline()
        if not line:
            raise AssertionError(f"server closed: {cls.proc.stderr.read()[:500]}")
        return json.loads(line)

    @classmethod
    def call(cls, name, arguments):
        resp = cls.rpc("tools/call", {"name": name, "arguments": arguments})
        result = resp["result"]
        text = result["content"][0]["text"]
        return result["isError"], json.loads(text)

    def test_01_initialize_and_list(self):
        resp = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        self.assertEqual(resp["result"]["serverInfo"]["name"], "storm-re")
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        self.proc.stdin.flush()
        resp = self.rpc("tools/list")
        self.assertEqual(len(resp["result"]["tools"]), 20)

    def test_02_resolve_local(self):
        is_error, data = self.call(
            "storm_resolve", {"target": "ccPlayer::ChangeAction", "build": "s4"}
        )
        self.assertFalse(is_error)
        self.assertEqual(data["rva"], "0x7AB468")

    def test_03_show_local_with_dead_backend(self):
        is_error, data = self.call("storm_show", {"query": "input", "limit": 5})
        self.assertFalse(is_error)
        self.assertGreaterEqual(len(data["entries"]), 1)

    def test_04_map(self):
        is_error, data = self.call(
            "storm_map", {"name": "ccPlayerLeader::UpdatePadState", "from_build": "s4", "to_build": "s4-debug"}
        )
        self.assertFalse(is_error)
        self.assertEqual(data["maps"][0]["to_rva"], "0x884228")

    def test_05_decomp_cache_hit_with_dead_backend(self):
        is_error, data = self.call(
            "storm_decomp", {"target": "ccPlayer::ChangeAction", "build": "s4", "detail": "sig"}
        )
        self.assertFalse(is_error)
        self.assertTrue(data["cache"]["hit"])

    def test_06_unknown_build_is_error(self):
        is_error, data = self.call("storm_resolve", {"target": "x", "build": "nope"})
        self.assertTrue(is_error)
        self.assertEqual(data["code"], 2)

    def test_07_stat(self):
        is_error, data = self.call("storm_stat", {})
        self.assertFalse(is_error)
        self.assertGreater(data["bsim_edges"], 0)
        self.assertGreater(data["index_entries"], 0)


if __name__ == "__main__":
    unittest.main()
