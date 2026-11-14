"""Synthetic DEX cyclic-arbitrage backtest (4 pools, 3 tokens, priority-auction competition).

SYNTHETIC: pools, noise flow, competitor arrivals and bids are all my assumptions. The test
checks mechanics and compares bidding policies under the *same* competitor draws. It does not
estimate real profit. Replace `Market` with replayed on-chain reserves (per-block pool state
from event logs) and observed competitor bundles to get a real number.

World per block:
  1. fair prices move (WETH, WBTC in USDC);
  2. random noise swaps hit pools (heavy-tailed sizes) -> cross-pool dislocations;
  3. we find the best WETH cycle (closed-form size); competitors (Poisson, regime-switching,
     only if gross > their gas) arrive with Beta-distributed bid fractions;
  4. each strategy settles against those same competitors;
  5. the cycle is executed by someone and pools are pulled back to within their fee band of fair
     (state evolution is identical for every strategy).

    python3 -m apex_v2.dex_backtest --blocks 100000 --scenario l1
"""
from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .backtest import stats
from .dex import (DexGovernor, Pool, best_opportunity, cycle_templates, gas_cost)

ETH_USD = 3000.0
SCENARIOS = {
    # gas median (gwei), competitor arrivals/block calm, hot
    "l1": dict(gas=3.0, lam_calm=0.4, lam_hot=3.0),
    "l2": dict(gas=0.02, lam_calm=1.0, lam_hot=6.0),
}


def make_pools(p_eth: float, p_btc: float) -> List[Pool]:
    d = 10e6  # $ per side
    return [
        Pool("WU5", "WETH", "USDC", d / p_eth, d, 0.0005),
        Pool("WU30", "WETH", "USDC", d / p_eth, d, 0.003),
        Pool("UB30", "USDC", "WBTC", d, d / p_btc, 0.003),
        Pool("WB30", "WETH", "WBTC", d / p_eth, d / p_btc, 0.003),
    ]


def pull_to_fair(pool: Pool, price: Dict[str, float]) -> None:
    """CEX-DEX arbitrage: clamp pool price into [fair(1-fee), fair/(1-fee)] keeping k."""
    fair = price[pool.t0] / price[pool.t1]          # t1 per t0
    cur = pool.r1 / pool.r0
    lo, hi = fair * (1 - pool.fee), fair / (1 - pool.fee)
    tgt = min(max(cur, lo), hi)
    if tgt != cur:
        k = pool.r0 * pool.r1
        pool.r0, pool.r1 = math.sqrt(k / tgt), math.sqrt(k * tgt)


def poisson(rng: random.Random, lam: float) -> int:
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


@dataclass
class Settle:
    trade: bool
    bid: float = 0.0
    public: bool = False


def settle(s: Settle, gross: float, gas_land: float, comp_bids: List[float]) -> Tuple[float, bool]:
    """(pnl in WETH, auction won)."""
    if not s.trade:
        return 0.0, False
    if all(s.bid > cb for cb in comp_bids):
        return gross * (1 - s.bid) - gas_land, True
    return (-0.6 * gas_land if s.public else 0.0), False


