"""Replay a recorded Kraken v2 feed through the screener + governor.

Method (no simulated competitors, no assumed toxicity):
  * rebuild the 3 books from snapshots/updates; keep a timeline of book states;
  * at each decision point, find the best triangular cycle from the books as of that instant;
  * strategy decides (naive / threshold / governed);
  * execution: leg k hits the book as it stands at t + k*latency, as a fill-or-kill order
    limited to the price level the plan touched (IOC at the decision-time worst price).
    If a leg cannot fill in full, the already-filled legs are unwound at that time's
    books, paying spread + fees. Price moves and snipes therefore show up in the data.

Limits (read before trusting numbers):
  * passive replay: our orders do not move the book, and fills inside the latency window are
    not queue-position modelled (optimistic when the market is thick, pessimistic via FOK
    when it moves);
  * the toxicity model has no reference venue here (divergence = 0) and is NOT fitted;
    only |trade-flow imbalance| informs it, with prior weights;
  * short recordings give few opportunities: look at t-stats and trade counts.

    python3 -m apex_v2.replay data/kraken.log --fee 0.0026 --latency-ms 40 --notional 1000
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from .core import Book, Leg, Level, best_cycle, simulate_cycle, walk_buy, walk_sell
from .backtest import CYCLES, V, stats
from .governor import GovernorConfig, Observation, PredictiveGovernor, ToxicityModel

SYMS = ["BTC/USD", "ETH/USD", "ETH/BTC"]
KCYCLES = [[Leg(V, l.pair, l.side) for l in c] for c in CYCLES]  # same triangle, venue tag V
DEPTH = 10


class Timeline:
    def __init__(self):
        self.t: List[int] = []                       # ns, book-state change times
        self.state: List[Dict[str, Tuple[tuple, tuple]]] = []
        self.msg_t: List[int] = []                   # every message (heartbeat/book/trade)
        self.trades: List[Tuple[int, str, str, float]] = []  # (t, sym, side, usd-ish qty)
        self.trade_t: List[int] = []

    def at(self, t_ns: int):
        i = bisect.bisect_right(self.t, t_ns) - 1
        return self.state[i] if i >= 0 else None

    def last_msg_age_ms(self, t_ns: int) -> float:
        i = bisect.bisect_right(self.msg_t, t_ns) - 1
        return (t_ns - self.msg_t[i]) / 1e6 if i >= 0 else math.inf


def load(path: str) -> Timeline:
    tl = Timeline()
    sides: Dict[str, Dict[str, Dict[float, float]]] = {s: {"b": {}, "a": {}} for s in SYMS}
    ready = set()
    cur: Dict[str, Tuple[tuple, tuple]] = {}
    with open(path) as f:
        for line in f:
            ts, _, raw = line.partition("\t")
            try:
                t, m = int(ts), json.loads(raw)
            except ValueError:
                continue
            ch = m.get("channel")
            if ch not in ("book", "trade", "heartbeat") or "data" not in m and ch != "heartbeat":
                continue
            tl.msg_t.append(t)
            if ch == "trade":
                for d in m["data"]:
                    tl.trades.append((t, d["symbol"], d["side"], float(d["qty"]) * float(d["price"])))
                    tl.trade_t.append(t)
                continue
            if ch != "book":
                continue
            for d in m["data"]:
                sym = d["symbol"]
                if sym not in sides:
                    continue
                if m["type"] == "snapshot":
                    sides[sym] = {"b": {}, "a": {}}
                for key, lst in (("b", d.get("bids", [])), ("a", d.get("asks", []))):
                    for lv in lst:
                        p, q = float(lv["price"]), float(lv["qty"])
                        if q == 0:
                            sides[sym][key].pop(p, None)
                        else:
                            sides[sym][key][p] = q
                # Kraken v2 only guarantees the top-`depth` window: truncate the *stored* book
                # (not just the output) and drop opposite-side levels a fresh quote crosses,
                # otherwise stale levels resurface and the book stays crossed.
                for key, lst in (("b", d.get("bids", [])), ("a", d.get("asks", []))):
                    for lv in lst:
                        if float(lv["qty"]) == 0:
                            continue
                        p = float(lv["price"])
                        other = sides[sym]["a" if key == "b" else "b"]
                        for q in [x for x in other if (x <= p if key == "b" else x >= p)]:
                            del other[q]
                kb = sorted(sides[sym]["b"].items(), reverse=True)[:DEPTH]
                ka = sorted(sides[sym]["a"].items())[:DEPTH]
                sides[sym]["b"], sides[sym]["a"] = dict(kb), dict(ka)
                bids, asks = tuple(kb), tuple(ka)
                if not bids or not asks:
                    continue
                cur = dict(cur)
                cur[sym] = (bids, asks)
                ready.add(sym)
                if len(ready) == len(SYMS):
                    tl.t.append(t)
                    tl.state.append(cur)
    return tl


def book_from(state, sym: str, t_ns: int) -> Book:
    bids, asks = state[sym]
    mk = lambda lv: [Level(Decimal(repr(p)), Decimal(repr(q))) for p, q in lv]
    return Book(V, sym, mk(bids), mk(asks), t_ns)


def books_from(state, t_ns: int):
    return {(V, s): book_from(state, s, t_ns) for s in SYMS}


def flow(tl: Timeline, t: int, sym: str, window_s: float = 3.0) -> float:
    lo = bisect.bisect_left(tl.trade_t, t - int(window_s * 1e9))
    hi = bisect.bisect_right(tl.trade_t, t)
    buy = sell = 0.0
    for _, s, side, usd in tl.trades[lo:hi]:
        if s == sym:
            if side == "buy":
                buy += usd
            else:
                sell += usd
    tot = buy + sell
    return (buy - sell) / tot if tot else 0.0


def execute(tl: Timeline, t0: int, legs, plan, notional: Decimal, fee: Decimal, latency_ms: float):
    """Return realized USD P&L of running `plan` with sequential FOK legs at t0 + k*latency."""
    amount, done = notional, []
    for k, (leg, pf) in enumerate(zip(legs, plan.fills), 1):
        te = t0 + int(k * latency_ms * 1e6)
        st = tl.at(te)
        if st is None:
            return None
        book = book_from(st, leg.pair, te)
        w = (walk_buy(book.asks, amount, pf.worst_price) if leg.side == "buy"
             else walk_sell(book.bids, amount, pf.worst_price))
        if w is None:  # snipe/move: unwind what we hold at this instant's books
            return _unwind(st, te, done, amount, notional, fee)
        out = w[0] * (1 - fee)
        done.append((leg, out))
        amount = out
    return amount - notional


def _unwind(st, te, done, held: Decimal, notional: Decimal, fee: Decimal):
    for leg, _ in reversed(done):
        book = book_from(st, leg.pair, te)
        if leg.side == "buy":      # we hold base, sell it back
            w = walk_sell(book.bids, held)
            got = (w[0] if w else held * book.bids[0].price * Decimal("0.995")) * (1 - fee)
        else:                      # we hold quote, buy base back
            w = walk_buy(book.asks, held)
            got = (w[0] if w else held / book.asks[0].price * Decimal("0.995")) * (1 - fee)
        held = got
    return held - notional if done else Decimal(0)


def run(path: str, fee: float, latency_ms: float, notional: float, decision_ms: float,
        cooldown_s: float, sigma: float):
    tl = load(path)
    if len(tl.t) < 10:
        raise SystemExit("not enough book data in file")
    fee_d, N = Decimal(repr(fee)), Decimal(repr(notional))
    fees = {V: fee_d}
    tox = ToxicityModel((-2.0, 2.0, 0.0))  # prior only; not fitted (no reference venue / labels)
    gov = PredictiveGovernor(GovernorConfig(), tox)
    names = ["naive (edge>0)", "threshold (edge>5bps)", "governed"]
    pnls = {n: [] for n in names}
    last_trade = {n: -10**30 for n in names}
    gross_edges: List[float] = []
    cand = 0
    last_dec = -10**30
    dec_ns, cd_ns = int(decision_ms * 1e6), int(cooldown_s * 1e9)

    for t, st in zip(tl.t, tl.state):
        if t - last_dec < dec_ns:
            continue
        last_dec = t
        books = books_from(st, t)
        g0, _ = best_cycle(books, KCYCLES, N, {V: Decimal(0)})   # gross, fee-free
        if g0 is not None:
            gross_edges.append(float(g0.edge_bps))
        res, legs = best_cycle(books, KCYCLES, N, fees)
        if res is None or res.profit_usd <= 0:
            continue
        cand += 1
        hs = statistics.mean(float((b.asks[0].price - b.bids[0].price) / (b.asks[0].price + b.bids[0].price) * 10000)
                             for b in books.values())
        events = [x[0] / 1e9 for x in tl.trades[bisect.bisect_left(tl.trade_t, t - 3_000_000_000):
                                                   bisect.bisect_right(tl.trade_t, t)]]
        obs = Observation(
            notional_usd=notional, profit_usd=float(res.profit_usd), n_legs=3,
            latency_per_leg_ms=latency_ms, book_age_ms=tl.last_msg_age_ms(t),
            sigma_per_sqrt_s=sigma, ofi=max(abs(flow(tl, t, l.pair)) for l in legs),
            ref_divergence_bps=0.0, unwind_bps=hs + fee * 1e4, now_s=t / 1e9,
            taker_event_times_s=events)
        picks = {names[0]: True, names[1]: float(res.edge_bps) > 5,
                 names[2]: gov.decide(obs).approve}
        for n in names:
            if picks[n] and t - last_trade[n] >= cd_ns:
                pnl = execute(tl, t, legs, res, N, fee_d, latency_ms)
                if pnl is not None:
                    pnls[n].append(float(pnl))
                    last_trade[n] = t

    span_min = (tl.t[-1] - tl.t[0]) / 6e10
    print(f"REAL-DATA replay | {path} | {span_min:.1f} min, {len(tl.t)} book states, "
          f"{len(tl.trades)} trades | fee={fee*1e4:.1f}bps/leg latency={latency_ms:g}ms/leg notional=${notional:g}")
    if gross_edges:
        ge = sorted(gross_edges)
        q = lambda p: ge[min(len(ge) - 1, int(p * len(ge)))]
        print(f"fee-free best-cycle edge over {len(ge)} samples (bps): median {q(.5):.2f}  p90 {q(.9):.2f}  "
              f"p99 {q(.99):.2f}  max {ge[-1]:.2f}   | fee hurdle for 3 legs: {3*fee*1e4:.1f} bps")
    print(f"candidates with positive net edge at decision time: {cand}")
    print(f"{'strategy':24}{'trades':>8}{'total $':>10}{'$/trade':>9}{'win%':>7}{'t-stat':>8}{'maxDD $':>9}")
    for n in names:
        s = stats(pnls[n])
        print(f"{n:24}{s.trades:8d}{s.total:10.2f}{s.mean:9.3f}{100*s.win:7.1f}{s.tstat:8.2f}{s.max_dd:9.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--fee", type=float, default=0.0026)
    ap.add_argument("--latency-ms", type=float, default=40.0)
    ap.add_argument("--notional", type=float, default=1000.0)
    ap.add_argument("--decision-ms", type=float, default=100.0)
    ap.add_argument("--cooldown-s", type=float, default=1.0)
    ap.add_argument("--sigma", type=float, default=1e-4)
    a = ap.parse_args()
    run(a.path, a.fee, a.latency_ms, a.notional, a.decision_ms, a.cooldown_s, a.sigma)
