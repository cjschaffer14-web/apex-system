import math
import random
import unittest
from decimal import Decimal as D

from .core import Book, Leg, Level, simulate_cycle, validate_cycle, walk_buy, walk_sell
from .governor import (GovernorConfig, HawkesIntensity, Observation,
                       PredictiveGovernor, ToxicityModel)
from .backtest import SimConfig, gen_trial, realize, run_seed


def book(pair, bid, ask, size="10", age_ns=0):
    return Book("X", pair, [Level(D(bid), D(size))], [Level(D(ask), D(size))], received_ns=age_ns)


class CoreTests(unittest.TestCase):
    def test_walk_buy_spans_levels(self):
        r = walk_buy([Level(D(100), D(1)), Level(D(101), D(1))], D(150))
        self.assertAlmostEqual(float(r[0]), 1 + 50 / 101, places=9)
        self.assertEqual(r[3], 2)

    def test_walk_sell_and_short_depth(self):
        r = walk_sell([Level(D(100), D(1)), Level(D(99), D(1))], D("1.5"))
        self.assertEqual(r[0], D(100) + D("0.5") * D(99))
        self.assertIsNone(walk_sell([Level(D(100), D(1))], D(2)))

    def test_validate_cycle(self):
        ok = [Leg("X", "BTC/USD", "buy"), Leg("X", "BTC/USD", "sell")]
        self.assertIsNone(validate_cycle(ok))
        self.assertIn("ends in", validate_cycle(ok[:1]))
        self.assertIn("needs", validate_cycle([Leg("X", "BTC/USD", "sell")]))

    def test_round_trip_costs_spread_and_fees(self):
        books = {("X", "BTC/USD"): book("BTC/USD", "99", "100")}
        legs = [Leg("X", "BTC/USD", "buy"), Leg("X", "BTC/USD", "sell")]
        res, err = simulate_cycle(books, legs, D(100), {"X": D("0.001")})
        self.assertIsNone(err)
        self.assertAlmostEqual(float(res.end_usd), 100 / 100 * 0.999 * 99 * 0.999, places=6)
        self.assertLess(res.profit_usd, 0)

    def test_triangle_profit_with_correct_sides(self):
        # USD->BTC (ask 100) ; BTC->ETH via ETH/BTC ask 0.1 ; ETH->USD bid 1100 => 1 BTC -> 10 ETH -> 11000? scale
        books = {
            ("X", "BTC/USD"): book("BTC/USD", "99", "100"),
            ("X", "ETH/BTC"): book("ETH/BTC", "0.0099", "0.01", size="1000"),
            ("X", "ETH/USD"): book("ETH/USD", "1.1", "1.2", size="1000"),
        }
        legs = [Leg("X", "BTC/USD", "buy"), Leg("X", "ETH/BTC", "buy"), Leg("X", "ETH/USD", "sell")]
        res, err = simulate_cycle(books, legs, D(100), {"X": D(0)})
        self.assertIsNone(err)
        self.assertAlmostEqual(float(res.end_usd), 100 / 100 / 0.01 * 1.1, places=6)

    def test_stale_rejected(self):
        books = {("X", "BTC/USD"): book("BTC/USD", "99", "100", age_ns=0)}
        legs = [Leg("X", "BTC/USD", "buy"), Leg("X", "BTC/USD", "sell")]
        res, err = simulate_cycle(books, legs, D(10), {}, now_ns=int(1e9), max_age_ms=250)
        self.assertIsNone(res)
        self.assertIn("stale", err)


class GovernorTests(unittest.TestCase):
    def test_hawkes_decay_and_stability(self):
        h = HawkesIntensity(1.0, 2.0, 5.0)
        h.observe(0.0)
        self.assertAlmostEqual(h.intensity(0.0), 3.0)
        self.assertAlmostEqual(h.intensity(1.0), 1.0 + 2.0 * math.exp(-5.0))
        self.assertAlmostEqual(h.stationary_rate, 1.0 / (1 - 0.4))
        with self.assertRaises(ValueError):
            HawkesIntensity(1.0, 5.0, 5.0)

    def obs(self, **kw):
        base = dict(notional_usd=5000, profit_usd=10.0, n_legs=3, latency_per_leg_ms=40,
                    book_age_ms=10, sigma_per_sqrt_s=1e-4, ofi=0.0, ref_divergence_bps=0.0,
                    unwind_bps=5.0, now_s=3.0, taker_event_times_s=[])
        base.update(kw)
        return Observation(**base)

    def test_approves_clean_trade_and_rejects_stale(self):
        g = PredictiveGovernor(tox_model=ToxicityModel((-4.0, 0.0, 0.0)))
        self.assertTrue(g.decide(self.obs()).approve)
        d = g.decide(self.obs(book_age_ms=400))
        self.assertFalse(d.approve)
        self.assertTrue(any("stale" in r for r in d.reasons))

    def test_ev_falls_with_latency_and_competition(self):
        g = PredictiveGovernor(GovernorConfig(min_p_survive=0.0, min_ev_bps=-1e9),
                               ToxicityModel((-4.0, 0.0, 0.0)))
        slow = g.decide(self.obs(latency_per_leg_ms=400)).ev_usd
        fast = g.decide(self.obs(latency_per_leg_ms=10)).ev_usd
        self.assertLess(slow, fast)
        busy = g.decide(self.obs(taker_event_times_s=[2.0 + i * 0.02 for i in range(50)])).ev_usd
        self.assertLess(busy, fast)

    def test_no_events_uses_prior_rate(self):
        g = PredictiveGovernor()
        self.assertAlmostEqual(g.competitor_rate([], 3.0), g.cfg.prior_rate)

    def test_toxicity_fit_separates_classes(self):
        rng = random.Random(0)
        data = [(abs(rng.gauss(0.6, 0.2)), abs(rng.gauss(8, 3)), True) for _ in range(300)]
        data += [(abs(rng.gauss(0.1, 0.1)), abs(rng.gauss(0, 2)), False) for _ in range(300)]
        m = ToxicityModel()
        m.fit(data)
        self.assertGreater(m.predict(0.7, 9), 0.8)
        self.assertLess(m.predict(0.05, 0.5), 0.2)


class BacktestTests(unittest.TestCase):
    def test_realize_and_run_smoke(self):
        cfg = SimConfig()
        rng = random.Random(1)
        for _ in range(50):
            realize(gen_trial(rng, cfg), cfg)
        out = run_seed(1, 1500, cfg)
        self.assertEqual(len(out), 3)

    def test_governed_filters_toxic_when_signal_exists(self):
        out = run_seed(2, 6000, SimConfig(signal=1.0))
        gov = [v for k, v in out.items() if k.startswith("governed")][0]
        naive = out["naive (edge>0)"]
        self.assertGreater(gov.mean, naive.mean)


if __name__ == "__main__":
    unittest.main()
