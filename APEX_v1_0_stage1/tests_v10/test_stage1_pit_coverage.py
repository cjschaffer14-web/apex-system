"""Stage 1: point-in-time access, funding accrual at recorded events, and the CoverageGate - on synthetic databases."""
import datetime as dt
import random
import sqlite3
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apex_v10.data import pit, schema                                          # noqa: E402
from apex_v10.data.coverage import CoverageError, discover_families, evaluate, require  # noqa: E402
from apex_v10.data.timeutil import is_business_day                             # noqa: E402
from apex_v10.interfaces import CoverageStatus                                 # noqa: E402

DAY, H = 86400, 3600


def new_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript("CREATE TABLE candles(source TEXT, pair TEXT, interval INTEGER, ts INTEGER, open REAL, high REAL, "
                      "low REAL, close REAL, volume REAL, trades INTEGER); CREATE TABLE readings(source TEXT, metric TEXT, "
                      "ts INTEGER, value REAL); CREATE TABLE imports(sha256 TEXT);")
    schema.apply(con)
    con.execute("INSERT INTO provenance VALUES ('test:0','test','synthetic',0,NULL,NULL,0,NULL)")
    return con


def add_macro(con, sid, obs, pub, value, quality="source_timestamp", source="s"):
    con.execute("INSERT INTO macro_observations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (source, sid, obs, pub, pub, value, "u", None, "0" * 64, quality, "test:0"))


def ts(day: str, hour: int = 0) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp()) + hour * H


