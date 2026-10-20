import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from support import add_symbol, decompile_payload, make_db

from storm_re import commands


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def call_tool(self, name, arguments, timeout=None):
        self.calls.append((name, arguments))
        if name == "decompile_function":
            return self.payloads[arguments["binary_name"]]
        raise AssertionError(f"unexpected tool {name}")


def args(**kw):
    base = dict(
        db=None, mcp=None, json=False, quiet=True, timeout=180.0, no_cache=False,
        refresh=False, build="s4", addr_kind=None, detail="summary",
        max_bytes=8000, head=0, direction="to", limit=100,
        from_build="s4", to_build="s4-debug", mode="symbol", semantic=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ChangeAction")
        add_symbol(self.db, "s4-debug", 0x7AB468, "ccPlayer::ChangeAction")
        self.db.set_symbol_version("s4")
        self.db.set_symbol_version("s4-debug")
        self.payloads = {
            "/NSUNS4_release.exe-test": decompile_payload("a\nb\nc\n"),
            "/NSUNS4_debug.exe-test": decompile_payload(
                "a\nB\nc\nd\n", callees=["ccPlayer::Other", "FUN_14076b4b0"]
            ),
        }
        self.client = FakeClient(self.payloads)
        self.patches = [
            mock.patch.object(commands, "open_db", return_value=self.db),
            mock.patch.object(commands, "make_client", return_value=self.client),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.db.close()
        self.tmp.cleanup()

    def run_cmd(self, fn, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = fn(args(**kw))
        return code, buf.getvalue()

    def test_decomp_cache_hit(self):
        code, out = self.run_cmd(commands.cmd_decomp, target="ChangeAction")
        self.assertEqual(code, 0)
        self.assertIn("ccPlayer::ChangeAction", out)
        self.assertIn("cache    miss", out)

        code, out = self.run_cmd(commands.cmd_decomp, target="ChangeAction")
        self.assertIn("cache    hit", out)
        self.assertEqual(len(self.client.calls), 1)

    def test_decomp_json(self):
        code, out = self.run_cmd(commands.cmd_decomp, target="ChangeAction", json=True)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["rva"], "0x7AB468")
        self.assertLess(len(payload["text"]), payload["summary"]["raw_chars"])

    def test_xrefs(self):
        code, out = self.run_cmd(commands.cmd_xrefs, target="ChangeAction")
        self.assertEqual(code, 0)
        self.assertIn("caller_0", out)
        self.assertNotIn("951", out)

    def test_diff(self):
        code, out = self.run_cmd(commands.cmd_diff, target="ChangeAction")
        self.assertEqual(code, 0)
        self.assertIn("similarity", out)
        self.assertIn("ccPlayer::Other", out)

    def test_find(self):
        code, out = self.run_cmd(commands.cmd_find, query="ChangeAction")
        self.assertEqual(code, 0)
        self.assertIn("ccPlayer::ChangeAction", out)
        self.assertEqual(self.client.calls, [])

    def test_empty_decompile_is_not_cached(self):
        from storm_re.mcp import MCPError

        self.payloads["/NSUNS4_release.exe-test"] = {
            "name": "bad", "code": "", "signature": "", "error": None,
            "callees": [], "xrefs": [], "referenced_strings": [],
        }
        with self.assertRaises(MCPError):
            commands.cmd_decomp(args(target="ccPlayer::ChangeAction"))
        self.assertIsNone(
            self.db.cache_get(
                "a" * 64, 0x7AB468, "decompile", "v1:xrefs=1,callees=1,strings=1",
                self.db.name_version("s4"),
            )
        )

    def test_poisoned_cache_is_refetched(self):
        from storm_re.summarize import summarize

        version = self.db.name_version("s4")
        bad = {
            "name": "bad", "code": "", "signature": "", "error": None,
            "callees": [], "xrefs": [], "referenced_strings": [],
        }
        s = summarize(bad)
        self.db.cache_put(
            "a" * 64, 0x7AB468, "decompile", "v1:xrefs=1,callees=1,strings=1",
            version, bad, s, s["raw_chars"], s["summary_chars"],
        )
        code, out = self.run_cmd(commands.cmd_decomp, target="ccPlayer::ChangeAction")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.client.calls), 1)
        hit = self.db.cache_get(
            "a" * 64, 0x7AB468, "decompile", "v1:xrefs=1,callees=1,strings=1", version
        )
        self.assertIn("a", hit["raw"]["code"])


if __name__ == "__main__":
    unittest.main()
