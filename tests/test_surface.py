import tempfile
import unittest

from support import add_symbol, make_db

from storm_re import surface


class SurfaceParseTests(unittest.TestCase):
    def test_pointer_scaling_and_rw(self):
        code = """void f(longlong *param_1,int param_2)
{
  lVar7 = param_1[0x198];
  *(int *)(param_1 + 0x198) = param_2;
  *(int *)((longlong)param_1 + 0xcc4) = lVar7;
  bVar1 = *(byte *)((longlong)param_1 + 0x942);
  if (*(int *)((longlong)param_1 + 0xc8c) == 0x91) { }
  param_1[0x29b7] = 0x3f800000;
  x = *(undefined4 *)(param_1 + 0x199);
  *(int *)((longlong)param_1 + 0xcc4) += 1;
}
"""
        accesses, unknown = surface.parse_surface(code)
        self.assertFalse(unknown)
        by_off = {}
        for a in accesses:
            by_off.setdefault(a.offset, []).append(a)
        self.assertEqual(set(by_off), {0xCC0, 0xCC4, 0x942, 0xC8C, 0x14DB8, 0xCC8})
        self.assertEqual(len(by_off[0xCC0]), 2)
        self.assertEqual({a.size for a in by_off[0xCC0]}, {8, 4})
        self.assertTrue(any(a.write for a in by_off[0xCC0]))
        self.assertEqual({a.size for a in by_off[0xCC4]}, {4})
        self.assertTrue(all(a.write for a in by_off[0xCC4]))
        self.assertEqual(by_off[0x942][0].size, 1)
        self.assertFalse(by_off[0x942][0].write)
        self.assertEqual(by_off[0xC8C][0].size, 4)
        self.assertFalse(by_off[0xC8C][0].write)
        self.assertTrue(by_off[0x14DB8][0].write)
        self.assertEqual(by_off[0xCC8][0].size, 4)

    def test_int_pointer_scale(self):
        accesses, _ = surface.parse_surface("void f(int *param_1){ x = param_1[0x1a]; }")
        self.assertEqual(accesses[0].offset, 0x68)
        self.assertEqual(accesses[0].size, 4)

    def test_unknown_struct_pointer(self):
        code = (
            "void f(ccPlayer *param_1){ "
            "x = param_1 + 0x10; "
            "y = *(int *)((longlong)param_1 + 0x20); }"
        )
        accesses, unknown = surface.parse_surface(code)
        self.assertTrue(unknown)
        self.assertEqual(len(accesses), 1)
        self.assertEqual(accesses[0].offset, 0x20)
        self.assertEqual(accesses[0].size, 4)

    def test_write_classification(self):
        self.assertFalse(surface._is_write(") == 0x91)"))
        self.assertFalse(surface._is_write(");"))
        self.assertTrue(surface._is_write(") = 1;"))
        self.assertTrue(surface._is_write(" = 1;"))
        self.assertTrue(surface._is_write(" += 1;"))
        self.assertTrue(surface._is_write("++"))

    def test_aggregate_confidence(self):
        a1 = surface.Access(0x10, 4, True, "fnA", 0x100, "a")
        a2 = surface.Access(0x10, 4, False, "fnB", 0x200, "b")
        a3 = surface.Access(0x20, None, True, "fnA", 0x100, "c")
        fields = surface._aggregate([a1, a2, a3], 0x1000, 0)
        by_off = {f["offset"]: f for f in fields}
        self.assertEqual(by_off["0x10"]["confidence"], "high")
        self.assertEqual(by_off["0x10"]["kind"], "rw")
        self.assertEqual(by_off["0x20"]["confidence"], "low")


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x100, "ccPlayer::ChangeAction")
        add_symbol(self.db, "s4", 0x200, "ccPlayer::GetOpponentPlayerPtr")
        add_symbol(self.db, "s4", 0x300, "ccPlayerLeader::UpdatePadState")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_prefix_dedupes_and_prioritizes(self):
        rows = self.db.symbols_prefix("s4", "ccPlayer::", 10)
        names = [r["name"] for r in rows]
        self.assertIn("ccPlayer::ChangeAction", names)
        self.assertNotIn("ccPlayerLeader::UpdatePadState", names)
        self.assertEqual(len(rows), 2)
        seeds = surface.select_seeds(self.db, "s4", "ccPlayer", limit=1)
        self.assertEqual(seeds[0].name, "ccPlayer::ChangeAction")


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.timeout = 180

    def call_tool(self, name, arguments, timeout=None):
        self.calls += 1
        return self.payload


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x100, "ccPlayer::ChangeAction")
        self.db.set_symbol_version("s4")
        self.code = (
            "void f(longlong *param_1,int param_2)\n"
            "{\n"
            "  param_1[0x198] = param_2;\n"
            "  *(int *)((longlong)param_1 + 0xcc4) = 0;\n"
            "}\n"
        )
        self.client = FakeClient(
            {"name": "x", "code": self.code, "signature": "", "error": None,
             "callees": [], "xrefs": [], "referenced_strings": []}
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_analyze(self):
        result = surface.analyze(self.db, self.client, "ccPlayer", "s4", limit=1)
        offsets = {f["offset"] for f in result["fields"]}
        self.assertIn("0xCC0", offsets)
        self.assertIn("0xCC4", offsets)
        self.assertEqual(result["stats"]["seeds_analyzed"], 1)
        self.assertEqual(result["stats"]["writes"], 2)


if __name__ == "__main__":
    unittest.main()
