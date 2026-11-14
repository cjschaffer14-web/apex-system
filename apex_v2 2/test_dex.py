import math
import unittest

from .dex import (DexGovernor, Pool, best_opportunity, compose, cycle_templates,
                  optimal_input, run_path)
from .dex_backtest import run


def pools():
    return [Pool("a", "WETH", "USDC", 1000.0, 3_000_000.0, 0.003),
            Pool("b", "WETH", "USDC", 1000.0, 3_090_000.0, 0.003)]  # 3% richer


class DexTests(unittest.TestCase):
    def test_compose_matches_sequential(self):
        p = pools()
        hops = [(p[0], "WETH"), (p[1], "USDC")]
        A, B, C = compose(hops)
        for t in (0.01, 1.0, 20.0):
            self.assertAlmostEqual(A * t / (B + C * t), run_path(hops, t), places=9)

    def test_closed_form_is_optimal(self):
        p = pools()
        hops = [(p[0], "WETH"), (p[1], "USDC")]  # WETH->USDC on a? a pays 3000, b pays 3090 per WETH
        hops = [(p[1], "WETH"), (p[0], "USDC")]  # sell WETH on the richer pool b, buy back on a
        t, g = optimal_input(hops)
        self.assertGreater(g, 0)
        best = max(run_path(hops, x) - x for x in [t * (0.5 + i / 100) for i in range(101)])
        self.assertAlmostEqual(g, best, delta=1e-6 * max(1.0, g) + 1e-9) if best <= g + 1e-9 else self.fail("grid beat closed form")

    def test_unprofitable_direction_returns_zero(self):
        p = pools()
        self.assertEqual(optimal_input([(p[0], "WETH"), (p[1], "USDC")]), (0.0, 0.0))

    def test_templates_and_best(self):
        p = pools()
        tpl = cycle_templates(p, "WETH", 3)
        self.assertEqual(len(tpl), 2)  # two directions over the two parallel pools
        opp = best_opportunity(p, tpl)
        self.assertIsNotNone(opp)
        self.assertGreater(opp.gross, 0)

    def test_governor_bids_more_under_competition_and_skips_dust(self):
        g = DexGovernor(seed=1)
        for blk in range(60):
            g.observe(blk, [0.5, 0.8, 0.9])  # heavy competition
        calm = DexGovernor(seed=1)
        for blk in range(60):
            calm.observe(blk, [])
        ok_h, b_h, _ = g.decide(60, 0.05, 0.004)
        ok_c, b_c, _ = calm.decide(60, 0.05, 0.004)
        self.assertGreaterEqual(b_h, b_c)
        ok_d, _, ev = g.decide(60, 0.003, 0.004)  # gross below gas
        self.assertFalse(ok_d)

    def test_p_win_monotone_in_bid(self):
        g = DexGovernor()
        for blk in range(50):
            g.observe(blk, [0.3, 0.6])
        ps = [g.p_win(b / 10, 2.0) for b in range(10)]
        self.assertEqual(ps, sorted(ps))

    def test_backtest_smoke(self):
        pnl, won, traded, opps = run(3000, "l1", 1, warmup=100)
        self.assertEqual(len(pnl), 4)
        self.assertTrue(all(math.isfinite(x) for v in pnl.values() for x in v))


if __name__ == "__main__":
    unittest.main()
