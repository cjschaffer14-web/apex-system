"""Contract tests for apex_v10.interfaces (Stage 0 contracts + the four Stage 0 review amendments)."""
import dataclasses
import math
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex_v10 import interfaces as I  # noqa: E402

H = "a" * 64
T = 1790899200                           # 2026-10-02 00:00 UTC
DAY = 86400
Q = I.AvailabilityQuality


def bar(open_ts, close_ts=None, px=100.0):
    return I.Bar("BTC-USD", "coinbase", open_ts, close_ts or open_ts + DAY, px, px * 1.01, px * 0.99, px, 10.0)


def obs(observation_ts, published_ts, value=1.0, series="nyfed:rrp"):
    return I.Observation("nyfed", series, observation_ts, published_ts, published_ts + 60, value,
                         Q.SOURCE_TIMESTAMP, H)


def feat(name="volatility.realized_30d", known=T - DAY, prov="operator:vol30@1", q=Q.EXACT_RELEASE, value=0.5):
    return I.Feature(name, value, known, prov, q)


def fset(*features, ts=T):
    return I.SanitizedFeatureSet(ts, tuple(features))


def fc(expert="e1", asset="BTC-USD", horizon=20, er=0.01, ts=T):
    return I.ExpertForecast(expert, asset, ts, horizon, DAY, er, 0.05, 0.6, 0.3)


