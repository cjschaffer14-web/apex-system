"""Pins the owner-ratified Stage 3 guard configuration (Gemini review, 2026-10-05).

Checks that allocator_v2 applies the new values and that the Stage 2 allocator is unchanged."""
import dataclasses
import unittest
from types import SimpleNamespace

import numpy as np

from apex_v10.risk.allocator import LedoitWolfKellyAllocator, PointInTimeViolation, ReturnsWindow, RiskConfig
from apex_v10.risk.allocator_v2 import LedoitWolfKellyAllocatorV2, RiskConfigV2, pyramid_regime_configs

H, D = 3600, 86400


def _mixture(ts, mu, horizon):
    return SimpleNamespace(decision_ts=ts, forecasts=[SimpleNamespace(horizon_seconds=horizon)],
                           combined_expected_return=lambda: dict(mu))


def _window(x, period, t0=1_000_000):
    ts = tuple(t0 + period * (i + 1) for i in range(len(x)))
    return ReturnsWindow(("BTC", "ETH"), ts, tuple(tuple(map(float, r)) for r in x), period), ts[-1]


def _field(alloc, i):
    return getattr(alloc, dataclasses.fields(alloc)[i].name)


def _parts(alloc):   # positional contract: weights=2, rung=6, events=8
    return _field(alloc, 2), _field(alloc, 6), _field(alloc, 8)


class Stage2Unchanged(unittest.TestCase):
    def test_stage2_defaults_untouched(self):
        c = RiskConfig()
        self.assertEqual((c.max_condition_number, c.min_observations, c.min_observations_per_asset), (1e4, 60, 20))
        self.assertEqual((c.gross_cap, c.net_cap, c.per_asset_cap, c.kelly_fraction), (3.0, 3.0, 2.0, 0.5))
        self.assertIsNone(c.target_volatility)
        self.assertTrue(LedoitWolfKellyAllocator().allocator_id.startswith("lw_kelly@"))


class Stage3Config(unittest.TestCase):
    def test_new_defaults(self):
        c = RiskConfigV2()
        self.assertEqual(c.max_condition_number, 1e3)
        self.assertEqual((c.gross_cap, c.net_cap, c.per_asset_cap, c.kelly_fraction), (1.0, 1.0, 1.0, 0.5))
        self.assertEqual((c.vol_spike_window, c.vol_spike_baseline_window, c.vol_spike_ratio), (20, 252, 2.0))
        self.assertIsNone(c.target_volatility)

    def test_timeframe_minimums(self):
        c = RiskConfigV2()
        h, d = c.for_period(H), c.for_period(D)
        self.assertEqual((h.min_observations, h.min_observations_per_asset), (720, 168))
        self.assertEqual((d.min_observations, d.min_observations_per_asset), (60, 20))

    def test_leverage_above_one_needs_target_vol(self):
        with self.assertRaises(ValueError):
            RiskConfigV2(gross_cap=2.0)
        RiskConfigV2(gross_cap=2.0, net_cap=2.0, target_volatility=0.40)   # allowed once a target is fixed

    def test_requires_v2_config(self):
        with self.assertRaises(TypeError):
            LedoitWolfKellyAllocatorV2(RiskConfig())


