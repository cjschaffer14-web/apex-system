"""Stage 2 Layer 6 tests: Ledoit-Wolf ladder, fractional Kelly, guards, exact caps, point-in-time fail-closed."""
import math
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np                                       # noqa: E402

from apex_v10 import interfaces as I                     # noqa: E402
from apex_v10.risk import (LedoitWolfKellyAllocator, PointInTimeViolation, ReturnsWindow, RiskConfig,  # noqa: E402
                           cap_gross_exactly)
from apex_v10.risk.allocator import ledoit_wolf_covariance                                            # noqa: E402

T = 1790899200
DAY = 86400
ASSETS = ("BTC-USD", "ETH-USD")


def window(x, assets=ASSETS, end=T, period=DAY):
    n = len(x)
    return ReturnsWindow(tuple(assets), tuple(end - (n - 1 - i) * period for i in range(n)),
                         tuple(tuple(float(v) for v in r) for r in x), period)


def mixture(er, ts=T, horizon=1):
    fcs = tuple(I.ExpertForecast("e1", a, ts, horizon, DAY, r, None, 0.5, 0.0) for a, r in er.items())
    return I.StrategyMixture(ts, "r", "s", {f.key: 1.0 for f in fcs}, fcs)


def returns(n=300, seed=7, vol=(0.03, 0.04), rho=0.6):
    rng = np.random.default_rng(seed)
    c = np.array([[vol[0] ** 2, rho * vol[0] * vol[1]], [rho * vol[0] * vol[1], vol[1] ** 2]])
    return rng.multivariate_normal([0, 0], c, size=n)


class LedoitWolf(unittest.TestCase):
    def test_matches_sklearn(self):
        from sklearn.covariance import ledoit_wolf
        x = returns(250)
        s, k = ledoit_wolf_covariance(x)
        s_ref, k_ref = ledoit_wolf(x)
        np.testing.assert_allclose(s, s_ref, rtol=1e-12, atol=1e-15)
        self.assertAlmostEqual(k, k_ref, places=12)


class Ladder(unittest.TestCase):
    def test_well_conditioned_uses_ledoit_wolf_and_is_deterministic(self):
        al = LedoitWolfKellyAllocator()
        a1 = al.allocate(mixture({"BTC-USD": 0.002, "ETH-USD": 0.001}), window(returns()), ASSETS)
        a2 = al.allocate(mixture({"BTC-USD": 0.002, "ETH-USD": 0.001}), window(returns()), ASSETS)
        self.assertEqual(a1.covariance_method, "ledoit_wolf")
        self.assertEqual(dict(a1.weights), dict(a2.weights))
        self.assertEqual(a1.guard_events, a2.guard_events)
        self.assertTrue(al.allocator_id.startswith("lw_kelly@"))

    def test_near_singular_hits_eigen_floor_and_stays_capped(self):
        # the frozen v0.9 stress case: three almost identical columns
        rng = np.random.default_rng(20261003)
        x = rng.normal(0, 0.01, 700)
        r = np.column_stack([x, x * 1.00000001, x + 1e-10 * rng.normal(size=len(x))])
        assets = ("A", "B", "C")
        cfg = RiskConfig(kelly_fraction=1.0)
        a = LedoitWolfKellyAllocator(cfg).allocate(mixture({k: 0.001 for k in assets}), window(r, assets), assets)
        self.assertIn(a.covariance_method, ("ledoit_wolf", "ledoit_wolf+eigen_floor"))
        self.assertTrue(all(math.isfinite(v) for v in a.weights.values()))
        self.assertLessEqual(a.gross, 3.0)                       # exact, no 3.0000000000000004
        self.assertLessEqual(a.condition_number, cfg.max_condition_number)

    def test_eigen_floor_rung_is_reported(self):
        x = returns(300, rho=0.999999)
        cfg = RiskConfig(max_condition_number=10.0)
        a = LedoitWolfKellyAllocator(cfg).allocate(mixture({"BTC-USD": 0.001, "ETH-USD": 0.001}), window(x), ASSETS)
        self.assertEqual(a.covariance_method, "ledoit_wolf+eigen_floor")
        self.assertTrue(any(e.startswith("fallback:eigen_floor") for e in a.guard_events))
        self.assertLessEqual(a.condition_number, 10.0)

    def test_short_history_falls_back_then_zero(self):
        al = LedoitWolfKellyAllocator()
        a = al.allocate(mixture({"BTC-USD": 0.002}), window(returns(40)), ASSETS)
        self.assertEqual(a.covariance_method, "independent_fractional_kelly")
        z = al.allocate(mixture({"BTC-USD": 0.002}), window(returns(10)), ASSETS)
        self.assertEqual(z.covariance_method, "zero_exposure")
        self.assertEqual(z.gross, 0.0)

    def test_constant_column_is_zero_exposure(self):
        x = returns(100)
        x[:, 1] = 0.0
        a = LedoitWolfKellyAllocator().allocate(mixture({"BTC-USD": 0.002}), window(x), ASSETS)
        self.assertEqual(a.covariance_method, "zero_exposure")

    def test_nan_rows_are_dropped_not_filled(self):
        x = returns(300)
        x[::3, 0] = np.nan
        a = LedoitWolfKellyAllocator().allocate(mixture({"BTC-USD": 0.002}), window(x), ASSETS)
        self.assertEqual(a.covariance_method, "ledoit_wolf")


