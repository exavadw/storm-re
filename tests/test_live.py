import json
import os
import pathlib
import subprocess
import sys
import unittest

from support import ROOT

from storm_re import config

LIVE = os.environ.get("STORM_RE_LIVE") == "1"


def cli(*argv, timeout=600):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "storm_re", *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    return proc


def cli_json(*argv, timeout=600):
    proc = cli(*argv, "--json", timeout=timeout)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = None
    return proc, payload


@unittest.skipUnless(LIVE, "set STORM_RE_LIVE=1 to run live tests")
class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = config.db_path()
        if not cls.db.exists():
            raise unittest.SkipTest(f"no database at {cls.db}; run `storm-re init` first")

    def test_builds(self):
        proc, data = cli_json("builds")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        builds = {b["alias"]: b for b in data["builds"]}
        self.assertIn("s4", builds)
        self.assertTrue(builds["s4"]["sha256"].startswith("147e52a3"))
        present = [b for b in builds.values() if b["present"]]
        self.assertGreaterEqual(len(present), 10)

    def test_resolve_by_name(self):
        proc, data = cli_json("resolve", "ccPlayer::ChangeAction", "-b", "s4")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["name"], "ccPlayer::ChangeAction")
        self.assertEqual(data["rva"], "0x7AB468")
        self.assertEqual(data["source"], "nucc")
        self.assertEqual(data["confidence"], "high")

    def test_resolve_va_and_rva(self):
        _, a = cli_json("resolve", "0x1407AB468", "-b", "s4")
        _, b = cli_json("resolve", "0x7AB468", "-b", "s4")
        self.assertEqual(a["rva"], b["rva"])
        self.assertEqual(a["rva"], "0x7AB468")

    def test_resolve_debug_other_build(self):
        proc, data = cli_json("resolve", "ccPlayer::ChangeAction", "-b", "s4-debug")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["name"], "ccPlayer::ChangeAction")
        # 1.06 has two candidates for this name; the medium-confidence one wins
        # and the other is reported as a note, never silently dropped.
        self.assertTrue(data["notes"] or data["conflicts"])

    def test_short_name_is_ambiguous(self):
        proc, data = cli_json("resolve", "ChangeAction", "-b", "s4")
        self.assertEqual(proc.returncode, 2)
        self.assertGreaterEqual(len(data.get("candidates", [])), 2)

    def test_decomp_summary_and_cache(self):
        proc, data = cli_json("decomp", "ccPlayer::ChangeAction", "-b", "s4")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertLess(data["summary"]["summary_chars"], data["summary"]["raw_chars"])
        self.assertGreater(data["summary"]["saved_pct"], 50)
        self.assertIn("void FUN_", data["signature"])

        _, again = cli_json("decomp", "ccPlayer::ChangeAction", "-b", "s4")
        self.assertTrue(again["cache"]["hit"])

    def test_xrefs(self):
        proc, data = cli_json("xrefs", "ccPlayer::ChangeAction", "-b", "s4", "--limit", "500")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreater(len(data["xrefs"]), 0)
        self.assertTrue(
            any(e.get("function") == "FUN_1407abaac" for e in data["xrefs"]),
            "expected FUN_1407abaac in callers",
        )

    def test_diff(self):
        proc, data = cli_json(
            "diff", "ccPlayer::ChangeAction", "--from", "s4", "--to", "s4-debug"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(data["similarity"], 0.0)
        self.assertLessEqual(data["similarity"], 1.0)

    def test_find(self):
        proc, data = cli_json("find", "ChangeAction", "-b", "s4")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(
            any(r["name"] == "ccPlayer::ChangeAction" for r in data["results"])
        )

    def test_unknown_build(self):
        proc, data = cli_json("resolve", "ChangeAction", "-b", "nope")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(data["ok"])


if __name__ == "__main__":
    unittest.main()
