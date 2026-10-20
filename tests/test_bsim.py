import pathlib
import tempfile
import unittest

from support import make_db

from storm_re import bsim


TSV = """0x100\tFUN_100\t_NSUNS4_debug_1.06.exe-test\t0x140000200\tFUN_140000200\t0.9000\t10.0
0x100\tFUN_100\t_NSUNS4_debug_1.06.exe-test\t0x140000300\tFUN_140000300\t0.7000\t9.0
0x100\tFUN_100\t_main-69612a\t0x7100000900\tccPlayer::Foo\t0.5000\t8.0
0x200\tFUN_200\t_NSUNS4_debug_1.06.exe-test\t0x140000400\tFUN_140000400\t0.4000\t7.0
0x300\tFUN_300\t_main-69612a\t0x7100000901\tccPlayer::Bar\t0.9500\t11.0
0x400\tFUN_400\t_JJASBR.exe\t0x140000500\tFUN_140000500\t0.9900\t12.0
"""


class BSimTests(unittest.TestCase):
    def test_build_from_path(self):
        self.assertEqual(bsim.build_from_path("_NSUNS4_release.exe-x.bsim.tsv"), "s4")
        self.assertEqual(bsim.build_from_path("_NSUNS4_debug_1.06.exe-x.bsim.tsv"), "s4-debug")
        self.assertEqual(bsim.build_from_path("NSUNS1.exe-x.bsim.tsv"), "s1")
        self.assertEqual(bsim.build_from_path("NSUNS1_debug.exe-x.bsim.tsv"), "s1-debug")
        self.assertIsNone(bsim.build_from_path("JJASBR_vs_full.bsim.tsv"))
        self.assertIsNone(bsim.build_from_path("NSUNS2_X360_0902.bsim.tsv"))

    def test_normalize_target_exe(self):
        self.assertEqual(bsim.normalize_target_exe("_NSUNS4_debug_1.06.exe-x"), "s4-debug")
        self.assertEqual(bsim.normalize_target_exe("_main-69612a"), "trilogy")
        self.assertEqual(bsim.normalize_target_exe("_NSUNS1.exe-x"), "s1")
        self.assertIsNone(bsim.normalize_target_exe("_JJASBR.exe"))

    def test_parse_topk_and_rva(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "x.tsv"
            path.write_text(TSV)
            bases = {"s4-debug": 0x140000000, "trilogy": 0x7100000000}
            rows, read, unknown = bsim.parse_tsv(path, "s4", bases, top_k=2, min_sim=0.5)
        self.assertEqual(read, 6)
        self.assertEqual(unknown, 1)
        by_rva = {}
        for r in rows:
            by_rva.setdefault(r[0], []).append(r)
        self.assertEqual(len(by_rva[0x100]), 2)  # top 2, trilogy 0.5 dropped
        self.assertEqual(by_rva[0x100][0][3], 0x200)  # normalized RVA
        self.assertEqual(by_rva[0x300][0][3], 0x901)
        self.assertNotIn(0x200, by_rva)  # below min_sim

    def test_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "_NSUNS4_release.exe-test.bsim.tsv").write_text(TSV)
            db = make_db(tmp)
            result = bsim.ingest(db, root, quiet=True)
            self.assertGreater(result["edges"], 0)
            self.assertEqual(result["skipped"], [])
            self.assertEqual(db.bsim_count(), result["edges"])
            db.close()


if __name__ == "__main__":
    unittest.main()