class Chronology(unittest.TestCase):
    def test_frame_rejects_future_bars_and_unpublished_observations(self):
        I.ObservationFrame(T, "BTC-USD", (bar(T - 2 * DAY), bar(T - DAY)))          # closes exactly at T: allowed
        with self.assertRaisesRegex(ValueError, "close after decision_ts"):
            I.ObservationFrame(T, "BTC-USD", (bar(T - DAY), bar(T)))                 # today's bar still forming
        with self.assertRaisesRegex(ValueError, "published after decision_ts"):
            I.ObservationFrame(T, "BTC-USD", (bar(T - DAY),), (obs(T - DAY, T + 1),))

    def test_asof_uses_publication_time_and_latest_vintage(self):
        o_old = obs(T - 9 * DAY, T - 8 * DAY, 1.0)
        o_new = obs(T - 2 * DAY, T - 1, 2.0)
        o_rev = obs(T - 2 * DAY, T, 2.5)                                           # revision released at T
        f = I.ObservationFrame(T, "BTC-USD", (bar(T - DAY),), (o_old, o_new, o_rev))
        self.assertEqual(f.asof("nyfed:rrp").value, 2.5)
        f2 = I.ObservationFrame(T - 1, "BTC-USD", (), (o_old, o_new))
        self.assertEqual(f2.asof("nyfed:rrp").value, 2.0)
        with self.assertRaisesRegex(ValueError, "published_ts precedes"):
            obs(T, T - 1)

    def test_availability_quality_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "mandatory"):
            I.Observation("x", "y", T, T, T, 1.0, "exact_release", H)               # a plain string is refused
        self.assertEqual(Q("source_timestamp"), Q.SOURCE_TIMESTAMP)

    def test_bars_must_be_ordered_and_consistent(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            I.ObservationFrame(T, "BTC-USD", (bar(T - DAY), bar(T - 2 * DAY)))
        with self.assertRaisesRegex(ValueError, "high/low"):
            I.Bar("BTC-USD", "coinbase", 0, DAY, 100, 99, 98, 100, 1)


class SanitizedFeatures(unittest.TestCase):
    def test_allowlist_fails_closed(self):
        fset(feat(), feat("macro.fed_total_assets", prov="data:macro_observations/fed_h41:WALCL", q=Q.EXACT_RELEASE))
        for bad in ("account_value", "portfolio_nav", "current_exposure", "risk.leverage", "router.weight",
                    "label.future_return", "Volatility.x", "volatility"):
            with self.subTest(name=bad), self.assertRaisesRegex(ValueError, "allowlisted namespace"):
                feat(bad)

    def test_every_feature_has_provenance_and_known_at(self):
        with self.assertRaisesRegex(ValueError, "provenance"):
            feat(prov="account:equity")
        with self.assertRaisesRegex(ValueError, "provenance"):
            feat(prov="")
        with self.assertRaisesRegex(ValueError, "known only after"):
            fset(feat(known=T + 1))
        with self.assertRaisesRegex(ValueError, "unique"):
            fset(feat(), feat())

    def test_expert_has_no_channel_for_account_router_execution_or_labels(self):
        reach = I.expert_reachable_fields()
        for channel in ("equity", "account", "positions", "allocation", "weights", "router", "mixture", "labels",
                        "fills", "execution", "leverage"):
            self.assertNotIn(channel, reach)
        inp = I.ExpertInput(T, fset(feat()))
        self.assertEqual(inp.features.value("volatility.realized_30d"), 0.5)
        with self.assertRaisesRegex(ValueError, "earlier"):
            I.ExpertInput(T, fset(feat()), (), (fc(ts=T),))
        with self.assertRaisesRegex(ValueError, "SanitizedFeatureSet"):
            I.ExpertInput(T, {"volatility.realized_30d": 0.5})                       # a raw dict is refused


class Structure(unittest.TestCase):
    def test_only_confirmed_pivots(self):
        p_ok = I.Pivot(T - 10 * DAY, T - 7 * DAY, 1, 120.0, "medium")
        p_active = I.Pivot(T - 2 * DAY, T + DAY, -1, 100.0, "medium")
        s = I.StructureState(T, "BTC-USD", (p_ok,), fset())
        self.assertEqual(I.ExpertInput.from_structure(s).pivots, (p_ok,))
        with self.assertRaisesRegex(ValueError, "unconfirmed"):
            I.StructureState(T, "BTC-USD", (p_ok, p_active), fset())
        with self.assertRaises(ValueError):
            I.Pivot(T, T - 1, 1, 1.0, "fast")

    def test_geometry_forecast_invariants(self):
        grid = (0.5, 0.618, 1.0, 1.618)
        ok = dict(decision_ts=T, asset="BTC-USD", direction=1, reference_price=100.0, reference_length=20.0,
                  ratio_grid=grid, horizon_bars=20, reach_probability=(0.8, 0.7, 0.5, 0.2), invalidation_price=95.0,
                  model_id="m")
        g = I.GeometryForecast(**ok)
        self.assertEqual(g.target_prices(), tuple(100.0 + r * 20.0 for r in grid))
        bad = [dict(reach_probability=(0.5, 0.6, 0.4, 0.2)), dict(ratio_grid=(1.0, 0.5, 0.6, 0.7)),
               dict(direction=0), dict(reference_price=-1.0), dict(reference_length=0.0),
               dict(ratio_grid=(-0.5, 0.618, 1.0, 1.618)), dict(invalidation_price=float("inf")),
               dict(invalidation_price=105.0),                                     # long invalidation above entry
               dict(direction=-1, invalidation_price=95.0),
               dict(direction=-1, invalidation_price=130.0, ratio_grid=(1.0, 2.0, 5.0, 6.0)),  # target below zero
               dict(horizon_bars=0)]
        for b in bad:
            with self.subTest(b=b), self.assertRaises(ValueError):
                I.GeometryForecast(**{**ok, **b})


class State(unittest.TestCase):
    def test_distribution_sums_to_one_and_baseline_is_one_hot(self):
        states = ("panic", "bull_core", "neutral")
        d = I.MarketStateDistribution.from_label(T, "BTC-USD", "v09_rules", "bull_core", states)
        self.assertEqual(d.most_likely, "bull_core")
        self.assertEqual(d.entropy, 0.0)
        u = I.MarketStateDistribution(T, "BTC-USD", "gmm", states, (1 / 3, 1 / 3, 1 / 3))
        self.assertAlmostEqual(u.entropy, math.log(3))
        with self.assertRaisesRegex(ValueError, "sum to 1"):
            I.MarketStateDistribution(T, "BTC-USD", "gmm", states, (0.5, 0.4, 0.0))

    def test_state_objects_cannot_size_trades(self):
        names = {f.name for f in dataclasses.fields(I.MarketStateDistribution)}
        self.assertFalse(names & {"weight", "weights", "exposure", "position", "size", "leverage"})


class Experts(unittest.TestCase):
    def test_forecast_units_and_bounds(self):
        f = fc()
        self.assertEqual(f.return_unit, I.RETURN_UNIT)
        self.assertEqual(f.horizon_seconds, 20 * DAY)
        self.assertEqual(f.key, ("e1", "BTC-USD"))
        for bad in (dict(confidence=1.2), dict(direction_score=-1.5), dict(expected_return=float("nan")),
                    dict(expected_volatility=-0.1), dict(horizon_bars=0), dict(return_unit="pct"),
                    dict(capacity_hint=0.0)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dataclasses.replace(f, **bad)


class Mixture(unittest.TestCase):
    def test_weights_are_per_expert_and_asset(self):
        fs = (fc("trend", "BTC-USD", er=0.02), fc("trend", "ETH-USD", er=0.03), fc("mr", "BTC-USD", er=-0.01))
        m = I.StrategyMixture(T, "router", "v09_rules",
                              {("trend", "BTC-USD"): 0.7, ("trend", "ETH-USD"): 0.25, ("mr", "BTC-USD"): 0.3}, fs)
        c = m.combined_expected_return()
        self.assertAlmostEqual(c["BTC-USD"], 0.7 * 0.02 - 0.3 * 0.01)
        self.assertAlmostEqual(c["ETH-USD"], 0.25 * 0.03)
        with self.assertRaisesRegex(ValueError, "per-asset weights"):
            I.StrategyMixture(T, "r", "s", {("trend", "BTC-USD"): 0.8, ("mr", "BTC-USD"): 0.3}, fs)
        with self.assertRaisesRegex(ValueError, "keyed by"):
            I.StrategyMixture(T, "r", "s", {"trend": 0.5}, fs)                      # expert-only keys refused
        with self.assertRaisesRegex(ValueError, "one horizon"):
            I.StrategyMixture(T, "r", "s", {}, (fc("a"), fc("b", horizon=5)))
        with self.assertRaisesRegex(ValueError, "one forecast per"):
            I.StrategyMixture(T, "r", "s", {}, (fc("a"), fc("a")))


class Risk(unittest.TestCase):
    def test_caps_condition_number_and_fallback_rungs(self):
        a = I.RiskAllocation(T, "mk", {"BTC-USD": 1.5, "ETH-USD": 1.0}, 2.0, 3.0, 0.5, "ledoit_wolf", 12.0)
        self.assertEqual(a.gross, 2.5)
        bad = [dict(weights={"BTC-USD": 2.5}), dict(weights={"BTC-USD": 2.0, "ETH-USD": 1.5}),
               dict(per_asset_cap=0.0), dict(gross_cap=float("nan")), dict(condition_number=0.5),
               dict(condition_number=float("inf")), dict(kelly_fraction=0.0),
               dict(covariance_method="diag_blend_50pct"),
               dict(covariance_method="zero_exposure", weights={"BTC-USD": 0.1})]
        base = dict(decision_ts=T, allocator_id="mk", weights={"BTC-USD": 1.0}, per_asset_cap=2.0, gross_cap=3.0,
                    kelly_fraction=0.5, covariance_method="ledoit_wolf", condition_number=12.0)
        for b in bad:
            with self.subTest(b=b), self.assertRaises(ValueError):
                I.RiskAllocation(**{**base, **b})


class Execution(unittest.TestCase):
    def ev(self, **kw):
        base = dict(ts=T, venue="v", symbol="s", kind=I.ExecutionKind.FILL, quantity=1.0, price=100.0,
                    schedule_id="sched@2026-10-01", fill_model=I.FillModel.CONSERVATIVE_BAR, fee_paid=0.045)
        base.update(kw)
        return I.ExecutionEvent(**base)

    def test_prices_and_fee_sign_conventions(self):
        self.ev()
        self.ev(fee_paid=0.0, rebate_received=0.01)
        for b in (dict(price=None), dict(price=0.0), dict(price=-5.0), dict(quantity=0.0), dict(fee_paid=-0.01),
                  dict(rebate_received=-0.01), dict(funding_paid=1.0),
                  dict(kind=I.ExecutionKind.UNFILLED, fee_paid=0.1)):
            with self.subTest(b=b), self.assertRaises(ValueError):
                self.ev(**b)

    def test_funding_needs_recorded_event_and_signed_payment(self):
        fund = dict(kind=I.ExecutionKind.FUNDING, quantity=0.0, price=None, fee_paid=0.0)
        with self.assertRaisesRegex(ValueError, "settlement timestamp"):
            self.ev(**fund, funding_rate=1e-4)
        self.ev(**fund, funding_rate=1e-4, funding_event_ts=T, funding_paid=0.25)    # long pays positive funding
        self.ev(**fund, funding_rate=-1e-4, funding_event_ts=T, funding_paid=-0.25)  # long receives

    def test_liquidation_and_same_bar_rules(self):
        with self.assertRaisesRegex(ValueError, "approximate"):
            self.ev(kind=I.ExecutionKind.LIQUIDATION, quantity=-1.0, price=90.0)
        self.ev(kind=I.ExecutionKind.LIQUIDATION, quantity=-1.0, price=90.0, liquidation_approximate=True)
        with self.assertRaisesRegex(ValueError, "state how"):
            self.ev(kind=I.ExecutionKind.STOP, quantity=-1.0, price=95.0, same_bar_ambiguous=True)
        with self.assertRaisesRegex(ValueError, "pessimistically"):
            self.ev(kind=I.ExecutionKind.TARGET, quantity=-1.0, price=110.0, same_bar_ambiguous=True,
                    ambiguity_resolution="optimistic")
        self.ev(kind=I.ExecutionKind.TARGET, quantity=-1.0, price=110.0, fill_model=I.FillModel.RESEARCH_OPTIMISTIC,
                same_bar_ambiguous=True, ambiguity_resolution="optimistic")


class Evidence(unittest.TestCase):
    def bundle(self, **kw):
        base = dict(schema_version="1.0", bundle_id="b1", created_ts=T, source_ai="claude", role="statistical_reviewer",
                    trial_ids=("t1", "t2"), n_trials_counted=68, verdict=I.Verdict.STRUCTURAL_ONLY, dsr=0.84,
                    pbo=None, pbo_matrix_sha256=None, holdout_accessed=False, code_sha256=H, data_sha256=H,
                    spec_sha256=None, execution_model_id="flat_25bps_v09")
        base.update(kw)
        return I.EvidenceBundle(**base)

    def test_gate_rules(self):
        self.assertEqual(len(self.bundle().sha256()), 64)
        with self.assertRaisesRegex(ValueError, "authority"):
            self.bundle(authority_request=True)
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            self.bundle(dsr=1.2)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.bundle(pbo=0.2)
        self.bundle(pbo=0.2, pbo_matrix_sha256=H)
        with self.assertRaisesRegex(ValueError, "0.95"):
            self.bundle(verdict=I.Verdict.CANDIDATE)
        self.bundle(verdict=I.Verdict.CANDIDATE, dsr=0.96)
        with self.assertRaisesRegex(ValueError, "holdout"):
            self.bundle(verdict=I.Verdict.CANDIDATE, dsr=0.96, holdout_accessed=True)
        with self.assertRaisesRegex(ValueError, "fixed"):
            self.bundle(dsr_threshold=1.0)
        self.bundle(n_trials_effective=40.5, n_return_equivalence_classes=60)
        with self.assertRaisesRegex(ValueError, "effective"):
            self.bundle(n_trials_effective=80.0)                                   # never larger than the count

    def trial(self, **kw):
        base = dict(trial_id="x", source_version="v0.6", family="v06.signal_elliott", name="T11_elliott_soft_wave4",
                    kind=I.TrialKind.CANDIDATE, parameters={"fib_anchors": [0.382, 0.5, 0.618]}, asset="BTC-USD",
                    venue="coinbase", product="spot", code_sha256=H, spec_sha256=None, data_sha256=H,
                    window={"full_sample": [1437350400, 1790899200]}, cost_model_id="flat_25bps",
                    metrics={"sharpe": 0.70}, returns_status=I.ReturnsStatus.RECONSTRUCTABLE)
        base.update(kw)
        return I.TrialRecord(**base)

    def test_identical_returns_do_not_merge_distinct_hypotheses(self):
        a = self.trial()
        b = self.trial(trial_id="y", family="v06.named_fibonacci", name="T12_named_fibonacci")
        self.assertNotEqual(a.identity_sha256(), b.identity_sha256())            # two hypotheses, two records
        stored = dict(returns_status=I.ReturnsStatus.STORED, returns_ref="r.csv.gz", returns_sha256=H,
                      return_equivalence_id="b" * 64, returns_frequency="daily")
        a2, b2 = self.trial(**stored), self.trial(trial_id="y", name="T12_named_fibonacci", **stored)
        self.assertEqual(a2.return_equivalence_id, b2.return_equivalence_id)    # but they share an equivalence id
        dup = self.trial(trial_id="z", metrics={"sharpe": 0.7000001}, artifact_refs=("other.json#run3",))
        self.assertEqual(a.identity_sha256(), dup.identity_sha256())             # same trial recorded twice

    def test_returns_and_kind_rules(self):
        with self.assertRaisesRegex(ValueError, "path"):
            self.trial(returns_status=I.ReturnsStatus.STORED)
        with self.assertRaisesRegex(ValueError, "frequency"):
            self.trial(returns_status=I.ReturnsStatus.STORED, returns_ref="r", returns_sha256=H,
                       return_equivalence_id=H)
        with self.assertRaisesRegex(ValueError, "cannot carry"):
            self.trial(returns_status=I.ReturnsStatus.UNAVAILABLE, return_equivalence_id=H)
        with self.assertRaisesRegex(ValueError, "sensitivity"):
            self.trial(kind=I.TrialKind.SENSITIVITY)
        self.trial(kind=I.TrialKind.SENSITIVITY, parent_trial_id="x", cost_model_id="flat_85bps")

    def test_objects_are_frozen_and_hash_deterministically(self):
        f = fc()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            f.expected_return = 1.0                                             # type: ignore[misc]
        with self.assertRaises(TypeError):
            f.metadata["x"] = 1                                                 # type: ignore[index]
        self.assertEqual(I.sha256_of(fc()), I.sha256_of(fc()))


class Coverage(unittest.TestCase):
    def test_coverage_result_validation(self):
        I.CoverageResult("funding:bitmex:XBTUSD", 0, 10, 2, 10, 0.8, Q.SOURCE_TIMESTAMP, I.CoverageStatus.PARTIAL)
        with self.assertRaises(ValueError):
            I.CoverageResult("f", 10, 0, None, None, 0.0, Q.APPROXIMATE, I.CoverageStatus.FAIL)
        with self.assertRaises(ValueError):
            I.CoverageResult("f", 0, 10, None, None, 1.5, Q.APPROXIMATE, I.CoverageStatus.FAIL)


if __name__ == "__main__":
    unittest.main()
