import tempfile
import unittest

from support import add_symbol, decompile_payload, make_db

from storm_re.summarize import summarize


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::ChangeAction")
        self.version = self.db.set_symbol_version("s4")
        self.raw = decompile_payload("void f() { return; }")
        self.summary = summarize(self.raw)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _put(self, version):
        self.db.cache_put(
            "a" * 64, 0x7AB468, "decompile", "v1", version,
            self.raw, self.summary, self.summary["raw_chars"], self.summary["summary_chars"],
        )

    def test_roundtrip(self):
        self._put(self.version)
        hit = self.db.cache_get("a" * 64, 0x7AB468, "decompile", "v1", self.version)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["raw"]["code"], self.raw["code"])
        self.assertEqual(hit["hit_count"], 1)

    def test_hit_count_increments(self):
        self._put(self.version)
        self.db.cache_get("a" * 64, 0x7AB468, "decompile", "v1", self.version)
        hit = self.db.cache_get("a" * 64, 0x7AB468, "decompile", "v1", self.version)
        self.assertEqual(hit["hit_count"], 2)

    def test_name_version_invalidates(self):
        self._put(self.version)
        add_symbol(self.db, "s4", 0x7AB468, "ccPlayer::Renamed", source="manual")
        new_version = self.db.set_symbol_version("s4")
        self.assertNotEqual(new_version, self.version)
        self.assertIsNone(
            self.db.cache_get("a" * 64, 0x7AB468, "decompile", "v1", new_version)
        )

    def test_clear(self):
        self._put(self.version)
        self.assertEqual(self.db.cache_clear("a" * 64), 1)
        self.assertIsNone(
            self.db.cache_get("a" * 64, 0x7AB468, "decompile", "v1", self.version)
        )


if __name__ == "__main__":
    unittest.main()
