"""Stage 2 step 6: macro and source vintage admissibility audit (read-only, fail-closed).

Pins the vintage decisions accepted in the Stage 1A review so no Stage 2 change can silently widen the evidence set:
  - TGA stays `unverified`, so no TGA row is evidence-grade until first-print Daily Treasury Statements are sourced.
  - The 497 NY Fed RRP rows edited after release stay excluded row by row.
  - Market records (candles, exchange funding, Treasury par yields, CBOE VIX) keep provenance on every row.
  - The evidence vintage/timing sets are exactly the ones the review accepted.
Nothing here writes to the database; it is opened read-only.
"""
from __future__ import annotations
import json, sqlite3, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apex_v10.interfaces_1a import EVIDENCE_TIMING, EVIDENCE_VINTAGES, is_evidence_grade  # noqa: E402


def _connect():
    man = json.loads((ROOT / 'data_v10/DB_MANIFEST_1A.json').read_text())
    return sqlite3.connect(f"file:{ROOT / man['file']}?mode=ro", uri=True)


class EvidenceSets(unittest.TestCase):
    def test_evidence_sets_are_exactly_the_reviewed_ones(self):
        self.assertEqual({v.value for v in EVIDENCE_VINTAGES},
                         {'first_release', 'unrevised_since_release', 'market_record'})
        self.assertEqual({t.value for t in EVIDENCE_TIMING},
                         {'exact_release', 'source_timestamp', 'conservative_lag'})

    def test_excluded_vintages_never_pass(self):
        for v in ('latest_vintage', 'edited_after_release', 'unverified'):
            for t in ('exact_release', 'source_timestamp', 'conservative_lag', 'approximate'):
                self.assertFalse(is_evidence_grade(t, v), (t, v))


class MacroVintages(unittest.TestCase):
    def setUp(self):
        self.con = _connect()

    def tearDown(self):
        self.con.close()

    def _grades(self, source):
        return [(t, v, n) for t, v, n in self.con.execute(
            'select availability_quality, value_vintage_quality, count(*) from macro_observations '
            'where source=? group by 1, 2', (source,))]

    def test_tga_unverified_and_excluded(self):
        rows = self._grades('treasury_fiscaldata')
        self.assertTrue(rows)
        self.assertEqual({v for _, v, _ in rows}, {'unverified'})
        self.assertFalse(any(is_evidence_grade(t, v) for t, v, _ in rows))
        policy = self.con.execute("select value_vintage_quality from vintage_policy "
                                  "where family='macro:treasury_fiscaldata:tga_closing_balance'").fetchone()[0]
        self.assertEqual(policy, 'unverified')

    def test_rrp_edited_rows_excluded_row_wise(self):
        rows = self._grades('nyfed')
        edited = [(t, v, n) for t, v, n in rows if v == 'edited_after_release']
        self.assertEqual(sum(n for *_, n in edited), 497)
        self.assertFalse(any(is_evidence_grade(t, v) for t, v, _ in edited))
        # The rest of RRP stays usable; only the edited rows drop out.
        kept = [(t, v, n) for t, v, n in rows if v != 'edited_after_release']
        self.assertTrue(kept and all(is_evidence_grade(t, v) for t, v, _ in kept))

    def test_market_records_are_evidence_grade_and_carry_provenance(self):
        for source in ('treasury_yields', 'cboe'):
            rows = self._grades(source)
            self.assertEqual({v for _, v, _ in rows}, {'market_record'}, source)
            self.assertTrue(all(is_evidence_grade(t, v) for t, v, _ in rows), source)
        for table in ('macro_observations', 'funding_events'):
            orphans = self.con.execute(
                f'select count(*) from {table} t left join provenance p using(provenance_id) '
                'where t.provenance_id is null or p.provenance_id is null').fetchone()[0]
            self.assertEqual(orphans, 0, table)
        self.assertEqual({r[0] for r in self.con.execute('select distinct value_vintage_quality from funding_events')},
                         {'market_record'})


if __name__ == '__main__':
    unittest.main()
