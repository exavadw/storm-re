import tempfile
import unittest

from support import add_symbol, make_db

from storm_re import frametick

CODE = """void f(longlong *param_1)
{
  bVar1 = *(byte *)(DAT_1416663c8 + 0x942);
  iVar2 = -(int)(3000 / (ulonglong)bVar1);
  *(int *)(param_1 + 0x27fe) = (int)(30.0 / (30.0 / (float)bVar1));
  iVar6 = 0;
  iVar6 += 5;
}
"""


class ScanTests(unittest.TestCase):
    def test_idioms_and_constants(self):
        found = frametick.scan_code(CODE)
        kinds = {i["kind"] for i in found["idioms"]}
        self.assertIn("state-timer-neg", kinds)
        self.assertIn("scaled-thirty", kinds)
        self.assertTrue(found["fps_sources"])
        self.assertTrue(any("+= 5" in c["line"] for c in found["constants"]))

    def test_no_idioms(self):
        found = frametick.scan_code("void g(void){ x = 1; }\n")
        self.assertEqual(found["idioms"], [])
        self.assertEqual(found["fps_sources"], [])
        self.assertEqual(found["constants"], [])


class FakeClient:
    def __init__(self, by_va):
        self.by_va = by_va
        self.timeout = 180

    def call_tool(self, name, arguments, timeout=None):
        return {
            "name": "f",
            "code": self.by_va.get(arguments["name_or_address"], "void f(void){}\n"),
            "signature": "void f(void);",
            "error": None,
            "callees": [],
            "xrefs": [],
            "referenced_strings": [],
        }


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ChangeAction")
        self.db.set_symbol_version("s4")
        self.client = FakeClient({"0x1407AB468": CODE})

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_select_seeds_includes_changeaction(self):
        seeds = frametick.select_frame_seeds(self.db, "s4", 10)
        names = [s.name for s in seeds]
        self.assertIn("ccPlayer::ChangeAction", names)

    def test_analyze(self):
        result = frametick.analyze_frame_tick(self.db, self.client, "s4", limit=10)
        names = {f["name"] for f in result["functions"]}
        self.assertIn("ccPlayer::ChangeAction", names)
        self.assertGreaterEqual(result["stats"]["idioms"], 2)
        self.assertTrue(result["notes"])


if __name__ == "__main__":
    unittest.main()
