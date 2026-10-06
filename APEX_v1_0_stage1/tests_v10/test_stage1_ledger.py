"""Stage 1: the trial ledger, its stored return series, and the reconstruction reconciliation.

Counts are checked against the frozen artifacts independently of the ledger builder."""
import csv
import hashlib
import json
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apex_v10.interfaces import ReturnsStatus, TrialKind, TrialStatus     # noqa: E402
from apex_v10.ledger.io import equivalence_id, iter_ledger, read_returns, roundtrip_ok  # noqa: E402

LEDGER = ROOT / "ledger/trial_ledger.jsonl"
SUMMARY = ROOT / "ledger/LEDGER_SUMMARY.json"
RECON = ROOT / "reports/reconstruction_reconciliation.json"
RES = ROOT / "baseline_v09/results"
FROZEN_VERSIONS = {"v0.6", "v0.7-nn", "v0.8", "v0.9"}


@unittest.skipUnless(LEDGER.exists() and SUMMARY.exists() and RECON.exists(), "run scripts/build_stage1.py first")
class Ledger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = list(iter_ledger(LEDGER))            # validates every line as a TrialRecord
        cls.recs = [r for _, r in cls.pairs]
        cls.by_id = {r.trial_id: r for r in cls.recs}
        cls.summary = json.loads(SUMMARY.read_text())
        cls.recon = json.loads(RECON.read_text())

    def count(self, **kw):
        return sum(1 for r in self.recs if all(getattr(r, k) == v for k, v in kw.items()))

    def test_lines_round_trip_exactly(self):
        for line, rec in self.pairs:
            self.assertTrue(roundtrip_ok(line, rec), rec.trial_id)

    def test_ids_and_identities_are_unique(self):
        self.assertEqual(len(self.by_id), len(self.recs))
        idents = Counter(r.identity_sha256() for r in self.recs)
        self.assertEqual([k for k, n in idents.items() if n > 1], [])

    def test_summary_matches_the_file(self):
        s = self.summary
        self.assertEqual(hashlib.sha256(LEDGER.read_bytes()).hexdigest(), s["ledger_sha256"])
        self.assertEqual(s["records"], len(self.recs))
        self.assertEqual(s["by_kind"], dict(Counter(r.kind.value for r in self.recs)))
        self.assertEqual(s["by_returns_status"], dict(Counter(r.returns_status.value for r in self.recs)))
        # the conservative DSR count is every viewed real-data trial; nothing is netted out
        self.assertEqual(s["n_conservative_all_viewed_real_data_trials"],
                         sum(1 for r in self.recs if r.real_data and r.viewed_before_later_choice))
        self.assertEqual(s["n_conservative_all_viewed_real_data_trials"], len(self.recs))
        self.assertGreater(s["dependence_diagnostic"]["participation_ratio"], 1)

    def test_sensitivities_point_to_real_parents(self):
        n = 0
        for r in self.recs:
            if r.kind == TrialKind.SENSITIVITY:
                p = self.by_id.get(r.parent_trial_id)
                self.assertIsNotNone(p, r.trial_id)
                self.assertEqual((p.family, p.asset), (r.family, r.asset), r.trial_id)
                self.assertNotEqual(p.kind, TrialKind.SENSITIVITY)
                n += 1
        self.assertEqual(n, self.summary["by_kind"]["sensitivity"])

    def test_stored_series_match_their_hashes_and_equivalence_ids(self):
        for r in self.recs:
            if r.returns_status == ReturnsStatus.STORED:
                ts, ret = read_returns(ROOT, r)            # raises on a file hash mismatch
                self.assertTrue(ts, r.trial_id)
                self.assertEqual(equivalence_id(ts, ret), r.return_equivalence_id, r.trial_id)
                self.assertIn(r.returns_frequency, ("daily", "event"))
            elif r.returns_status == ReturnsStatus.RECONSTRUCTABLE:
                self.assertTrue(r.returns_ref and r.returns_ref.startswith("derived:"), r.trial_id)
            else:
                self.assertIsNone(r.returns_sha256)
                self.assertIsNone(r.return_equivalence_id)

    def test_no_orphan_return_files(self):
        used = {r.returns_ref.partition("#")[0] for r in self.recs if r.returns_status == ReturnsStatus.STORED}
        files = {p.relative_to(ROOT).as_posix() for p in (ROOT / "ledger/returns").glob("*.csv.gz")}
        self.assertEqual(files, used)

    def test_identical_paths_stay_distinct_trials(self):
        a, b = self.by_id["v0.6|BTC-USD|T11_elliott_soft_wave4|25bps"], self.by_id["v0.6|BTC-USD|T12_named_fibonacci|25bps"]
        self.assertNotEqual(a.identity_sha256(), b.identity_sha256())
        self.assertEqual(a.return_equivalence_id, b.return_equivalence_id)
        h6, h9 = self.by_id["v0.6|BTC-USD|hold|25bps"], self.by_id["v0.9|BTC-USD|hold_long|25bps"]
        self.assertEqual(h6.return_equivalence_id, h9.return_equivalence_id)
        groups = defaultdict(set)
        for r in self.recs:
            if r.return_equivalence_id:
                groups[r.return_equivalence_id].add(r.trial_id)
        self.assertEqual(len(groups), self.summary["return_equivalence"]["classes"])

    def test_counts_match_the_frozen_artifacts(self):
        hist = json.loads((RES / "historical_v09_results.json").read_text())
        for pair, slug in (("BTC-USD", "btc"), ("ETH-USD", "eth")):
            v06 = json.loads((RES / f"{slug}_v06_historical_25bps.json").read_text())
            self.assertEqual(self.count(source_version="v0.6", asset=pair),
                             len(v06["runs"]) + v06["controls"]["T12_fibonacci_placebo"]["n"])
            v08 = json.loads((RES / f"{slug}_real_v08_25bps.json").read_text())
            self.assertEqual(self.count(source_version="v0.8", asset=pair), len(v08["runs"]))
            cr = hist[pair]["cost_runs"]
            self.assertEqual(self.count(family="v09.expert", asset=pair), sum(len(c["experts"]) for c in cr.values()))
            self.assertEqual(self.count(family="v09.mixture", asset=pair), 2 * len(cr))
            self.assertEqual(self.count(family="v09.conditional_expert_state", asset=pair),
                             sum(len(c["conditional"]) for c in cr.values()))
            self.assertEqual(self.count(family="v09.geometry_target_cell", asset=pair), len(hist[pair]["geometry"]["summary"]))
            with open(RES / "state_forward_distributions.csv") as fh:
                sf = [r for r in csv.DictReader(fh) if r["pair"] == pair]
            self.assertEqual(self.count(family="v09.state_forward_distribution", asset=pair), len(sf))
        self.assertEqual(self.count(family="v09.matrix_kelly_pair"), len(hist["matrix_kelly_25bps"]["rows"]))

    def test_apex_v05_history_imported(self):
        ev = json.loads((ROOT / "data_v10/imports/apex_v05/apex_ledger_extract.json").read_text())["events"]
        refs = {ref for r in self.recs for ref in r.artifact_refs}
        trials = [e for e in ev if e["event_type"] == "ResearchTrial"]
        hyps = [e for e in ev if e["event_type"] == "HypothesisTested"]
        self.assertEqual(len({e["payload"]["name"] for e in trials}), 14)     # 14 governed trials, each run twice
        self.assertEqual(len(trials), 28)
        self.assertEqual(len(hyps), 22)
        for e in trials + hyps:
            self.assertIn(f"data_v10/imports/apex_v05/apex_ledger_extract.json#{e['event_id']}", refs)
        self.assertEqual(sum(1 for r in self.recs if r.family.startswith("apex.research_v05.")), 14)
        self.assertEqual(sum(1 for r in self.recs if r.family.startswith("apex.hypothesis.")), 22)
        for r in self.recs:
            for ref in r.artifact_refs:
                self.assertTrue((ROOT / ref.partition("#")[0]).exists(), ref)

    def test_controls_failures_and_sensitivities_retained(self):
        self.assertEqual(self.by_id["adhoc-2026-10-02|BTC-USD|six_cycle_calendar_checks"].status, TrialStatus.FAILED)
        self.assertEqual(self.count(family="v06.T12", kind=TrialKind.CONTROL), 100)
        self.assertGreater(self.count(kind=TrialKind.SENSITIVITY), 0)

    def test_reconstruction_reconciles(self):
        self.assertEqual(self.recon["failed"], [])
        self.assertEqual(self.recon["checks"], self.recon["passed"])
        ok = {row["trial_id"] for row in self.recon["rows"] if row["pass"]}
        for r in self.recs:
            if r.source_version in FROZEN_VERSIONS and r.returns_status != ReturnsStatus.UNAVAILABLE:
                self.assertIn(r.trial_id, ok, r.trial_id)


if __name__ == "__main__":
    unittest.main()
