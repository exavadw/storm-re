import tempfile
import unittest

from support import add_symbol, make_db

from storm_re.resolve import Ambiguous, NotFound, resolve


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ChangeAction")
        add_symbol(self.db, "s4", 0x7E10E0, "ccPlayerLeader::UpdatePadState")
        add_symbol(self.db, "s4-debug", 0x7AB468, "ccPlayer::ChangeAction")
        add_symbol(self.db, "s4-debug", 0x7E00E0, "ccPlayerLeader::UpdatePadState")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_rva_and_va_agree(self):
        a = resolve(self.db, "0x7ab468", "s4")
        b = resolve(self.db, "0x1407ab468", "s4")
        self.assertEqual(a.rva, b.rva)
        self.assertEqual(a.name, "ccPlayer::ChangeAction")
        self.assertEqual(a.va, 0x1407AB468)

    def test_full_and_short_name(self):
        self.assertEqual(resolve(self.db, "ccPlayer::ChangeAction", "s4").rva, 0x7AB468)
        self.assertEqual(resolve(self.db, "ChangeAction", "s4").rva, 0x7AB468)

    def test_manual_overrides_nucc(self):
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ManualName", source="manual")
        res = resolve(self.db, "ChangeAction", "s4")
        self.assertEqual(res.name, "ccPlayer::ManualName")
        self.assertTrue(any(c["name"] == "ccPlayer::ChangeAction" for c in res.conflicts))

    def test_different_rva_per_build(self):
        a = resolve(self.db, "UpdatePadState", "s4")
        b = resolve(self.db, "UpdatePadState", "s4-debug")
        self.assertEqual(a.rva, 0x7E10E0)
        self.assertEqual(b.rva, 0x7E00E0)

    def test_ambiguous(self):
        add_symbol(self.db, "s4", 0x1000, "nsA::DoThing")
        add_symbol(self.db, "s4", 0x2000, "nsB::DoThing")
        with self.assertRaises(Ambiguous) as ctx:
            resolve(self.db, "DoThing", "s4")
        self.assertEqual(len(ctx.exception.candidates), 2)

    def test_not_found_has_hint(self):
        with self.assertRaises(NotFound) as ctx:
            resolve(self.db, "ChangeActoin", "s4")
        self.assertIn("ChangeAction", str(ctx.exception))

    def test_address_without_symbol(self):
        res = resolve(self.db, "0x999999", "s4")
        self.assertIsNone(res.name)
        self.assertEqual(res.kind, "address")


if __name__ == "__main__":
    unittest.main()
