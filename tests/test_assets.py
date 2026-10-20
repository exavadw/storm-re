import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import make_db

from storm_re import assets


def xfbin(chunks: list[tuple[str, str, str]]) -> bytes:
    """Minimal NUCC file laid out like the game's (chunk table at 0x1C, strings at 0x44)."""
    types = ["nuccChunkNull"] + sorted({c[0] for c in chunks})
    paths = [""] + sorted({c[1] for c in chunks})
    names = [""] + sorted({c[2] for c in chunks})
    maps = [(0, 0, 0)] + [(types.index(t), paths.index(p), names.index(n)) for t, p, n in chunks]
    blob = lambda xs: b"".join(x.encode() + b"\0" for x in xs)  # noqa: E731
    tb, pb, nb = blob(types), blob(paths), blob(names)
    head = b"NUCC" + struct.pack(">I", 0x79) + b"\0" * 8 + struct.pack(">II", 0xE4, 3) + b"\0" * 4
    table = struct.pack(">10I", len(types), len(tb), len(paths), len(pb), len(names), len(nb),
                        len(maps), 12 * len(maps), len(maps), 0)
    body = head + table + tb + pb + nb
    body += b"\0" * (-len(body) % 4)
    return body + b"".join(struct.pack(">3I", *m) for m in maps)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ext"
        files = {
            "storm4/data/sim/data2/data/spc/1nrtbod1.xfbin": xfbin([
                ("nuccChunkClump", "c/1nrt/bod1.max", "1nrtbod1"),
                ("nuccChunkTexture", "c/1nrt/tex.nut", "1nrt_tex"),
            ]),
            # patch archive whose dir is a prefix-sibling of data2: must not swallow it
            "storm4/data/patch/12/data/data/spc/1nrtbod1.xfbin": b"NUCC" + b"\0" * 8,
            "storm4/data/launch/sound/data/sound/PC/bgm.awb": b"AFS2" + b"\0" * 20,
            "storm1/data/sim/data/data/spc/1nrtbod1.xfbin": b"NUCC" + b"\0" * 60,
            "stormgen/data/system/loose.bin": b"\x01\x02\x03\x04",
        }
        for rel, data in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.root / "CPKS.tsv").write_text(
            "game\tcpk\n"
            "storm4\tdata/sim/data2.cpk\nstorm4\tdata/patch/12/data.cpk\n"
            "storm4\tdata/launch/sound.cpk\nstorm1\tdata/sim/data.cpk\n"
            "stormgen\tdata/cpk/dataCmn.cpk\n"
        )
        self.env = mock.patch.dict(os.environ, {"STORM_RE_ASSETS": str(self.root),
                                                "STORM_RE_ASSETS_WIN": r"F:\x"})
        self.env.start()
        self.db = make_db(self.tmp.name)
        self.result = assets.index(self.db, self.root)

    def tearDown(self):
        self.env.stop()
        self.db.conn.close()
        self.tmp.cleanup()

    def test_entries_are_attributed_to_their_archive(self):
        rows = {r["rel"]: r for r in map(dict, self.db.conn.execute("SELECT * FROM asset"))}
        r = rows["data/sim/data2/data/spc/1nrtbod1.xfbin"]
        self.assertEqual((r["cpk"], r["entry"]), ("data/sim/data2.cpk", "data/spc/1nrtbod1.xfbin"))
        r = rows["data/patch/12/data/data/spc/1nrtbod1.xfbin"]
        self.assertEqual((r["cpk"], r["entry"]), ("data/patch/12/data.cpk", "data/spc/1nrtbod1.xfbin"))
        # disc files outside every listed archive stay loose, path unchanged
        r = rows["data/system/loose.bin"]
        self.assertEqual((r["cpk"], r["entry"]), ("", "data/system/loose.bin"))
        self.assertEqual(self.result["files"], 5)

    def test_reindex_one_game_keeps_others(self):
        assets.index(self.db, self.root, ["storm1"])
        n = self.db.conn.execute("SELECT COUNT(*) FROM asset").fetchone()[0]
        self.assertEqual(n, 5)

    def test_find_substring_glob_and_filters(self):
        self.assertEqual(assets.find(self.db, "1NRTBOD1")["total"], 3)
        self.assertEqual(assets.find(self.db, "1nrtbod1", game="s4")["total"], 2)
        self.assertEqual(assets.find(self.db, "*.awb")["total"], 1)
        self.assertEqual(assets.find(self.db, "1nrt", cpk="patch")["total"], 1)
        hit = assets.find(self.db, "bgm", ext="awb")["results"][0]
        self.assertEqual(hit["magic"], "AFS2")
        self.assertEqual(hit["win_path"], r"F:\x\storm4\data\launch\sound\data\sound\PC\bgm.awb")

    def test_info_lists_xfbin_chunks_and_other_games(self):
        out = assets.info(self.db, "storm4", "data/sim/data2/data/spc/1nrtbod1.xfbin")
        self.assertEqual(out["xfbin"]["chunk_count"], 2)
        self.assertIn({"type": "nuccChunkClump", "path": "c/1nrt/bod1.max", "name": "1nrtbod1"},
                      out["xfbin"]["chunks"])
        self.assertEqual([o["game"] for o in out["other_games"]], ["storm1"])
        self.assertFalse(out["other_games"][0]["same_size"])

    def test_info_entry_path_ambiguous_across_archives(self):
        # same entry in data2.cpk and the patch archive: caller must pick one
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            assets.info(self.db, "storm4", "data/spc/1nrtbod1.xfbin")
        out = assets.info(self.db, "storm1", "data/spc/1nrtbod1.xfbin")
        self.assertEqual(out["cpk"], "data/sim/data.cpk")

    def test_summary_groups_by_archive(self):
        s = assets.summary(self.db)
        self.assertEqual(s["games"]["storm4"]["files"], 3)
        self.assertIn("(loose)", [c["cpk"] for c in s["games"]["stormgen"]["cpks"]])


if __name__ == "__main__":
    unittest.main()