class Stage3Allocation(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(7)

    def _alloc(self, n, period):
        win, ts = _window(self.rng.normal(0, 0.01, (n, 2)), period)
        return LedoitWolfKellyAllocatorV2().allocate(_mixture(ts, {"BTC": 0.01, "ETH": 0.008}, period), win, ("BTC", "ETH"))

    def test_hourly_below_floor_is_zero_exposure(self):
        w, rung, _ = _parts(self._alloc(167, H))
        self.assertEqual(rung, "zero_exposure")
        self.assertTrue(all(v == 0.0 for v in w.values()))

    def test_hourly_between_floor_and_primary_falls_back(self):
        self.assertEqual(_parts(self._alloc(500, H))[1], "independent_fractional_kelly")
        self.assertNotEqual(_parts(self._alloc(800, H))[1], "independent_fractional_kelly")

    def test_daily_keeps_60_20(self):
        self.assertNotEqual(_parts(self._alloc(100, D))[1], "independent_fractional_kelly")
        self.assertEqual(_parts(self._alloc(40, D))[1], "independent_fractional_kelly")

    def test_caps_hold_at_one(self):
        w, _, _ = _parts(self._alloc(900, H))
        self.assertLessEqual(sum(abs(v) for v in w.values()), 1.0)
        self.assertLessEqual(max(abs(v) for v in w.values()), 1.0)

    def test_rolling_baseline_detects_spike_full_window_misses(self):
        # very volatile early history inflates the full-window baseline; the recent spike is
        # anomalous only against the trailing 252 rows
        x = np.vstack([self.rng.normal(0, 0.08, (400, 2)), self.rng.normal(0, 0.01, (252, 2)),
                       self.rng.normal(0, 0.03, (20, 2))])
        win, ts = _window(x, D)
        mix = _mixture(ts, {"BTC": 0.01, "ETH": 0.01}, D)
        _, _, ev2 = _parts(LedoitWolfKellyAllocator().allocate(mix, win, ("BTC", "ETH")))
        _, _, ev3 = _parts(LedoitWolfKellyAllocatorV2().allocate(mix, win, ("BTC", "ETH")))
        self.assertFalse(any(e.startswith("vol_spike_guard") for e in ev2))
        self.assertTrue(any(e.startswith("vol_spike_guard") and "baseline=252" in e for e in ev3))

    def test_point_in_time_still_fails_closed(self):
        win, ts = _window(self.rng.normal(0, 0.01, (800, 2)), H)
        with self.assertRaises(PointInTimeViolation):
            LedoitWolfKellyAllocatorV2().allocate(_mixture(ts - 1, {"BTC": 0.01}, H), win, ("BTC", "ETH"))

    def test_baseline_excludes_current_window(self):
        # a spike that dominates the trailing 252 only if the current window is counted in the baseline
        x = np.vstack([self.rng.normal(0, 0.01, (252, 2)), self.rng.normal(0, 0.05, (20, 2))])
        win, ts = _window(x, D)
        _, _, ev = _parts(LedoitWolfKellyAllocatorV2().allocate(_mixture(ts, {"BTC": 0.01, "ETH": 0.01}, D),
                                                                win, ("BTC", "ETH")))
        e = [e for e in ev if e.startswith("vol_spike_guard")]
        self.assertTrue(e and "baseline=252" in e[0])
        self.assertGreater(float(e[0].split("ratio=")[1].split(":")[0]), 4.0)


class CorrelationShock(unittest.TestCase):
    def _run(self, corr, mu=0.05):
        rng = np.random.default_rng(3)
        z = rng.normal(size=(800, 2))
        z[:, 1] = corr * z[:, 0] + np.sqrt(1 - corr ** 2) * z[:, 1]
        win, ts = _window(z * 0.04, D)
        return _parts(LedoitWolfKellyAllocatorV2().allocate(_mixture(ts, {"BTC": mu, "ETH": mu}, D), win, ("BTC", "ETH")))

    def test_events_record_all_measures(self):
        _, _, ev = self._run(0.2)
        e = [e for e in ev if e.startswith("corr_shock:")]
        self.assertEqual(len(e), 1)
        for key in ("unstressed=", "stressed@0.95=", "diagnostic@1=", "limit=", "scale="):
            self.assertIn(key, e[0])

    def test_stressed_vol_within_operative_limit(self):
        _, _, ev = self._run(-0.3)
        e = [e for e in ev if e.startswith("corr_shock:")][0]
        f = dict(kv.split("=") for kv in e.split(":")[1:])
        self.assertLess(float(f["scale"]), 1.0)                  # diversification assumption was binding
        self.assertLessEqual(float(f["limit"]), 0.30 + 1e-12)

    def test_order_target_vol_before_per_asset_cap(self):
        _, _, ev = self._run(0.2, mu=0.5)
        names = [e.split(":")[0].split("=")[0] for e in ev]
        if "per_asset_cap" in names:
            self.assertLess(names.index("corr_shock"), names.index("per_asset_cap"))


class PyramidRegimes(unittest.TestCase):
    def test_regime_parameters(self):
        r = pyramid_regime_configs()
        self.assertEqual(sorted(r), ["pyramid_1.0x", "pyramid_1.5x", "pyramid_2.0x", "pyramid_2.5x", "pyramid_3.0x"])
        for name, c in r.items():
            cap = float(name.split("_")[1][:-1])
            self.assertEqual((c.gross_cap, c.net_cap, c.per_asset_cap), (cap, cap, cap))
            self.assertAlmostEqual(c.target_volatility, 0.40 * cap)
            self.assertAlmostEqual(c.corr_shock_abs_vol_ceiling, 0.60 * cap)
        self.assertEqual(RiskConfigV2().gross_cap, 1.0)            # general default stays unlevered
        self.assertIsNone(RiskConfigV2().target_volatility)

    def test_regimes_actually_differ_in_leverage(self):
        rng = np.random.default_rng(11)
        z = rng.normal(size=(800, 2)); z[:, 1] = 0.2 * z[:, 0] + np.sqrt(1 - 0.04) * z[:, 1]
        win, ts = _window(z * 0.01, D)                            # about 19% annualized volatility
        mix = _mixture(ts, {"BTC": 0.02, "ETH": 0.02}, D)
        gross = {}
        for name, c in pyramid_regime_configs().items():
            w, _, ev = _parts(LedoitWolfKellyAllocatorV2(c).allocate(mix, win, ("BTC", "ETH")))
            gross[name] = sum(abs(v) for v in w.values())
            self.assertLessEqual(gross[name], c.gross_cap + 1e-12)
            self.assertTrue(any(e.startswith("corr_shock:") for e in ev))
        self.assertLessEqual(gross["pyramid_1.0x"], 1.0 + 1e-12)
        self.assertGreater(gross["pyramid_3.0x"], 2.0)
        vals = [gross[k] for k in sorted(gross)]
        self.assertEqual(vals, sorted(vals))

    def test_target_vol_is_annualized(self):
        rng = np.random.default_rng(5)
        win, ts = _window(rng.normal(0, 0.05, (800, 2)), D)       # about 95% annualized volatility
        c = pyramid_regime_configs()["pyramid_1.0x"]
        _, _, ev = _parts(LedoitWolfKellyAllocatorV2(c).allocate(_mixture(ts, {"BTC": 0.05, "ETH": 0.05}, D),
                                                                 win, ("BTC", "ETH")))
        self.assertTrue(any(e.startswith("vol_target_annualized:") for e in ev))


if __name__ == "__main__":
    unittest.main()
