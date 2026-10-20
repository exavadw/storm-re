import tempfile
import unittest

from support import add_symbol, make_db

from storm_re import netsession


class FakeClient:
    def __init__(self):
        self.timeout = 180
        self.imports = {
            "imports": [
                {"name": "SteamMatchmaking", "library": "STEAM_API64.DLL"},
                {"name": "SteamNetworking", "library": "STEAM_API64.DLL"},
                {"name": "SteamUserStats", "library": "STEAM_API64.DLL"},
                {"name": "SteamAPI_RegisterCallback", "library": "STEAM_API64.DLL"},
            ]
        }

    def call_tool(self, name, arguments, timeout=None):
        if name == "list_imports":
            return self.imports
        return {
            "name": "f",
            "code": "void f(void){}\n",
            "signature": "void f(void);",
            "error": None,
            "callees": ["ccNetFreeBattleSync::SendFrameData"],
            "xrefs": [
                {
                    "function_name": "ccNetManager::ReceiveData",
                    "from_address": "1",
                    "to_address": "2",
                    "type": "UNCONDITIONAL_CALL",
                }
            ],
            "referenced_strings": [],
        }


class NetSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0xAF3B10, "ccNetFreeBattleSync::SendFrameData")
        add_symbol(self.db, "s4", 0xAF4CD0, "ccNetFreeBattleSync::ReceiveData")
        add_symbol(self.db, "s4", 0xAF2A60, "ccNetFreeBattleSync::CtrlFighting")
        add_symbol(self.db, "s4", 0xAEFDC0, "ccNetInputBuffer::Add")
        self.db.set_symbol_version("s4")
        self.client = FakeClient()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_direction(self):
        self.assertEqual(netsession.direction_of("ccNetFreeBattleSync::SendFrameData"), "send")
        self.assertEqual(netsession.direction_of("ccNetFreeBattleSync::ReceiveData"), "recv")
        self.assertEqual(netsession.direction_of("ccNetFreeBattleSync::CtrlFighting"), "tick")
        self.assertEqual(netsession.direction_of("ccNetInputBuffer::Add"), "buffer")
        self.assertEqual(netsession.layer_of("ccNetFreeBattleSync::SendFrameData"), "game-sync")

    def test_analyze(self):
        result = netsession.analyze_net_session(self.db, self.client, "s4", limit=10)
        directions = {f["direction"] for f in result["functions"]}
        self.assertTrue({"send", "recv", "tick", "buffer"} <= directions)
        self.assertGreaterEqual(result["stats"]["steam_interfaces"], 3)
        self.assertTrue(all(e["verified"] for e in result["edges"]))
        self.assertTrue(result["notes"])

    def test_no_imports(self):
        result = netsession.analyze_net_session(
            self.db, self.client, "s4", limit=10, include_imports=False
        )
        self.assertEqual(result["steam_interfaces"], [])


if __name__ == "__main__":
    unittest.main()
