import tempfile
import unittest

from support import add_symbol, make_db

from storm_re import scenedispatch


def payload(code="void f(void){}\n", strings=None, callees=None, callers=None):
    return {
        "name": "f",
        "code": code,
        "signature": "void f(void);",
        "error": None,
        "callees": list(callees or []),
        "xrefs": [
            {"function_name": c, "from_address": "1", "to_address": "2", "type": "UNCONDITIONAL_CALL"}
            for c in (callers or [])
        ],
        "referenced_strings": [{"value": s, "address": "0"} for s in (strings or [])],
    }


class FakeClient:
    def __init__(self, by_va):
        self.by_va = by_va
        self.timeout = 180

    def call_tool(self, name, arguments, timeout=None):
        return self.by_va.get(arguments["name_or_address"], payload())


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x871310, "Movie::Invoke")
        add_symbol(self.db, "s4", 0xABD020, "ccMessageManager::GetMessageParam")
        add_symbol(self.db, "s4", 0xAB93D0, "ccUiGetMessageSpeaker")
        self.db.set_symbol_version("s4")
        self.client = FakeClient(
            {
                "0x140871310": payload(strings=[".gfx", "c_sta_01", "option"]),
                "0x140ABD020": payload(callers=["ccSceneManager::Execute"]),
                "0x140AB93D0": payload(strings=["c_sta_07"]),
            }
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_roles_and_message(self):
        result = scenedispatch.analyze_scene_dispatch(self.db, self.client, "s4", limit=10)
        roles = {f["role"] for f in result["functions"]}
        self.assertIn("message", roles)
        self.assertIn("ui", roles)
        self.assertIsNotNone(result["message_lookup"])
        self.assertEqual(result["message_lookup"]["rva"], "0xABD020")

    def test_strings_and_ids(self):
        result = scenedispatch.analyze_scene_dispatch(self.db, self.client, "s4", limit=10)
        ids = {x["id"] for x in result["scene_ids"]}
        self.assertEqual(ids, {"0x5300", "0x5301"})
        all_stages = {s for f in result["functions"] for s in f["stage_names"]}
        self.assertIn("c_sta_01", all_stages)

    def test_notes(self):
        result = scenedispatch.analyze_scene_dispatch(self.db, self.client, "s4", limit=10)
        self.assertTrue(any("0x5300" in n for n in result["notes"]))


if __name__ == "__main__":
    unittest.main()
