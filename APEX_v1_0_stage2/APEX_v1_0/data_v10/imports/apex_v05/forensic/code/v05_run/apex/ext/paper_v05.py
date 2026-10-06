"""v0.5 paper trading (owner decision 2, 2 Oct 2026): no money, real prices, real out-of-sample evidence.

Two paper books run side by side so the venue question is answered by evidence, not argument:
  perps_long_short   US perpetual-futures costs (~6 bps per unit of turnover), long and short
  spot_long_only     Kraken Pro tier-1 taker costs (85 bps), long only

Each rebalance is a governed action on the `market.paper_order` capability (it needs that lease). Fills use the
latest public daily close plus the venue's cost; nothing is sent to any exchange. Every rebalance and daily mark
is a ledger event, so the books rebuild exactly after a restart (persistent memory) and the paper track record is
auditable. The paper record feeds the evidence ledger; it is the demonstration the owner asked for before live.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any

PAPER_START_EQUITY = 100_000.0          # notional, in USD; paper only


@dataclass
class PaperBook:
    name: str
    cost_bps: float
    long_short: bool
    equity: float = PAPER_START_EQUITY
    weights: dict = field(default_factory=dict)       # product -> fraction of equity (negative = short)
    last_prices: dict = field(default_factory=dict)
    last_day: int | None = None
    daily: list = field(default_factory=list)         # (day, return) after costs
    rebalances: int = 0
    costs_paid: float = 0.0

    def mark(self, prices: dict[str, float], day: int) -> float | None:
        """Mark to market at today's closes. Returns today's book return, or None if nothing to mark."""
        if self.last_day is not None and day <= self.last_day:
            return None
        r = 0.0
        if self.weights and self.last_prices:
            for p, w in self.weights.items():
                if p in prices and p in self.last_prices and self.last_prices[p] > 0:
                    r += w * (prices[p] / self.last_prices[p] - 1)
        self.equity *= 1 + r
        # weights drift with prices; renormalize the long/short exposures to today's equity
        if self.weights:
            gross_before = sum(abs(w) for w in self.weights.values())
            self.weights = {p: w * (prices.get(p, self.last_prices.get(p, 1)) / self.last_prices.get(p, 1)) / (1 + r)
                            for p, w in self.weights.items() if self.last_prices.get(p)}
            if gross_before == 0:
                self.weights = {}
        self.last_prices = {**self.last_prices, **prices}
        if self.last_day is not None:
            self.daily.append((day, r))
        self.last_day = day
        return r

    def rebalance(self, target: dict[str, float], prices: dict[str, float], day: int) -> dict:
        target = {p: w for p, w in target.items() if p in prices and (self.long_short or w > 0)}
        turnover = sum(abs(target.get(p, 0.0) - self.weights.get(p, 0.0)) for p in set(target) | set(self.weights))
        cost = turnover * self.cost_bps / 1e4
        self.equity *= 1 - cost
        self.costs_paid += cost * self.equity
        self.weights = dict(target)
        self.last_prices = {**self.last_prices, **prices}
        self.rebalances += 1
        if self.daily and self.daily[-1][0] == day:
            d, r = self.daily[-1]
            self.daily[-1] = (d, (1 + r) * (1 - cost) - 1)
        elif cost:
            self.daily.append((day, -cost))            # the record includes every cost paid, from the first trade
        if self.last_day is None:
            self.last_day = day
        return {"book": self.name, "day": day, "turnover": round(turnover, 4), "cost": round(cost, 6),
                "weights": {p: round(w, 5) for p, w in target.items()}, "equity": round(self.equity, 2)}

    def stats(self) -> dict:
        rs = [r for _, r in self.daily]
        sharpe = mean(rs) / pstdev(rs) * math.sqrt(365) if len(rs) > 2 and pstdev(rs) > 0 else 0.0
        peak, mdd, eq = 1.0, 0.0, 1.0
        for r in rs:
            eq *= 1 + r
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
        t = sharpe * math.sqrt(len(rs) / 365) if rs else 0.0
        return {"book": self.name, "days": len(rs), "equity": round(self.equity, 2),
                "return": round(self.equity / PAPER_START_EQUITY - 1, 4), "sharpe": round(sharpe, 3),
                "t_stat": round(t, 2), "max_drawdown": round(mdd, 4), "rebalances": self.rebalances,
                "gross_exposure": round(sum(abs(w) for w in self.weights.values()), 3)}


def apply_paper_event(books: dict[str, PaperBook], event_type: str, p: dict) -> None:
    """The reducer that rebuilds paper books from the ledger (same events, same order, same numbers)."""
    b = books.get(p.get("book", ""))
    if b is None:
        return
    if event_type == "PaperMark":
        b.mark(p["prices"], p["day"])
    elif event_type == "PaperRebalance":
        b.rebalance(p["target"], p["prices"], p["day"])


def evidence_from_paper(book: PaperBook, years_needed_note: bool = True) -> dict:
    """How strong is the paper record? t = Sharpe x sqrt(years). t >= 2 is the usual bar for 'probably not luck'."""
    s = book.stats()
    out = {**s, "probability_edge_positive": round(0.5 * (1 + math.erf(s["t_stat"] / math.sqrt(2))), 3)}
    if years_needed_note and s["sharpe"] > 0:
        out["days_to_t2_at_this_sharpe"] = int(365 * (2 / s["sharpe"]) ** 2)
    return out
