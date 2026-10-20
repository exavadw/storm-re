import json
import os
import subprocess
import sys
import unittest

from support import ROOT

from storm_re import config

LIVE = os.environ.get("STORM_RE_LIVE") == "1"


@unittest.skipUnless(LIVE, "set STORM_RE_LIVE=1 to run live tests")
class LiveMCP2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "src")
        cls.proc = subprocess.Popen(
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
        cls.next_id = 0
        cls.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        cls.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        cls.proc.stdin.flush()

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
            raise AssertionError(f"server closed: {cls.proc.stderr.read()[:400]}")
        return json.loads(line)

    @classmethod
    def call(cls, name, arguments):
        resp = cls.rpc("tools/call", {"name": name, "arguments": arguments})
        result = resp["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def test_explain(self):
        is_error, data = self.call("storm_explain", {"target": "ccPlayer::ChangeAction"})
        self.assertFalse(is_error)
        self.assertIn("ccPlayer::ChangeAction", data["code"])
        self.assertTrue(data["maps"])

    def test_batch(self):
        is_error, data = self.call("storm_batch", {"calls": [
            {"tool": "storm_resolve", "arguments": {"target": "ccPlayer::ChangeAction"}},
            {"tool": "storm_stat", "arguments": {}},
        ]})
        self.assertFalse(is_error)
        self.assertEqual(len(data["results"]), 2)
        self.assertTrue(all(r["result"]["ok"] for r in data["results"]))

    def test_resource_builds(self):
        resp = self.rpc("resources/read", {"uri": "storm-re://builds"})
        text = resp["result"]["contents"][0]["text"]
        self.assertIn("s4", text)
        self.assertIn("s1-clean", text)

    def test_resource_topic(self):
        resp = self.rpc("resources/read", {"uri": "storm-re://topic/input"})
        text = resp["result"]["contents"][0]["text"]
        self.assertIn("# storm-re: input", text)
        self.assertIn("ccPlayer::ChangeAction", text)

    def test_resource_function(self):
        resp = self.rpc("resources/read", {"uri": "storm-re://function/s4/0x7AB468"})
        text = resp["result"]["contents"][0]["text"]
        self.assertIn("ccPlayer::ChangeAction", text)

    def test_progress_notification(self):
        self.next_id += 1
        rid = self.next_id
        msg = {
            "jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {
                "name": "storm_patch_diff",
                "arguments": {"from_build": "s1-clean", "to_build": "s1", "limit": 20},
                "_meta": {"progressToken": "p1"},
            },
        }
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        saw_progress = False
        for _ in range(200):
            line = self.proc.stdout.readline()
            if not line:
                break
            event = json.loads(line)
            if event.get("method") == "notifications/progress":
                saw_progress = True
            if event.get("id") == rid:
                break
        self.assertTrue(saw_progress)

    def test_prompt(self):
        resp = self.rpc("prompts/get", {"name": "clean_vs_mod", "arguments": {}})
        text = resp["result"]["messages"][0]["content"]["text"]
        self.assertIn("storm_patch_diff", text)


if __name__ == "__main__":
    unittest.main()
