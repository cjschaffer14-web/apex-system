"""Atomic cyclic arbitrage on constant-product (Uniswap-v2 style) pools.

Academic basis
  * Angeris, Chitra et al., "An analysis of Uniswap markets" / "Optimal routing for constant
    function market makers": a path of CPMM swaps composes to f(t) = A t / (B + C t), so the
    optimal input is closed form  t* = (sqrt(AB) - B) / C  (profitable iff A > B).
  * Daian et al., "Flash Boys 2.0": arbitrageurs compete in a priority auction; value leaks to
    whoever controls ordering (here: a bid = fraction of gross profit paid to the builder).
  * Bidding model: competitors arrive Poisson(lam) per block with bid fractions ~ F (estimated
    online from observed winning/competing bids). Win iff our bid beats all of them:
        P_win(b) = exp(-lam * (1 - F(b))).
    lam comes from an exponential-kernel Hawkes process over past blocks (HawkesIntensity).

Atomic execution: a failed cycle reverts, so there is no leg risk and no toxicity module.
With a private bundle a lost auction costs nothing; with the public mempool it costs gas.
All amounts are floats in units of the start token (WETH). Production code must use
integer on-chain math. No transaction is ever signed or sent here.
"""
from __future__ import annotations

import bisect
import math
import random
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Sequence, Tuple

from .governor import HawkesIntensity


@dataclass
class Pool:
    pid: str
    t0: str
    t1: str
    r0: float
    r1: float
    fee: float  # e.g. 0.003

    def other(self, token: str) -> str:
        return self.t1 if token == self.t0 else self.t0

    def reserves(self, token_in: str) -> Tuple[float, float]:
        return (self.r0, self.r1) if token_in == self.t0 else (self.r1, self.r0)

    def out(self, token_in: str, dx: float) -> float:
        rin, rout = self.reserves(token_in)
        g = 1.0 - self.fee
        return g * rout * dx / (rin + g * dx)

    def swap(self, token_in: str, dx: float) -> float:
        dy = self.out(token_in, dx)
        if token_in == self.t0:
            self.r0 += dx
            self.r1 -= dy
        else:
            self.r1 += dx
            self.r0 -= dy
        return dy


Hop = Tuple[Pool, str]  # (pool, token_in)


def compose(hops: Sequence[Hop]) -> Tuple[float, float, float]:
    """f(t) = A t / (B + C t) for the whole path."""
    A, B, C = 1.0, 1.0, 0.0
    for pool, tok in hops:
        rin, rout = pool.reserves(tok)
        g = 1.0 - pool.fee
        a, b, c = g * rout, rin, g
        A, B, C = A * a, B * b, C * b + c * A
    return A, B, C


def optimal_input(hops: Sequence[Hop]) -> Tuple[float, float]:
    """(t*, gross profit) in start-token units; (0, 0) if the cycle is not profitable."""
    A, B, C = compose(hops)
    if A <= B or C <= 0:
        return 0.0, 0.0
    t = (math.sqrt(A * B) - B) / C
    return t, A * t / (B + C * t) - t


def run_path(hops: Sequence[Hop], t: float) -> float:
    for pool, tok in hops:
        t = pool.out(tok, t)
    return t


def cycle_templates(pools: Sequence[Pool], start: str, max_hops: int = 3) -> List[List[Tuple[int, str]]]:
    """All pool-simple cycles from `start` of length 2..max_hops, as (pool_index, token_in)."""
    out: List[List[Tuple[int, str]]] = []

    def dfs(tok: str, used: Tuple[int, ...], path: List[Tuple[int, str]]):
        for i, p in enumerate(pools):
            if i in used or tok not in (p.t0, p.t1):
                continue
            nxt = p.other(tok)
            step = path + [(i, tok)]
            if nxt == start and len(step) >= 2:
                out.append(step)
            elif len(step) < max_hops:
                dfs(nxt, used + (i,), step)

    dfs(start, (), [])
    return out


@dataclass
class Opportunity:
    hops: List[Hop]
    size: float
    gross: float
    n_hops: int


def best_opportunity(pools: Sequence[Pool], templates) -> Optional[Opportunity]:
    best = None
    for tpl in templates:
        hops = [(pools[i], tok) for i, tok in tpl]
        t, g = optimal_input(hops)
        if g > 0 and (best is None or g > best.gross):
            best = Opportunity(hops, t, g, len(hops))
    return best


def gas_units(n_hops: int) -> int:
    return 120_000 + 110_000 * n_hops  # base + flash-loan overhead + per swap


def gas_cost(n_hops: int, gas_price_gwei: float) -> float:
    return gas_units(n_hops) * gas_price_gwei * 1e-9  # in ETH == WETH


class DexGovernor:
    """Chooses whether to bid and how much, maximising EV of the priority auction."""

    def __init__(self, window_blocks: int = 50, beta: float = 1.0, branching: float = 0.3,
                 prior_rate: float = 0.2, public: bool = False, fail_gas_frac: float = 0.6,
                 min_ev: float = 0.0, seed: int = 0, max_bids: int = 3000):
        self.W, self.beta, self.b, self.prior = window_blocks, beta, branching, prior_rate
        self.public, self.fail_frac, self.min_ev = public, fail_gas_frac, min_ev
        self.events: Deque[int] = deque()
        self.bids: List[float] = []
        self.max_bids = max_bids
        self.rng = random.Random(seed)
        self.grid = [i / 100 for i in range(0, 100, 2)]

    def observe(self, block: int, competitor_bids: Sequence[float]) -> None:
        for bid in competitor_bids:
            self.events.append(block)
            bisect.insort(self.bids, bid)
            if len(self.bids) > self.max_bids:
                self.bids.pop(self.rng.randrange(len(self.bids)))
        while self.events and self.events[0] < block - self.W:
            self.events.popleft()

    def rate(self, block: int) -> float:
        """Competitor arrivals per block (Hawkes intensity at `block`, floored at the prior)."""
        base = len(self.events) / self.W
        h = HawkesIntensity(max(base, self.prior) * (1 - self.b), self.b * self.beta, self.beta)
        for e in self.events:
            h.observe(float(e))
        return max(h.intensity(float(block)), self.prior)

    def cdf(self, b: float) -> float:
        if not self.bids:
            return b  # uninformed prior: competitors bid U(0,1)
        return bisect.bisect_left(self.bids, b) / len(self.bids)

    def p_win(self, b: float, lam: float) -> float:
        return math.exp(-lam * (1.0 - self.cdf(b)))

    def decide(self, block: int, gross: float, gas_land: float) -> Tuple[bool, float, float]:
        """Returns (approve, bid_fraction, ev)."""
        lam = self.rate(block)
        fail = self.fail_frac * gas_land if self.public else 0.0
        best_ev, best_b = -math.inf, 0.0
        for b in self.grid:
            p = self.p_win(b, lam)
            ev = p * (gross * (1 - b) - gas_land) - (1 - p) * fail
            if ev > best_ev:
                best_ev, best_b = ev, b
        return best_ev > self.min_ev, best_b, best_ev
