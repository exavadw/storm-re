import unittest

from support import decompile_payload

from storm_re.summarize import summarize


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        code = "\n".join(f"  line_{i} = {i};" for i in range(400))
        self.raw = decompile_payload(
            code,
            callers=100,
            callees=[f"fn_{i}" for i in range(100)] + [f"FUN_{i:08x}" for i in range(20)],
        )

    def test_caps(self):
        s = summarize(self.raw)
        self.assertEqual(s["caller_count"], 100)
        self.assertEqual(len(s["callers"]), 40)
        self.assertEqual(len(s["callees"]), 60)
        self.assertGreaterEqual(s["fun_callee_count"], 20)

    def test_savings(self):
        s = summarize(self.raw)
        self.assertGreater(s["saved_pct"], 50)
        self.assertEqual(s["code_lines"], 400)

    def test_sig_is_smaller(self):
        s = summarize(self.raw, detail="sig")
        self.assertNotIn("callers (", s["text"])
        self.assertIn("void FUN_1407ab468", s["text"])

    def test_code_head(self):
        s = summarize(self.raw, detail="summary", head=5)
        self.assertIn("line_0", s["text"])
        self.assertNotIn("line_50", s["text"])

    def test_full_has_code(self):
        s = summarize(self.raw, detail="full")
        self.assertIn("line_399", s["text"])


if __name__ == "__main__":
    unittest.main()