class PointInTime(unittest.TestCase):
    def test_macro_asof_respects_publication_and_revisions(self):
        con = new_db()
        d1, d2 = ts("2024-03-04", 16), ts("2024-03-05", 16)
        add_macro(con, "x", d1, d1 + H, 10.0)                       # first print of period 1
        add_macro(con, "x", d2, d2 + H, 20.0)                       # period 2 published before period 1 is revised
        add_macro(con, "x", d1, d2 + 5 * H, 11.0, "approximate")    # revision of period 1
        add_macro(con, "x", d2, d2 + 30 * H, 21.0)                  # revision of period 2
        q = lambda t: (lambda v: v and v.value)(pit.macro_asof(con, "s", "x", t))
        self.assertIsNone(q(d1 + H - 1))                            # nothing is visible before it is published
        self.assertEqual(q(d1 + H), 10.0)
        self.assertEqual(q(d2 + H - 1), 10.0)
        self.assertEqual(q(d2 + H), 20.0)                           # the newer period wins
        self.assertEqual(q(d2 + 6 * H), 20.0)                       # a revision of an older period does not override it
        self.assertEqual(q(d2 + 30 * H - 1), 20.0)
        self.assertEqual(q(d2 + 30 * H), 21.0)                      # the revised vintage, only once published
        self.assertEqual(pit.macro_asof(con, "s", "x", d2 + 6 * H).availability_quality, "source_timestamp")

    def test_macro_series_matches_sql_on_random_revisions(self):
        con = new_db()
        rng = random.Random(7)
        base = ts("2020-01-01")
        rows = set()
        for _ in range(400):
            obs = base + rng.randrange(0, 200) * DAY
            pub = obs + rng.choice([0, H, 5 * H, DAY, 3 * DAY, 40 * DAY])
            if (obs, pub) not in rows:
                rows.add((obs, pub))
                add_macro(con, "r", obs, pub, rng.random())
        ms = pit.MacroSeries(con, "s", "r")
        probes = [base - 1] + [p for _, p in rows] + [p - 1 for _, p in rows] + \
                 [base + rng.randrange(0, 260 * DAY) for _ in range(500)]
        for t in probes:
            a, b = ms.asof(t), pit.macro_asof(con, "s", "r", t)
            self.assertEqual(a, b, t)

    def test_legacy_readings_use_their_lag_rule(self):
        con = new_db()
        d = ts("2024-05-10") // DAY
        for k in range(4):
            con.execute("INSERT INTO readings VALUES ('attention','wiki:Bitcoin',?,?)", (d - k, float(d - k)))
        self.assertEqual(pit.reading_asof(con, "attention", "wiki:Bitcoin", d * DAY + 48 * H - 1)[0], d - 1)
        self.assertEqual(pit.reading_asof(con, "attention", "wiki:Bitcoin", d * DAY + 48 * H)[0], d)
        con.execute("INSERT INTO readings VALUES ('attention','new_metric',?,1.0)", (d,))
        with self.assertRaises(KeyError):                           # no rule, no use
            pit.reading_asof(con, "attention", "new_metric", d * DAY + 10 * DAY)

    def _funding(self):
        con = new_db()
        t0 = ts("2024-01-01")
        ev = [(t0, 0.0001, 28800), (t0 + 8 * H, 0.0001, 28800), (t0 + 16 * H, 0.0002, 28800),
              (t0 + 20 * H, -0.0002, 14400), (t0 + 24 * H, 0.0003, 14400),          # interval changes 8h -> 4h
              (t0 + 32 * H, 0.0001, 14400)]                                          # 28h settlement missing (gap)
        for t, r, i in ev:
            con.execute("INSERT INTO funding_events VALUES ('bitmex','XBTUSD',?,?,?,'source_field','test',NULL,NULL,?,"
                        "'source_timestamp','test:0')", (t, r, i, t))
        return con, t0

    def test_funding_accrues_only_at_recorded_events(self):
        con, t0 = self._funding()
        events = pit.funding_events(con, "bitmex", "XBTUSD", t0, t0 + 40 * H)
        self.assertEqual([e.funding_ts for e in events], [t0 + k * H for k in (8, 16, 20, 24, 32)])   # t0 < ts <= t1
        self.assertEqual([e.interval_s for e in events], [28800, 28800, 14400, 14400, 14400])         # from the data

        def notional(t):                       # long 1000 until 12h, flat 12h-18h, short 500 after
            return 1000.0 if t < t0 + 12 * H else (0.0 if t < t0 + 18 * H else -500.0)

        paid = pit.accrue_funding(events, notional)
        self.assertEqual([t for t, _ in paid], [t0 + 8 * H, t0 + 20 * H, t0 + 24 * H, t0 + 32 * H])  # flat at 16h
        amounts = dict(paid)
        self.assertAlmostEqual(amounts[t0 + 8 * H], 0.1)            # long pays a positive rate
        self.assertAlmostEqual(amounts[t0 + 20 * H], 0.1)           # short pays a negative rate
        self.assertAlmostEqual(amounts[t0 + 24 * H], -0.15)         # short receives a positive rate
        self.assertNotIn(t0 + 28 * H, amounts)                      # a missing settlement is never invented

    def test_position_opened_after_the_settlement_instant_is_not_charged(self):
        con, t0 = self._funding()
        events = pit.funding_events(con, "bitmex", "XBTUSD", t0 - 1, t0 + 8 * H)
        opened_after = pit.accrue_funding(events, lambda t: 1000.0 if t > t0 + 8 * H else 0.0)
        held_through = pit.accrue_funding(events, lambda t: 1000.0 if t >= t0 else 0.0)
        self.assertEqual(opened_after, [])
        self.assertEqual([t for t, _ in held_through], [t0, t0 + 8 * H])


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        con = new_db()
        s = ts("2024-01-01")
        hours = range(0, 30 * 24)
        rows = []
        for pair, keep in (("FULL", lambda h: True), ("LATE", lambda h: h >= 10 * 24), ("SHORT", lambda h: h < 10 * 24),
                           ("HOLES", lambda h: h % 10 != 3)):
            rows += [("t", pair, 60, s + h * H, 1, 1, 1, 1, 1, 1) for h in hours if keep(h)]
        con.executemany("INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        d, end = dt.date(2024, 1, 1), dt.date(2024, 10, 31)
        bdays = []
        while d <= end:
            if is_business_day(d):
                bdays.append(d)
            d += dt.timedelta(days=1)
        for k, day in enumerate(bdays):
            o = ts(day.isoformat(), 16)
            add_macro(con, "good", o, o + H, 1.0)
            add_macro(con, "few_approx", o, o + H, 1.0, "approximate" if k == 50 else "source_timestamp")
            add_macro(con, "many_approx", o, o + H, 1.0, "approximate" if k % 40 == 0 else "conservative_lag")
        cls.con = con
        cls.fam = {f.family: f for f in discover_families(con)}

    def status(self, fam, a, b):
        return evaluate(self.con, self.fam[fam], a, b)

    def test_statuses(self):
        S = CoverageStatus
        self.assertEqual(self.status("candles:t:FULL:60", "2024-01-01", "2024-01-30").status, S.PASS)
        r = self.status("candles:t:LATE:60", "2024-01-01", "2024-01-30")
        self.assertEqual(r.status, S.PARTIAL)
        self.assertIn("starts 2024-01-11", r.reason)
        self.assertEqual(self.status("candles:t:SHORT:60", "2024-01-01", "2024-01-30").status, S.FAIL)
        r = self.status("candles:t:HOLES:60", "2024-01-01", "2024-01-30")
        self.assertEqual(r.status, S.PARTIAL)
        self.assertIn("coverage 90", r.reason)
        r = self.status("candles:t:FULL:60", "2019-01-01", "2019-12-31")
        self.assertEqual((r.status, r.reason), (S.FAIL, "no overlap with the requested window"))
        self.assertEqual(self.status("macro:s:good", "2024-01-01", "2024-10-31").status, S.PASS)
        self.assertEqual(self.status("macro:s:few_approx", "2024-01-01", "2024-10-31").status, S.PASS)   # 1 row < 1%
        r = self.status("macro:s:many_approx", "2024-01-01", "2024-10-31")
        self.assertEqual(r.status, S.PARTIAL)
        self.assertIn("approximate availability timing", r.reason)
        self.assertEqual(r.worst_quality.value, "approximate")

    def test_require_refuses_fail_and_partial_by_default(self):
        with self.assertRaisesRegex(CoverageError, "FAIL"):
            require(self.con, ["candles:t:SHORT:60"], "2024-01-01", "2024-01-30")
        with self.assertRaisesRegex(CoverageError, "PARTIAL"):
            require(self.con, ["candles:t:LATE:60"], "2024-01-01", "2024-01-30")
        with self.assertRaisesRegex(CoverageError, "unknown"):
            require(self.con, ["candles:t:NOPE:60"], "2024-01-01", "2024-01-30")
        ok = require(self.con, ["candles:t:FULL:60"], "2024-01-01", "2024-01-30")
        self.assertEqual((ok["window"], ok["ablated"]), (["2024-01-01", "2024-01-30"], []))

    def test_require_named_ablation(self):
        d = require(self.con, ["candles:t:FULL:60", "candles:t:SHORT:60"], "2024-01-01", "2024-01-30", ablate_on_fail=True)
        self.assertEqual(d["ablated"], ["candles:t:SHORT:60"])
        d = require(self.con, ["candles:t:FULL:60", "candles:t:LATE:60"], "2024-01-01", "2024-01-30", on_partial="ablate")
        self.assertEqual(d["ablated"], ["candles:t:LATE:60"])
        self.assertEqual(d["window"], ["2024-01-01", "2024-01-30"])

    def test_require_shortens_only_when_the_shorter_window_passes(self):
        d = require(self.con, ["candles:t:FULL:60", "candles:t:LATE:60"], "2024-01-01", "2024-01-30", on_partial="shorten")
        self.assertTrue(d["shortened"])
        self.assertEqual(d["window"], ["2024-01-11", "2024-01-30"])
        self.assertEqual({v["shortened_status"] for v in d["families"].values()}, {"PASS"})
        with self.assertRaisesRegex(CoverageError, "still PARTIAL"):             # holes cannot be shortened away
            require(self.con, ["candles:t:HOLES:60"], "2024-01-01", "2024-01-30", on_partial="shorten")
        d = require(self.con, ["candles:t:FULL:60", "candles:t:SHORT:60"], "2024-01-01", "2024-01-30", on_fail="shorten")
        self.assertEqual(d["window"], ["2024-01-01", "2024-01-10"])               # a FAIL family may also shorten
        with self.assertRaisesRegex(CoverageError, "cannot be shortened"):        # but not when it has no data inside
            require(self.con, ["candles:t:FULL:60"], "2019-01-01", "2019-12-31", on_fail="shorten")
        with self.assertRaisesRegex(CoverageError, "still PARTIAL"):             # nor can approximate timing
            require(self.con, ["macro:s:many_approx"], "2024-01-01", "2024-10-31", on_partial="shorten")


if __name__ == "__main__":
    unittest.main()
