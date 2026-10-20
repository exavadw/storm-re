import json
import tempfile
import unittest
from pathlib import Path

from support import make_db

from storm_re import export


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        self.db.index_put(
            topic="input",
            build_alias="s4",
            rva=0x7AB468,
            name="ccPlayer::ChangeAction",
            target="ccPlayer::ChangeAction",
            sha256="a" * 64,
            name_version="v1",
            signature="void f(longlong *param_1,int param_2);",
            summary=json.dumps({"caller_count": 2, "callee_count": 3, "code_lines": 10,
                                "callers": ["a", "b"], "callees": ["c"]}),
            text="summary text",
            symbolized="void ccPlayer::ChangeAction(longlong *param_1){}",
            raw_chars=100,
            summary_chars=20,
            status="ok",
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_report(self):
        markdown, meta = export.build_report(self.db, "input")
        self.assertIn("# storm-re: input", markdown)
        self.assertIn("ccPlayer::ChangeAction", markdown)
        self.assertIn("0x7AB468", markdown)
        self.assertIn("## Caveats", markdown)
        self.assertEqual(meta["entries"][0]["name"], "ccPlayer::ChangeAction")

    def test_code(self):
        markdown, _ = export.build_report(self.db, "input", include_code=True)
        self.assertIn("void ccPlayer::ChangeAction", markdown)

    def test_write(self):
        markdown, meta = export.build_report(self.db, "input")
        path = Path(self.tmp.name) / "report.md"
        out = export.write_report(markdown, str(path))
        self.assertTrue(Path(out).exists())
        self.assertIn("storm-re: input", Path(out).read_text())


if __name__ == "__main__":
    unittest.main()
