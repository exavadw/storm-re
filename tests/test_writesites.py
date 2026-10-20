import tempfile
import unittest

from support import add_symbol, decompile_payload, make_db

from storm_re import writesites


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.timeout = 180

    def call_tool(self, name, arguments, timeout=None):
        self.calls.append((name, arguments))
        return self.payload


class AddressModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        self.client = FakeClient(
            {
                "cross_references": [
                    {"type": "WRITE", "function_name": "FUN_140530174", "from_address": "140530245"},
                    {"type": "WRITE", "function_name": "FUN_140530174", "from_address": "140530264"},
                    {"type": "READ", "function_name": "FUN_140a198b0", "from_address": "140a198b6"},
                    {"type": "UNCONDITIONAL_CALL", "function_name": "FUN_140111111", "from_address": "140111119"},
                    {"type": "DATA", "function_name": None, "from_address": "148dac5a0"},
                ]
            }
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_writes_only_by_default(self):
        result = writesites.analyze_address(
            self.db, self.client, "0x1416663c8", "s4"
        )
        self.assertEqual(len(result["sites"]), 1)
        self.assertEqual(result["sites"][0]["kind"], "write")
        self.assertEqual(result["sites"][0]["count"], 2)
        self.assertEqual(result["stats"]["xrefs_total"], 5)

    def test_include_reads(self):
        result = writesites.analyze_address(
            self.db, self.client, "0x1416663c8", "s4", include_reads=True
        )
        kinds = {s["kind"] for s in result["sites"]}
        self.assertEqual(kinds, {"write", "read", "data"})

    def test_include_calls(self):
        result = writesites.analyze_address(
            self.db, self.client, "0x1416663c8", "s4", include_calls=True
        )
        kinds = {s["kind"] for s in result["sites"]}
        self.assertIn("call", kinds)


class OffsetModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x100, "ccPlayer::ChangeAction")
        self.db.set_symbol_version("s4")
        code = (
            "void f(longlong *param_1)\n"
            "{\n"
            "  *(int *)((longlong)param_1 + 0xcc4) = 0;\n"
            "  x = *(int *)((longlong)param_1 + 0xcc4);\n"
            "}\n"
        )
        self.client = FakeClient(decompile_payload(code))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_writer(self):
        result = writesites.analyze_offset(
            self.db, self.client, "ccPlayer", 0xCC4, "s4", limit=1
        )
        self.assertEqual(len(result["sites"]), 1)
        self.assertEqual(result["sites"][0]["kind"], "write")
        self.assertEqual(result["sites"][0]["function"], "ccPlayer::ChangeAction")
        self.assertEqual(result["stats"]["writes"], 1)

    def test_reader(self):
        result = writesites.analyze_offset(
            self.db, self.client, "ccPlayer", 0xCC4, "s4",
            include_reads=True, limit=10,
        )
        kinds = {s["kind"] for s in result["sites"]}
        self.assertEqual(kinds, {"write", "read"})

    def test_missing_offset(self):
        result = writesites.analyze_offset(
            self.db, self.client, "ccPlayer", 0xCC0, "s4", limit=1
        )
        self.assertEqual(result["sites"], [])
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
