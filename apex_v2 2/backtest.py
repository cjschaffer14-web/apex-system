"""Synthetic backtest harness: naive screener vs thresholded vs governed.

READ THIS: no real market data is available here, so this is a *simulation*
with a known data-generating process (toxic dislocations, competitor sniping,
ghost quotes). It demonstrates that the mechanics work and that the governor
helps *when its inputs carry information*; `--signal 0` removes that
information as a null test. It says nothing about live profitability. To get
that, replay recorded L2 books + trades through `simulate_cycle` and
`PredictiveGovernor.decide`, using this file's `realize()` replaced by actual
fills.

Run from the 'APEX System' folder:  python3 -m apex_v2.backtest --trials 20000 --seeds 5
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

from .core import Book, CycleResult, Leg, Level, best_cycle
from .governor import GovernorConfig, Observation, PredictiveGovernor, ToxicityModel

V = "X"
CYCLES = [
    [Leg(V, "BTC/USD", "buy"), Leg(V, "ETH/BTC", "buy"), Leg(V, "ETH/USD", "sell")],
    [Leg(V, "ETH/USD", "buy"), Leg(V, "ETH/BTC", "sell"), Leg(V, "BTC/USD", "sell")],
]
NOW_NS = 10**18


@dataclass
class SimConfig:
    p_hot: float = 0.30
    lam_calm: float = 1.0          # competitor snipes / second
    lam_hot: float = 10.0
    p_toxic: float = 0.40
    mean_dislocation_bps: float = 12.0
    p_stale: float = 0.05          # quotes that look dislocated but are ghosts
    latency_leg_ms: float = 40.0
    notional: float = 5000.0
    fee: float = 0.0004
    half_spread_bps: float = 1.0
    sigma: float = 1e-4
    signal: float = 1.0            # 0 => observables carry no information


@dataclass
class Trial:
    toxic: bool
    stale: bool
    delta_bps: float
    t_comp: float                  # seconds until a competitor kills the level
    result: Optional[CycleResult]
    obs: Optional[Observation]
    noise: float                   # standard normal, shared across strategies


def _book(pair: str, mid: float, base_usd: float, hs_bps: float, age_ms: float) -> Book:
    size = Decimal(repr(100_000.0 / base_usd))
    bids = [Level(Decimal(repr(mid * (1 - (hs_bps + i) / 1e4))), size) for i in range(3)]
    asks = [Level(Decimal(repr(mid * (1 + (hs_bps + i) / 1e4))), size) for i in range(3)]
    return Book(V, pair, bids, asks, NOW_NS - int(age_ms * 1e6))


def gen_trial(rng: random.Random, cfg: SimConfig) -> Trial:
    hot = rng.random() < cfg.p_hot
    lam = cfg.lam_hot if hot else cfg.lam_calm
    toxic = rng.random() < cfg.p_toxic
    stale = rng.random() < cfg.p_stale
    delta = rng.expovariate(1.0 / cfg.mean_dislocation_bps) * rng.choice([-1, 1])

    btc = 60000.0 * (1 + rng.gauss(0, 0.01))
    eth = 3000.0 * (1 + rng.gauss(0, 0.01))
    ethbtc = eth / btc * (1 + delta / 1e4)
    age = rng.uniform(300, 600) if stale else rng.uniform(0, 40)
    hs = cfg.half_spread_bps
    j = lambda: 1 + rng.gauss(0, 0.3) / 1e4
    books = {
        (V, "BTC/USD"): _book("BTC/USD", btc * j(), btc, hs, age),
        (V, "ETH/USD"): _book("ETH/USD", eth * j(), eth, hs, age),
        (V, "ETH/BTC"): _book("ETH/BTC", ethbtc * j(), eth, hs, age),
    }
    fees = {V: Decimal(repr(cfg.fee))}
    result, _ = best_cycle(books, CYCLES, Decimal(repr(cfg.notional)), fees)

    # Observables the governor sees (informative in proportion to cfg.signal).
    s = cfg.signal
    if toxic:
        ofi = min(1.0, abs(rng.gauss(0.15 + 0.4 * s, 0.25)))
        div = abs(rng.gauss(0.7 * abs(delta) * s, 3.0))
    else:
        ofi = min(1.0, abs(rng.gauss(0.15, 0.25)))
        div = abs(rng.gauss(0.0, 3.0))
    obs_rate = cfg.lam_calm + s * (lam - cfg.lam_calm)
    times, t = [], rng.expovariate(obs_rate)
    while t < 3.0:
        times.append(t)
        t += rng.expovariate(obs_rate)

    obs = None
    if result is not None:
        obs = Observation(
            notional_usd=cfg.notional, profit_usd=float(result.profit_usd), n_legs=3,
            latency_per_leg_ms=cfg.latency_leg_ms, book_age_ms=age, sigma_per_sqrt_s=cfg.sigma,
            ofi=ofi, ref_divergence_bps=div, unwind_bps=hs + cfg.fee * 1e4,
            now_s=3.0, taker_event_times_s=times)
    return Trial(toxic, stale, delta, rng.expovariate(lam), result, obs, rng.gauss(0, 1))


def realize(tr: Trial, cfg: SimConfig) -> float:
    """Ground-truth P&L of taking this trade."""
    n, L = 3, cfg.latency_leg_ms / 1000.0
    unwind = (cfg.half_spread_bps + cfg.fee * 1e4) / 1e4 * cfg.notional
    k_fail = next((k for k in range(1, n + 1) if tr.t_comp <= k * L), None)
    if k_fail == 1:
        return 0.0
    if k_fail:
        return -(k_fail - 1) * unwind + tr.noise * cfg.sigma * math.sqrt(k_fail * L) * cfg.notional
    if tr.stale:  # ghost: the dislocation was not real, you pay spread + fees
        return -n * (cfg.half_spread_bps + cfg.fee * 1e4) / 1e4 * cfg.notional
    pnl = float(tr.result.profit_usd)
    if tr.toxic:  # fair value moved to the quote: the stale legs reprice against you
        pnl -= 1.5 * abs(tr.delta_bps) / 1e4 * cfg.notional
    return pnl + tr.noise * cfg.sigma * math.sqrt(n * L) * cfg.notional


@dataclass
class Stats:
    trades: int
    total: float
    mean: float
    win: float
    tstat: float
    max_dd: float


def stats(pnls: List[float]) -> Stats:
    n = len(pnls)
    if n == 0:
        return Stats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    mean = sum(pnls) / n
    sd = statistics.pstdev(pnls) if n > 1 else 0.0
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return Stats(n, sum(pnls), mean, sum(p > 0 for p in pnls) / n,
                 mean / (sd / math.sqrt(n)) if sd > 0 else 0.0, dd)


def run_seed(seed: int, n_trials: int, cfg: SimConfig):
    rng = random.Random(seed)
    trials = [gen_trial(rng, cfg) for _ in range(n_trials)]
    split = int(n_trials * 0.3)
    train, test = trials[:split], trials[split:]

    # Fit toxicity on train candidates (live: ex-post labels from price after the window).
    tox = ToxicityModel()
    tox.fit([(t.obs.ofi, t.obs.ref_divergence_bps, t.toxic)
             for t in train if t.obs and t.obs.profit_usd > 0])

    def governed(min_ev_bps: float) -> Callable[[Trial], bool]:
        gov = PredictiveGovernor(GovernorConfig(min_ev_bps=min_ev_bps), tox)
        return lambda t: t.obs is not None and gov.decide(t.obs).approve

    strategies: Dict[str, Callable[[Trial], bool]] = {
        "naive (edge>0)": lambda t: t.result is not None and t.result.profit_usd > 0,
        "threshold (edge>5bps)": lambda t: t.result is not None and float(t.result.edge_bps) > 5,
    }
    # Choose the governor's EV threshold on TRAIN only.
    grid = [0.0, 1.0, 2.0, 4.0, 6.0]
    best = max(grid, key=lambda g: sum(realize(t, cfg) for t in train if governed(g)(t)))
    strategies[f"governed (EV>{best:g}bps)"] = governed(best)

    return {name: stats([realize(t, cfg) for t in test if pick(t)])
            for name, pick in strategies.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--signal", type=float, default=1.0)
    ap.add_argument("--fee", type=float, default=0.0004, help="taker fee per leg (0.0004 = 4bps)")
    a = ap.parse_args()
    cfg = SimConfig(signal=a.signal, fee=a.fee)
    agg: Dict[str, List[Stats]] = {}
    for seed in range(1, a.seeds + 1):
        for name, st in run_seed(seed, a.trials, cfg).items():
            key = name.split(" (EV")[0] if name.startswith("governed") else name
            agg.setdefault(key, []).append(st)
    print(f"SYNTHETIC backtest | signal={a.signal} fee={a.fee*1e4:.1f}bps/leg "
          f"trials={a.trials} seeds={a.seeds} (70% out-of-sample)")
    print(f"{'strategy':24}{'trades':>8}{'total $':>11}{'$/trade':>9}{'win%':>7}{'t-stat':>8}{'maxDD $':>10}{'seeds+':>8}")
    for name, sts in agg.items():
        m = lambda f: sum(f(s) for s in sts) / len(sts)
        print(f"{name:24}{m(lambda s: s.trades):8.0f}{m(lambda s: s.total):11.0f}"
              f"{m(lambda s: s.mean):9.3f}{100*m(lambda s: s.win):7.1f}{m(lambda s: s.tstat):8.2f}"
              f"{m(lambda s: s.max_dd):10.0f}{sum(s.total > 0 for s in sts):5d}/{len(sts)}")


if __name__ == "__main__":
    main()
