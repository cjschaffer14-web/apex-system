"""Stage 1: every source adapter, offline, against recorded-shape fixtures."""
import datetime as dt
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from apex_v10.data import schema                                   # noqa: E402
from apex_v10.data.archive import RawArchive                       # noqa: E402
from apex_v10.data.sources import funding as F, macro as M         # noqa: E402
from apex_v10.data.sources.common import FUNDING_COLUMNS, MACRO_COLUMNS  # noqa: E402
from apex_v10.data.timeutil import et_ts                           # noqa: E402
from fixtures import fake_sources as fx                            # noqa: E402

ASOF = int(dt.datetime(2026, 10, 3, 2, 0, tzinfo=dt.timezone.utc).timestamp())


class Adapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        b = fx.FakeArchiveBuilder(Path(cls.tmp.name) / "raw")
        fx.bitmex(b, ASOF)
        cls.deribit_start = ASOF - 40 * 86400
        fx.deribit(b, ASOF, cls.deribit_start)
        fx.kraken(b, ASOF)
        fx.intx(b, ASOF)
        fx.h41(b)
        fx.nyfed(b, ASOF)
        fx.tga(b)
        fx.yields(b, 2026)
        fx.vix(b)
        b.close()
        cls.ar = RawArchive(Path(cls.tmp.name) / "raw", mode="raw")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assertRows(self, rows, ncols):
        for r in rows:
            self.assertIsInstance(r, tuple)                       # never a set or list (the v1.0 migration bug)
            self.assertEqual(len(r), ncols)

    def test_bitmex_uses_recorded_interval_and_as_of(self):
        r = F.bitmex(self.ar, ASOF, "raw")
        self.assertRows(r.funding, len(FUNDING_COLUMNS))
        xbt = [x for x in r.funding if x[1] == "XBTUSD"]
        self.assertEqual(xbt[0][4], 86400)                        # first event: 24-hour interval
        self.assertEqual(xbt[1][4], 28800)                        # then 8 hours, from the source field
        self.assertTrue(all(x[2] <= ASOF for x in r.funding))     # nothing after the as-of time
        self.assertTrue(all(x[10] == "source_timestamp" and x[9] == x[2] for x in r.funding))

    def test_deribit_dedupes_and_labels_semantics(self):
        r = F.deribit(self.ar, ASOF, "raw", start_ts=self.deribit_start)
        keys = [(x[1], x[2]) for x in r.funding]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("continuous", r.funding[0][6])
        self.assertTrue(r.notes)

    def test_kraken_and_intx_derive_spacing(self):
        k = F.kraken_futures(self.ar, ASOF, "raw")
        xbt = [x for x in k.funding if x[1] == "PF_XBTUSD"]
        self.assertEqual([x[4] for x in xbt], [None, 3600, 7200, 3600])   # 2h gap visible; future event dropped
        i = F.coinbase_intx(self.ar, ASOF, "raw")
        btc = [x for x in i.funding if x[1] == "BTC-PERP"]
        self.assertEqual([x[2] for x in btc], sorted(x[2] for x in btc))
        self.assertEqual(btc[0][7], 50000.0)                      # mark price kept

    def test_h41_release_calendar_handles_holiday(self):
        r = M.fed_h41(self.ar, ASOF, "raw")
        self.assertRows(r.macro, len(MACRO_COLUMNS))
        pub = {row[2]: row[3] for row in r.macro}
        wed1 = et_ts(dt.date(2024, 7, 4), 0, 0)                   # end of Wednesday 3 July
        self.assertEqual(pub[wed1], et_ts(dt.date(2024, 7, 5), 16, 30))   # Friday, after the 4 July holiday
        self.assertEqual(len(r.macro), 2)                         # 17 July has no proven release: not ingested
        self.assertTrue(all(x[9] == "exact_release" for x in r.macro))

    def test_nyfed_late_edits_are_flagged(self):
        r = M.nyfed_rrp(self.ar, ASOF, "raw")
        q = {dt.datetime.fromtimestamp(x[2], dt.timezone.utc).date().isoformat(): (x[9], x[5]) for x in r.macro}
        self.assertEqual(q["2015-03-02"][0], "approximate")      # record edited on 2015-12-05
        self.assertEqual(q["2024-07-01"], ("source_timestamp", 401000000000.0))   # two operations summed

    def test_tga_layouts_spliced_only_when_seams_match(self):
        r = M.treasury_tga(self.ar, ASOF, "raw")
        vals = {dt.datetime.fromtimestamp(x[2], dt.timezone.utc).date().isoformat(): x[5] for x in r.macro}
        self.assertEqual(vals["2021-10-01"], 215160e6)            # 30 Sep close (layout 1)
        self.assertEqual(vals["2022-04-19"], 841253e6)            # 18 Apr close (layout 3, 'today' column)
        self.assertTrue(all(x[9] == "conservative_lag" for x in r.macro))
        with tempfile.TemporaryDirectory() as d:
            b = fx.FakeArchiveBuilder(Path(d))
            fx.tga(b, seam_ok=False)
            b.close()
            with self.assertRaisesRegex(ValueError, "seam"):
                M.treasury_tga(RawArchive(Path(d), mode="raw"), ASOF, "raw")

    def test_yields_and_vix(self):
        y = M.treasury_yields(self.ar, ASOF, "raw", start_year=2026)
        self.assertEqual(len([x for x in y.macro if x[1] == "par_yield_2y"]), 1)    # N/A skipped
        self.assertEqual(len([x for x in y.macro if x[1] == "par_yield_10y"]), 2)
        v = M.cboe_vix(self.ar, ASOF, "raw")
        self.assertEqual(len(v.macro), 2)                         # 2013 row before START_DATE dropped
        self.assertTrue(all(x[3] - x[2] == 45 * 60 for x in v.macro))

    def test_rows_insert_into_the_schema(self):
        con = sqlite3.connect(":memory:")
        self.addCleanup(con.close)
        con.executescript("CREATE TABLE candles(source TEXT, pair TEXT, interval INTEGER, ts INTEGER, open REAL, high REAL, "
                          "low REAL, close REAL, volume REAL, trades INTEGER); CREATE TABLE readings(source TEXT, metric TEXT, "
                          "ts INTEGER, value REAL); CREATE TABLE imports(sha256 TEXT);")
        schema.apply(con)
        from apex_v10.data.build import _insert
        for fn in (F.bitmex, F.kraken_futures, M.fed_h41, M.nyfed_rrp):
            _insert(con, fn(self.ar, ASOF, "raw"))
        self.assertGreater(con.execute("SELECT COUNT(*) FROM funding_events").fetchone()[0], 0)
        with self.assertRaises(sqlite3.IntegrityError):           # a bad quality tag is refused by the schema
            con.execute("INSERT INTO macro_observations VALUES ('s','x',1,2,3,1.0,'u',NULL,'h','guess','p')")
        with self.assertRaises(sqlite3.IntegrityError):           # published before observed is refused
            con.execute("INSERT INTO macro_observations VALUES ('s','x',5,2,3,1.0,'u',NULL,'h','approximate','p')")

    def test_raw_archive_detects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            b = fx.FakeArchiveBuilder(Path(d))
            fx.vix(b)
            b.close()
            p = next((Path(d) / "cboe").glob("*.gz"))
            from apex_v10.data.archive import gzip_deterministic
            p.write_bytes(gzip_deterministic(b"tampered"))
            with self.assertRaisesRegex(ValueError, "corrupted"):
                M.cboe_vix(RawArchive(Path(d), mode="raw"), ASOF, "raw")


if __name__ == "__main__":
    unittest.main()
