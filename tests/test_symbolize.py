import tempfile
import unittest

from support import add_symbol, make_db

from storm_re.symbolize import sanitize, symbolize_code


class SymbolizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ChangeAction")
        add_symbol(self.db, "s4", 0x76B4B0, "ccPlayer::ResetBunshinState")
        add_symbol(self.db, "s4", 0x900, "_Call_func$catch$0")
        add_symbol(self.db, "s4", 0x1000, "operator new")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_rewrite_and_leave_placeholders(self):
        code = (
            "void FUN_1407ab468(void) {\n"
            "  FUN_14076b4b0();\n"
            "  DAT_1416663c8 = 0;\n"
            "LAB_1407ab500:\n"
            "  PTR_FUN_14076b4b0();\n"
            "  thunk_FUN_14076b4b0();\n"
            "}\n"
        )
        out, mapping, unresolved = symbolize_code(self.db, "s4", code)
        self.assertIn("void ccPlayer::ChangeAction(void)", out)
        self.assertIn("ccPlayer::ResetBunshinState()", out)
        self.assertIn("thunk_ccPlayer::ResetBunshinState()", out)
        self.assertIn("DAT_1416663c8", out)
        self.assertIn("LAB_1407ab500", out)
        self.assertIn("PTR_FUN_14076b4b0", out)
        self.assertEqual(len(mapping), 3)
        self.assertEqual(unresolved, 1)
        self.assertTrue(all(m["source"] == "nucc" for m in mapping))

    def test_sanitize(self):
        self.assertEqual(sanitize("_Call_func$catch$0"), "_Call_func_catch_0")
        self.assertEqual(sanitize("operator new"), "operator_new")
        self.assertEqual(sanitize("ccPlayer::ChangeAction"), "ccPlayer::ChangeAction")

    def test_sanitized_names_in_code(self):
        code = "void FUN_140000900(void){ FUN_140001000(); }"
        out, mapping, _ = symbolize_code(self.db, "s4", code)
        self.assertIn("_Call_func_catch_0", out)
        self.assertIn("operator_new", out)
        self.assertEqual(len(mapping), 2)

    def test_manual_overrides_nucc(self):
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ManualName", source="manual")
        out, mapping, _ = symbolize_code(self.db, "s4", "void FUN_1407ab468(void){}")
        self.assertIn("ccPlayer::ManualName", out)
        self.assertEqual(mapping[0]["source"], "manual")

    def test_dunder_promotion(self):
        out, mapping, _ = symbolize_code(
            self.db, "s4", "ccPlayer__ResetBunshinState(param_1);"
        )
        self.assertIn("ccPlayer::ResetBunshinState(param_1)", out)
        self.assertEqual(mapping[0]["name"], "ccPlayer::ResetBunshinState")

    def test_32bit_base(self):
        self.db.upsert_build("s3fb", "/NS3FB.exe-test", sha256="d" * 64, base=0x400000)
        add_symbol(self.db, "s3fb", 0x1234, "ccThing::Foo")
        out, mapping, _ = symbolize_code(self.db, "s3fb", "void FUN_00401234(void){}")
        self.assertIn("ccThing::Foo", out)
        self.assertEqual(mapping[0]["rva"], "0x1234")

    def test_unknown_token_untouched(self):
        out, mapping, unresolved = symbolize_code(
            self.db, "s4", "void FUN_140999999(void){}"
        )
        self.assertIn("FUN_140999999", out)
        self.assertEqual(mapping, [])
        self.assertEqual(unresolved, 1)


if __name__ == "__main__":
    unittest.main()
