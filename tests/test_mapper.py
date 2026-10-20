import tempfile
import unittest

from support import add_symbol, make_db

from storm_re.mapper import confidence_for, map_all, map_name
from storm_re.text import fmt_addr


def edge(rva, target_build, target_rva, sim, name="FUN"):
    return (rva, f"_{target_build}.exe-test", target_build, target_rva, name, sim, 10.0)


class MapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x100, "ccPlayer::Direct")
        add_symbol(self.db, "s4", 0x110, "ccPlayer::Trilogy")
        add_symbol(self.db, "s4", 0x120, "ccPlayer::Named")
        add_symbol(self.db, "s4", 0x130, "ccPlayer::RvaOnly")
        add_symbol(self.db, "s4-debug", 0x320, "ccPlayer::Named")
        add_symbol(self.db, "s4-debug", 0x130, "Other::SameRva")
        self.db.set_symbol_version("s4")
        self.db.set_symbol_version("s4-debug")
        self.db.set_symbol_version("s4-107")

        self.db.bsim_replace(
            "s4",
            [
                edge(0x100, "s4-debug", 0x300, 0.80),
                edge(0x110, "trilogy", 0x900, 0.90),
            ],
        )
        self.db.bsim_replace(
            "s4-debug",
            [edge(0x310, "trilogy", 0x900, 0.85)],
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_direct(self):
        m = map_name(self.db, "ccPlayer::Direct", "s4", "s4-debug")
        self.assertEqual(m.to_rva, 0x300)
        self.assertEqual(m.method, "bsim-direct")
        self.assertEqual(m.confidence, "medium")
        self.assertAlmostEqual(m.score, 0.80)

    def test_trilogy_mediation(self):
        m = map_name(self.db, "ccPlayer::Trilogy", "s4", "s4-debug")
        self.assertEqual(m.to_rva, 0x310)
        self.assertEqual(m.method, "bsim-trilogy")
        self.assertAlmostEqual(m.score, 0.85)

    def test_name_fallback(self):
        m = map_name(self.db, "ccPlayer::Named", "s4", "s4-debug")
        self.assertEqual(m.to_rva, 0x320)
        self.assertEqual(m.method, "name")
        self.assertEqual(m.confidence, "high")

    def test_name_beats_trilogy_false_positive(self):
        add_symbol(self.db, "s4", 0x140, "ccPlayer::NamedTrilogy")
        add_symbol(self.db, "s4-debug", 0x340, "ccPlayer::NamedTrilogy")
        self.db.bsim_replace("s4", [edge(0x140, "trilogy", 0x910, 1.0)])
        self.db.bsim_replace("s4-debug", [edge(0x350, "trilogy", 0x910, 1.0)])
        m = map_name(self.db, "ccPlayer::NamedTrilogy", "s4", "s4-debug")
        self.assertEqual(m.to_rva, 0x340)
        self.assertEqual(m.method, "name")

    def test_address_input_uses_resolved_name(self):
        m = map_name(self.db, "0x120", "s4", "s4-debug")
        self.assertEqual(m.to_rva, 0x320)
        self.assertEqual(m.method, "name")

    def test_rva_fallback(self):
        m = map_name(self.db, "ccPlayer::RvaOnly", "s4", "s4-debug")
        self.assertEqual(m.to_rva, 0x130)
        self.assertEqual(m.method, "rva")
        self.assertEqual(m.confidence, "low")

    def test_cache_and_refresh(self):
        first = map_name(self.db, "ccPlayer::Direct", "s4", "s4-debug")
        self.db.bsim_replace("s4", [])
        cached = map_name(self.db, "ccPlayer::Direct", "s4", "s4-debug")
        self.assertEqual(cached.to_rva, first.to_rva)
        refreshed = map_name(self.db, "ccPlayer::Direct", "s4", "s4-debug", refresh=True)
        # No edges, no same name, no symbol at 0x100 in debug -> no candidate.
        self.assertIsNone(refreshed)

    def test_map_all(self):
        results, missing = map_all(self.db, "ccPlayer::Direct", "s4")
        builds = {r.to_build for r in results}
        self.assertIn("s4-debug", builds)
        self.assertIn("s4-107", missing)

    def test_confidence(self):
        self.assertEqual(confidence_for(0.9), "high")
        self.assertEqual(confidence_for(0.7), "medium")
        self.assertEqual(confidence_for(0.4), "low")


if __name__ == "__main__":
    unittest.main()
