import json
import os
import subprocess
import sys
import unittest

from support import ROOT

from storm_re import config

LIVE = os.environ.get("STORM_RE_LIVE") == "1"


def cli(*argv, timeout=900):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "storm_re", *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def cli_json(*argv, timeout=900):
    proc = cli(*argv, "--json", timeout=timeout)
    try:
        return proc, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc, None


@unittest.skipUnless(LIVE, "set STORM_RE_LIVE=1 to run live tests")
class LivePhase1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not config.db_path().exists():
            raise unittest.SkipTest(f"no database at {config.db_path()}; run `storm-re init`")

    def test_bsim_edges(self):
        proc, data = cli_json("bsim", "stat")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreater(data["edges"], 600_000)

    def test_map_changeaction(self):
        proc, data = cli_json("map", "ccPlayer::ChangeAction", "--from", "s4", "--to", "s4-debug")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = data["maps"][0]
        self.assertEqual(row["to_rva"], "0x84B2F8")
        self.assertGreaterEqual(row["score"], 0.65)

    def test_map_updatepad_direct(self):
        proc, data = cli_json(
            "map", "ccPlayerLeader::UpdatePadState", "--from", "s4", "--to", "s4-debug"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = data["maps"][0]
        self.assertEqual(row["to_rva"], "0x884228")
        self.assertEqual(row["method"], "bsim-direct")
        self.assertAlmostEqual(row["score"], 1.0, places=3)

    def test_map_damage_direct(self):
        proc, data = cli_json(
            "map", "ccPlayer::OnDamageGuardHit", "--from", "s4", "--to", "s4-debug"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = data["maps"][0]
        self.assertEqual(row["to_rva"], "0x827E00")
        self.assertEqual(row["method"], "bsim-direct")

    def test_map_address_uses_name_not_false_positive(self):
        proc, data = cli_json(
            "map", "0xABD020", "--from", "s4", "--to", "s4-debug", "--refresh"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = data["maps"][0]
        self.assertEqual(row["to_rva"], "0x1A4FE0")
        self.assertEqual(row["method"], "name")
        self.assertEqual(row["to_name"], "ccMessageManager::GetMessageParam")

    def test_index_and_local_show(self):
        proc = cli("index", "--topic", "input", "--build", "s4", "--limit", "3")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # A deliberately dead MCP URL proves `show` never touches the backend.
        proc, data = cli_json("show", "input", "--mcp", "http://127.0.0.1:9/mcp")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreaterEqual(len(data["entries"]), 3)
        self.assertTrue(any("callers=" in e["text"] for e in data["entries"]))

    def test_index_is_idempotent_without_backend(self):
        cli("index", "--topic", "input", "--build", "s4")
        proc, data = cli_json(
            "index", "--topic", "input", "--build", "s4",
            "--mcp", "http://127.0.0.1:9/mcp",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        statuses = {r["status"] for r in data["results"]}
        self.assertEqual(statuses, {"cached"})

    def test_diff_map(self):
        proc, data = cli_json(
            "diff", "ccPlayer::ChangeAction",
            "--from", "s4", "--to", "s4-debug", "--map",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["to"]["rva"], "0x84B2F8")
        self.assertGreater(data["similarity"], 0.0)
        self.assertIsNotNone(data["map"])

    def test_stat_has_phase1_counts(self):
        proc, data = cli_json("stat")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreater(data["bsim_edges"], 0)
        self.assertGreater(data["index_entries"], 0)


if __name__ == "__main__":
    unittest.main()
