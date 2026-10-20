import tempfile
import unittest

from support import add_symbol, decompile_payload, make_db

from storm_re import indexer


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.timeout = 180

    def call_tool(self, name, arguments, timeout=None):
        self.calls += 1
        return self.payload


class IndexerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(self.tmp.name)
        add_symbol(self.db, "s4", 0x100, "ccPlayer::Foo")
        self.db.set_symbol_version("s4")
        self.client = FakeClient(decompile_payload("a\nb\nc\n"))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_index_and_show(self):
        results = indexer.index_topic(
            self.db, self.client, "input", ["ccPlayer::Foo"], ["s4"],
            default_build="s4",
        )
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(self.client.calls, 1)
        rows = indexer.show_entries(self.db, "input")
        self.assertEqual(len(rows), 1)
        self.assertIn("callers=", rows[0]["text"])

    def test_second_run_is_cached(self):
        indexer.index_topic(
            self.db, self.client, "input", ["ccPlayer::Foo"], ["s4"], default_build="s4"
        )
        results = indexer.index_topic(
            self.db, self.client, "input", ["ccPlayer::Foo"], ["s4"], default_build="s4"
        )
        self.assertEqual(results[0]["status"], "cached")
        self.assertEqual(self.client.calls, 1)

    def test_missing_target_is_recorded(self):
        results = indexer.index_topic(
            self.db, self.client, "input", ["NoSuchSymbol"], ["s4"], default_build="s4"
        )
        self.assertEqual(results[0]["status"], "missing")
        rows = indexer.show_entries(self.db, "input")
        self.assertEqual(rows[0]["status"].split(":")[0], "missing")
        self.assertEqual(self.client.calls, 0)


if __name__ == "__main__":
    unittest.main()
