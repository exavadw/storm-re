import unittest

from support import ROOT  # noqa: F401  (adds src to sys.path)

from storm_re.text import fmt_addr, fun_addr, is_hex, parse_addr, split_name, truncate


class TextTests(unittest.TestCase):
    def test_parse_bare_and_prefixed(self):
        self.assertEqual(parse_addr("0x7ab468"), 0x7AB468)
        self.assertEqual(parse_addr("7ab468"), 0x7AB468)
        self.assertEqual(parse_addr("0x1407AB468"), 0x1407AB468)

    def test_fun_name(self):
        self.assertEqual(fun_addr("FUN_1407ab468"), 0x1407AB468)
        self.assertEqual(fun_addr("thunk_FUN_1407ab468"), 0x1407AB468)
        self.assertIsNone(fun_addr("ccPlayer::ChangeAction"))

    def test_hex_detection(self):
        self.assertTrue(is_hex("0x7ab468"))
        self.assertTrue(is_hex("deadbeef"))
        self.assertFalse(is_hex("ChangeAction"))

    def test_split(self):
        self.assertEqual(split_name("ns3::ccPlayer::ChangeAction"), ("ns3::ccPlayer", "ChangeAction"))
        self.assertEqual(split_name("ChangeAction"), ("", "ChangeAction"))

    def test_truncate(self):
        body, cut = truncate("a" * 100, 10)
        self.assertTrue(cut)
        self.assertIn("truncated", body)
        body, cut = truncate("short", 100)
        self.assertFalse(cut)

    def test_fmt(self):
        self.assertEqual(fmt_addr(0x7AB468), "0x7AB468")


if __name__ == "__main__":
    unittest.main()
