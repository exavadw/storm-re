import tempfile
import unittest

from support import add_symbol, make_db

from storm_re import inputpath


def payload(callees, callers):
    xrefs = [
        {
            "function_name": c,
            "from_address": "140000000",
            "to_address": "0",
            "type": "UNCONDITIONAL_CALL",
        }
        for c in callers
    ]
    return {
        "name": "f",
        "code": "void f(void){ return; }\n",
        "signature": "void f(void);",
        "error": None,
        "callees": list(callees),
        "xrefs": xrefs,
        "referenced_strings": [],
    }


class FakeClient:
    def __init__(self, by_va):
        self.by_va = by_va
        self.calls = []
        self.timeout = 180

    def call_tool(self, name, arguments, timeout=None):
        self.calls.append((name, arguments))
        if name != "decompile_function":
            raise AssertionError(f"unexpected tool {name}")
        return self.by_va[arguments["name_or_address"]]


class InputPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x7E10E0, "ccPlayerLeader::UpdatePadState")
        add_symbol(self.db, "s4", 0x7E0214, "ccPlayerLeader::CtrlInputPad")
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ChangeAction")
        self.db.set_symbol_version("s4")
        self.client = FakeClient(
            {
                "0x1407E10E0": payload(["FUN_1407c02dc"], ["FUN_1406b70f8"]),
                "0x1407E0214": payload(["FUN_1407c0c74"], ["FUN_140260de4"]),
                "0x1407AB468": payload(["ccPlayer::ResetBunshinState"], ["FUN_1407abaac"]),
            }
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_graph(self):
        result = inputpath.analyze_input_path(self.db, self.client, "s4")
        self.assertEqual(result["stats"]["seeds"], 3)
        self.assertGreaterEqual(result["stats"]["edges"], 6)
        self.assertEqual(result["stats"]["gates"], 2)
        self.assertTrue(result["button_bits"])
        roles = {n["role"] for n in result["nodes"]}
        self.assertTrue({"pad-state", "ctrl", "action", "gate"} <= roles)

    def test_no_direct_path_is_reported(self):
        result = inputpath.analyze_input_path(self.db, self.client, "s4")
        self.assertEqual(result["paths"], [])
        self.assertTrue(any("vfunc" in w for w in result["warnings"]))
        self.assertTrue(result["known_chain"])

    def test_edges_verified(self):
        result = inputpath.analyze_input_path(self.db, self.client, "s4")
        self.assertTrue(all(e["verified"] for e in result["edges"]))
        self.assertTrue(all(e["method"] in ("decompile", "xref") for e in result["edges"]))

    def test_gates_are_addresses(self):
        result = inputpath.analyze_input_path(self.db, self.client, "s4")
        rvas = {g["rva"] for g in result["gates"]}
        self.assertEqual(rvas, {"0x7AD3F8", "0x7AD12C"})


if __name__ == "__main__":
    unittest.main()