class PointInTime(unittest.TestCase):
    def test_future_row_raises(self):
        with self.assertRaises(PointInTimeViolation):
            LedoitWolfKellyAllocator().allocate(mixture({"BTC-USD": 0.002}), window(returns(), end=T + DAY), ASSETS)

    def test_future_state_raises(self):
        st = I.MarketStateDistribution.from_label(T + 1, "market", "rules", "bull", ("bull", "bear"))
        with self.assertRaises(PointInTimeViolation):
            LedoitWolfKellyAllocator().allocate(mixture({"BTC-USD": 0.002}), window(returns()), ASSETS, state=st)

    def test_untimestamped_matrix_refused(self):
        with self.assertRaises(TypeError):
            LedoitWolfKellyAllocator().allocate(mixture({"BTC-USD": 0.002}), returns().tolist(), ASSETS)

    def test_column_mismatch_and_unknown_asset_refused(self):
        al = LedoitWolfKellyAllocator()
        with self.assertRaises(ValueError):
            al.allocate(mixture({"BTC-USD": 0.002}), window(returns()), ("ETH-USD", "BTC-USD"))
        with self.assertRaises(ValueError):
            al.allocate(mixture({"SOL-USD": 0.002}), window(returns()), ASSETS)

    def test_required_state_missing_is_zero_exposure(self):
        a = LedoitWolfKellyAllocator(RiskConfig(require_state=True)).allocate(
            mixture({"BTC-USD": 0.002}), window(returns()), ASSETS)
        self.assertEqual(a.covariance_method, "zero_exposure")
        self.assertIn("zero_exposure:state_required_but_missing", a.guard_events)


class Guards(unittest.TestCase):
    big = {"BTC-USD": 0.05, "ETH-USD": 0.05}

    def test_caps_hold_and_are_logged(self):
        a = LedoitWolfKellyAllocator(RiskConfig(kelly_fraction=1.0)).allocate(mixture(self.big), window(returns()), ASSETS)
        self.assertLessEqual(max(abs(v) for v in a.weights.values()), 2.0)
        self.assertLessEqual(a.gross, 3.0)
        self.assertTrue(any(e.startswith("per_asset_cap") for e in a.guard_events))

    def test_long_only_clips_shorts(self):
        a = LedoitWolfKellyAllocator().allocate(mixture({"BTC-USD": -0.01, "ETH-USD": 0.001}), window(returns()), ASSETS)
        self.assertGreaterEqual(min(a.weights.values()), 0.0)
        self.assertTrue(any(e.startswith("long_only_clip") for e in a.guard_events))

    def test_net_cap_with_shorts(self):
        cfg = RiskConfig(long_only=False, net_cap=0.5, kelly_fraction=1.0)
        a = LedoitWolfKellyAllocator(cfg).allocate(mixture(self.big), window(returns()), ASSETS)
        self.assertLessEqual(abs(sum(a.weights.values())), 0.5)

    def test_vol_target_only_scales_down(self):
        x = returns()
        mix = mixture({"BTC-USD": 0.002, "ETH-USD": 0.001})
        free = LedoitWolfKellyAllocator().allocate(mix, window(x), ASSETS)
        tight = LedoitWolfKellyAllocator(RiskConfig(target_volatility=0.005)).allocate(mix, window(x), ASSETS)
        loose = LedoitWolfKellyAllocator(RiskConfig(target_volatility=10.0)).allocate(mix, window(x), ASSETS)
        self.assertLess(tight.gross, free.gross)
        self.assertEqual(dict(loose.weights), dict(free.weights))

    def test_regime_and_uncertainty_guards_reduce_gross(self):
        cfg = RiskConfig(kelly_fraction=1.0, regime_gross_multipliers={"bear": 0.25}, max_state_entropy=0.5)
        al = LedoitWolfKellyAllocator(cfg)
        bear = I.MarketStateDistribution.from_label(T, "market", "rules", "bear", ("bull", "bear"))
        mixed = I.MarketStateDistribution(T, "market", "gmm", ("bull", "bear"), (0.5, 0.5))
        a = al.allocate(mixture(self.big), window(returns()), ASSETS, state=bear)
        self.assertLessEqual(a.gross, 0.75)
        b = al.allocate(mixture(self.big), window(returns()), ASSETS, state=mixed)
        self.assertLessEqual(b.gross, 1.5)
        self.assertTrue(any(e.startswith("regime_uncertain") for e in b.guard_events))

    def test_vol_spike_guard(self):
        x = returns(300)
        x[-20:] *= 5
        a = LedoitWolfKellyAllocator(RiskConfig(kelly_fraction=1.0)).allocate(mixture(self.big), window(x), ASSETS)
        self.assertTrue(any(e.startswith("vol_spike_guard") for e in a.guard_events))
        self.assertLessEqual(a.gross, 1.5)

    def test_guards_cannot_raise_exposure(self):
        for bad in (dict(regime_gross_multipliers={"bull": 1.5}), dict(vol_spike_gross_multiplier=2.0),
                    dict(kelly_fraction=1.5), dict(gross_cap=float("inf"))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                RiskConfig(**bad)

    def test_cap_gross_exactly(self):
        w = np.array([1.0, 1.0, 1.0000000000000004])
        out = cap_gross_exactly(w * 7.3, 3.0)
        self.assertLessEqual(float(np.sum(np.abs(out))), 3.0)
        self.assertGreater(float(np.sum(np.abs(out))), 3.0 - 1e-12)


class Protocol(unittest.TestCase):
    def test_conforms_to_risk_allocator(self):
        self.assertIsInstance(LedoitWolfKellyAllocator(), I.RiskAllocator)


if __name__ == "__main__":
    unittest.main()