def run(blocks: int, scenario: str, seed: int, warmup: int = 500):
    sc = SCENARIOS[scenario]
    rng = random.Random(seed)
    price = {"USDC": 1.0, "WETH": ETH_USD, "WBTC": 60000.0}
    pools = make_pools(price["WETH"], price["WBTC"])
    tpl = cycle_templates(pools, "WETH", 3)
    gov = DexGovernor(public=False, seed=seed)
    names = ["naive public (bid 0, edge>0)", "gas-aware public (bid 20%)",
             "private bundle (fixed bid 70%)", "governed bundle (EV-optimal bid)"]
    pnl: Dict[str, List[float]] = {n: [] for n in names}
    won = {n: 0 for n in names}
    traded = {n: 0 for n in names}
    hot, opps = False, 0
    sigma = 0.6 * math.sqrt(12 / 31.5e6)

    for blk in range(blocks):
        z0, z1, z2 = rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)
        price["WETH"] *= math.exp(sigma * (0.8 * z0 + 0.6 * z1))
        price["WBTC"] *= math.exp(sigma * (0.8 * z0 + 0.6 * z2))
        for p in pools:
            if rng.random() < 0.6:  # noise flow, heavy-tailed size as a fraction of reserves
                frac = min(0.02, rng.lognormvariate(math.log(0.0006), 0.9))
                tok = rng.choice([p.t0, p.t1])
                p.swap(tok, frac * p.reserves(tok)[0])

        hot = (rng.random() < 0.92) if hot else (rng.random() < 0.04)
        gwei = sc["gas"] * math.exp(rng.gauss(0, 0.5))
        opp = best_opportunity(pools, tpl)
        comp_bids: List[float] = []
        if opp is not None:
            gl = gas_cost(opp.n_hops, gwei)
            if opp.gross > gl:  # competitors only show up for profitable cycles
                comp_bids = [min(0.99, rng.betavariate(5, 2.5))
                             for _ in range(poisson(rng, sc["lam_hot"] if hot else sc["lam_calm"]))]
            if blk >= warmup:
                opps += 1
                gross = opp.gross
                decisions = {
                    names[0]: Settle(True, 0.0, True),
                    names[1]: Settle(gross > 1.2 * gl, 0.20, True),
                    names[2]: Settle(gross > gl, 0.70, False),
                }
                ok, b, _ = gov.decide(blk, gross, gl)
                decisions[names[3]] = Settle(ok, b, False)
                for n, s in decisions.items():
                    p_, w = settle(s, gross, gl, comp_bids)
                    pnl[n].append(p_)
                    won[n] += w
                    traded[n] += s.trade
            # state restored: the cycle is executed by someone (us or a competitor)
            if opp.gross > gl:
                t = opp.size
                for pool, tok in opp.hops:
                    t = pool.swap(tok, t)
        gov.observe(blk, comp_bids)
        for p in pools:
            pull_to_fair(p, price)
    return pnl, won, traded, opps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=100000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="l1")
    a = ap.parse_args()
    agg: Dict[str, list] = {}
    tot_opps = 0
    for seed in range(1, a.seeds + 1):
        pnl, won, traded, opps = run(a.blocks, a.scenario, seed)
        tot_opps += opps
        for n in pnl:
            s = stats(pnl[n])
            agg.setdefault(n, []).append((s, won[n], traded[n]))
    sc = SCENARIOS[a.scenario]
    print(f"SYNTHETIC DEX backtest | scenario={a.scenario} gas~{sc['gas']}gwei "
          f"competitors/block calm={sc['lam_calm']} hot={sc['lam_hot']} | blocks={a.blocks} x {a.seeds} seeds "
          f"| opportunities/seed={tot_opps/a.seeds:.0f}")
    print(f"{'strategy':36}{'trades':>8}{'land%':>7}{'total $':>10}{'$/trade':>9}{'t-stat':>8}{'maxDD $':>9}{'seeds+':>8}")
    for n, rows in agg.items():
        m = lambda f: sum(f(r) for r in rows) / len(rows)
        landed = sum(r[1] for r in rows) / max(1, sum(r[2] for r in rows))
        print(f"{n:36}{m(lambda r: r[2]):8.0f}{100*landed:7.1f}{ETH_USD*m(lambda r: r[0].total):10.0f}"
              f"{ETH_USD*m(lambda r: r[0].mean):9.2f}{m(lambda r: r[0].tstat):8.2f}"
              f"{ETH_USD*m(lambda r: r[0].max_dd):9.0f}{sum(r[0].total > 0 for r in rows):5d}/{len(rows)}")


if __name__ == "__main__":
    main()
