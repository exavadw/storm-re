import tempfile
import unittest

from support import add_symbol, make_db

from storm_re import patchdiff


class FakeClient:
    def __init__(self, by_key):
        self.by_key = by_key
        self.timeout = 180

    def call_tool(self, name, arguments, timeout=None):
        key = (arguments["binary_name"], arguments["name_or_address"])
        code = self.by_key.get(key, "void f(void){}\n")
        return {
            "name": "f",
            "code": code,
            "signature": "void f(void);",
            "error": None,
            "callees": [],
            "xrefs": [],
            "referenced_strings": [],
        }


class PatchDiffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x100, "ccPlayer::Same")
        add_symbol(self.db, "s4", 0x110, "ccPlayer::Changed")
        add_symbol(self.db, "s4-debug", 0x200, "ccPlayer::Same")
        add_symbol(self.db, "s4-debug", 0x210, "ccPlayer::Changed")
        self.db.set_symbol_version("s4")
        self.db.set_symbol_version("s4-debug")
        self.client = FakeClient(
            {
                ("/NSUNS4_release.exe-test", "0x140000100"): "a\nb\n",
                ("/NSUNS4_debug.exe-test", "0x140000200"): "a\nb\n",
                ("/NSUNS4_release.exe-test", "0x140000110"): "a\nb\n",
                ("/NSUNS4_debug.exe-test", "0x140000210"): "a\nB\nc\n",
            }
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_common_symbols(self):
        rows = self.db.common_symbols("s4", "s4-debug", 10)
        self.assertEqual({r["name"] for r in rows}, {"ccPlayer::Same", "ccPlayer::Changed"})

    def test_changed_and_same(self):
        result = patchdiff.analyze_patch_diff(
            self.db, self.client, "s4", "s4-debug",
            seeds="ccPlayer::Same,ccPlayer::Changed", include_same=True,
        )
        self.assertEqual(result["stats"]["compared"], 2)
        self.assertEqual(result["stats"]["changed"], 1)
        self.assertEqual(result["stats"]["same"], 1)
        by_name = {p["name"]: p for p in result["pairs"]}
        self.assertFalse(by_name["ccPlayer::Same"]["changed"])
        self.assertTrue(by_name["ccPlayer::Changed"]["changed"])

    def test_changed_only(self):
        result = patchdiff.analyze_patch_diff(
            self.db, self.client, "s4", "s4-debug",
            seeds="ccPlayer::Same,ccPlayer::Changed",
        )
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(result["pairs"][0]["name"], "ccPlayer::Changed")


if __name__ == "__main__":
    unittest.main()
