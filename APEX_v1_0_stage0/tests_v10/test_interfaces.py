"""Stage 0 contract tests for apex_v10.interfaces (standard library only)."""
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


def bar(open_ts, close_ts=None, px=100.0):
    return I.Bar("BTC-USD", "coinbase", open_ts, close_ts or open_ts + DAY, px, px * 1.01, px * 0.99, px, 10.0)


def obs(observation_ts, published_ts, value=1.0, series="nyfed:rrp"):
    return I.Observation("nyfed", series, observation_ts, published_ts, published_ts + 60, value,
                         I.AvailabilityQuality.EXACT_RELEASE, H)


def fc(expert="e1", asset="BTC-USD", horizon=20, er=0.01, ts=T):
    return I.ExpertForecast(expert, asset, ts, horizon, DAY, er, 0.05, 0.6, 0.3)


class Chronology(unittest.TestCase):
    def test_frame_rejects_future_bars_and_unpublished_observations(self):
        I.ObservationFrame(T, "BTC-USD", (bar(T - 2 * DAY), bar(T - DAY)))          # closes exactly at T: allowed
        with self.assertRaisesRegex(ValueError, "close after decision_ts"):
            I.ObservationFrame(T, "BTC-USD", (bar(T - DAY), bar(T)))                 # today's bar still forming
        with self.assertRaisesRegex(ValueError, "published after decision_ts"):
            I.ObservationFrame(T, "BTC-USD", (bar(T - DAY),), (obs(T - DAY, T + 1),))

    def test_asof_uses_publication_time_not_observation_time(self):
        o_old = obs(T - 9 * DAY, T - 8 * DAY, 1.0)
        o_new = obs(T - 2 * DAY, T - 1, 2.0)                                       # published one second earlier
        f = I.ObservationFrame(T, "BTC-USD", (bar(T - DAY),), (o_old, o_new))
        self.assertEqual(f.asof("nyfed:rrp").value, 2.0)
        with self.assertRaisesRegex(ValueError, "published_ts precedes"):
            obs(T, T - 1)

    def test_bars_must_be_ordered_and_consistent(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            I.ObservationFrame(T, "BTC-USD", (bar(T - DAY), bar(T - 2 * DAY)))
        with self.assertRaisesRegex(ValueError, "high/low"):
            I.Bar("BTC-USD", "coinbase", 0, DAY, 100, 99, 98, 100, 1)


class Structure(unittest.TestCase):
    def test_only_confirmed_pivots(self):
        p_ok = I.Pivot(T - 10 * DAY, T - 7 * DAY, 1, 120.0, "medium")
        p_active = I.Pivot(T - 2 * DAY, T + DAY, -1, 100.0, "medium")              # not yet confirmable
        I.StructureState(T, "BTC-USD", (p_ok,))
        with self.assertRaisesRegex(ValueError, "unconfirmed"):
            I.StructureState(T, "BTC-USD", (p_ok, p_active))
        with self.assertRaises(ValueError):
            I.Pivot(T, T - 1, 1, 1.0, "fast")

    def test_geometry_forecast_monotone_and_uses_ratio_grid(self):
        grid = (0.5, 0.618, 1.0, 1.618)
        g = I.GeometryForecast(T, "BTC-USD", 1, 100.0, 20.0, grid, 20, (0.8, 0.7, 0.5, 0.2), 95.0, "m")
        self.assertEqual(g.target_prices(), tuple(100.0 + r * 20.0 for r in grid))
        with self.assertRaisesRegex(ValueError, "non-increasing"):
            I.GeometryForecast(T, "BTC-USD", 1, 100.0, 20.0, grid, 20, (0.5, 0.6, 0.4, 0.2), 95.0, "m")
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            I.GeometryForecast(T, "BTC-USD", 1, 100.0, 20.0, (1.0, 0.5), 20, (0.5, 0.4), 95.0, "m")


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
    def test_expert_cannot_reach_account_router_or_future(self):
        self.assertFalse(I.expert_input_fields() & I.FORBIDDEN_EXPERT_INPUTS)
        st = I.StructureState(T, "BTC-USD", (), {"leverage": 2.0})
        with self.assertRaisesRegex(ValueError, "forbidden"):
            I.ExpertInput(T, st)
        with self.assertRaisesRegex(ValueError, "earlier"):
            I.ExpertInput(T, I.StructureState(T, "BTC-USD", ()), (fc(ts=T),))

    def test_forecast_units_and_bounds(self):
        f = fc()
        self.assertEqual(f.return_unit, I.RETURN_UNIT)
        self.assertEqual(f.horizon_seconds, 20 * DAY)
        for bad in (dict(confidence=1.2), dict(direction_score=-1.5), dict(expected_return=float("nan")),
                    dict(expected_volatility=-0.1), dict(horizon_bars=0), dict(return_unit="pct")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                dataclasses.replace(f, **bad)


class Mixture(unittest.TestCase):
    def test_common_horizon_and_weights(self):
        m = I.StrategyMixture(T, "router", "v09_rules", {"e1": 0.6, "e2": 0.3},
                              (fc("e1", er=0.02), fc("e2", er=-0.01)))
        self.assertAlmostEqual(m.combined_expected_return()["BTC-USD"], 0.6 * 0.02 - 0.3 * 0.01)
        with self.assertRaisesRegex(ValueError, "one horizon"):
            I.StrategyMixture(T, "r", "s", {"e1": 0.5}, (fc("e1"), fc("e2", horizon=5)))
        with self.assertRaisesRegex(ValueError, "at most 1"):
            I.StrategyMixture(T, "r", "s", {"e1": 0.7, "e2": 0.7}, (fc("e1"), fc("e2")))


class Risk(unittest.TestCase):
    def test_caps_and_fallback_rungs(self):
        a = I.RiskAllocation(T, "mk", {"BTC-USD": 1.5, "ETH-USD": 1.0}, 2.0, 3.0, 0.5, "ledoit_wolf", 12.0)
        self.assertEqual(a.gross, 2.5)
        with self.assertRaisesRegex(ValueError, "per-asset cap"):
            I.RiskAllocation(T, "mk", {"BTC-USD": 2.5}, 2.0, 3.0, 0.5, "ledoit_wolf", 12.0)
        with self.assertRaisesRegex(ValueError, "gross exposure"):
            I.RiskAllocation(T, "mk", {"BTC-USD": 2.0, "ETH-USD": 1.5}, 2.0, 3.0, 0.5, "ledoit_wolf", 12.0)
        with self.assertRaisesRegex(ValueError, "zero-exposure"):
            I.RiskAllocation(T, "mk", {"BTC-USD": 0.1}, 2.0, 3.0, 0.5, "zero_exposure", None)
        with self.assertRaisesRegex(ValueError, "covariance_method"):
            I.RiskAllocation(T, "mk", {}, 2.0, 3.0, 0.5, "diag_blend_50pct", None)


class Execution(unittest.TestCase):
    def test_funding_needs_recorded_event_and_liquidation_flags(self):
        with self.assertRaisesRegex(ValueError, "settlement timestamp"):
            I.ExecutionEvent(T, "bitmex", "XBTUSD", I.ExecutionKind.FUNDING, 0, None, 0, "s1",
                             I.FillModel.CONSERVATIVE_BAR, funding_rate=1e-4)
        I.ExecutionEvent(T, "bitmex", "XBTUSD", I.ExecutionKind.FUNDING, 0, None, 0, "s1",
                         I.FillModel.CONSERVATIVE_BAR, funding_rate=1e-4, funding_event_ts=T)
        with self.assertRaisesRegex(ValueError, "approximate"):
            I.ExecutionEvent(T, "v", "s", I.ExecutionKind.LIQUIDATION, -1, 90.0, 1.0, "s1", I.FillModel.CONSERVATIVE_BAR)
        I.ExecutionEvent(T, "v", "s", I.ExecutionKind.LIQUIDATION, -1, 90.0, 1.0, "s1", I.FillModel.CONSERVATIVE_BAR,
                         liquidation_approximate=True)

    def test_same_bar_ambiguity_is_resolved_pessimistically_by_default(self):
        with self.assertRaisesRegex(ValueError, "state how"):
            I.ExecutionEvent(T, "v", "s", I.ExecutionKind.STOP, -1, 95.0, 0.1, "s1", I.FillModel.CONSERVATIVE_BAR,
                             same_bar_ambiguous=True)
        with self.assertRaisesRegex(ValueError, "pessimistically"):
            I.ExecutionEvent(T, "v", "s", I.ExecutionKind.TARGET, -1, 110.0, 0.1, "s1", I.FillModel.CONSERVATIVE_BAR,
                             same_bar_ambiguous=True, ambiguity_resolution="optimistic")
        I.ExecutionEvent(T, "v", "s", I.ExecutionKind.TARGET, -1, 110.0, 0.1, "s1", I.FillModel.RESEARCH_OPTIMISTIC,
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
        b = self.bundle()
        self.assertEqual(len(b.sha256()), 64)
        with self.assertRaisesRegex(ValueError, "authority"):
            self.bundle(authority_request=True)
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            self.bundle(dsr=1.2)
        with self.assertRaisesRegex(ValueError, "aligned return matrix"):
            self.bundle(pbo=0.2)
        self.bundle(pbo=0.2, pbo_matrix_sha256=H)
        with self.assertRaisesRegex(ValueError, "0.95"):
            self.bundle(verdict=I.Verdict.CANDIDATE)                     # DSR 0.84 fails the gate
        self.bundle(verdict=I.Verdict.CANDIDATE, dsr=0.96)
        with self.assertRaisesRegex(ValueError, "holdout"):
            self.bundle(verdict=I.Verdict.CANDIDATE, dsr=0.96, holdout_accessed=True)
        with self.assertRaisesRegex(ValueError, "fixed"):
            self.bundle(dsr_threshold=1.0)

    def test_trial_identity_and_returns_status(self):
        t = I.TrialRecord("x", "v06.signal_sma200", {"cost_bps": 25}, "BTC-USD", "coinbase", "spot", H, None, H,
                          {"full_sample": [1437350400, 1790899200]}, "flat_25bps", {"sharpe": 1.0},
                          I.ReturnsStatus.RECONSTRUCTABLE)
        t2 = dataclasses.replace(t, trial_id="y", metrics={"sharpe": 2.0})
        self.assertEqual(t.identity_sha256(), t2.identity_sha256())            # same trial; metrics are not identity
        t3 = dataclasses.replace(t, parameters={"cost_bps": 85})
        self.assertNotEqual(t.identity_sha256(), t3.identity_sha256())
        with self.assertRaisesRegex(ValueError, "path and its SHA-256"):
            dataclasses.replace(t, returns_status=I.ReturnsStatus.STORED)

    def test_objects_are_frozen_and_hash_deterministically(self):
        f = fc()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            f.expected_return = 1.0                                             # type: ignore[misc]
        with self.assertRaises(TypeError):
            f.metadata["x"] = 1                                                 # type: ignore[index]
        self.assertEqual(I.sha256_of(fc()), I.sha256_of(fc()))


if __name__ == "__main__":
    unittest.main()
