"""Corrected cycle simulator (replaces hybrid_screen_research_grade's execution math).

Fixes versus the original script:
  * every leg is explicit: 'buy' (spend quote, walk asks, receive base) or
    'sell' (spend base, walk bids, receive quote), so the book side is always right;
  * units are tracked through the chain (each leg's input asset must equal the
    previous leg's output asset; cycle must start and end in USD);
  * no inverted-book 1/price hack: list the pair as quoted on the venue;
  * fees are taken on the received asset;
  * staleness is a parameter (or None), not a hard-coded 10 ms.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Dict, List, Optional, Sequence, Tuple

getcontext().prec = 28
BPS = Decimal(10000)
ZERO = Decimal(0)


@dataclass(frozen=True)
class Level:
    price: Decimal
    size: Decimal  # base-asset quantity


@dataclass
class Book:
    venue: str
    pair: str  # "BASE/QUOTE" exactly as the venue lists it
    bids: List[Level]  # descending
    asks: List[Level]  # ascending
    received_ns: int = 0


@dataclass(frozen=True)
class Leg:
    venue: str
    pair: str
    side: str  # 'buy' base with quote, or 'sell' base for quote

    def __post_init__(self):
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {self.side!r}")
        if self.pair.count("/") != 1:
            raise ValueError(f"pair must look like BASE/QUOTE, got {self.pair!r}")

    @property
    def base(self) -> str:
        return self.pair.split("/")[0]

    @property
    def quote(self) -> str:
        return self.pair.split("/")[1]

    @property
    def asset_in(self) -> str:
        return self.quote if self.side == "buy" else self.base

    @property
    def asset_out(self) -> str:
        return self.base if self.side == "buy" else self.quote


@dataclass
class LegFill:
    leg: Leg
    amount_in: Decimal
    amount_out: Decimal  # net of fee
    fee: Decimal  # in asset_out
    vwap: Decimal  # quote per base
    top_price: Decimal
    slippage_bps: Decimal  # adverse vs top of book, >= 0
    levels_consumed: int
    worst_price: Decimal = ZERO  # least favourable level touched (use as an IOC limit)


@dataclass
class CycleResult:
    fills: List[LegFill]
    start_usd: Decimal
    end_usd: Decimal

    @property
    def profit_usd(self) -> Decimal:
        return self.end_usd - self.start_usd

    @property
    def edge_bps(self) -> Decimal:
        return self.profit_usd / self.start_usd * BPS


def walk_buy(asks: Sequence[Level], quote_budget: Decimal, limit: Optional[Decimal] = None):
    """Spend quote_budget on asks (optionally only up to `limit`). Returns (base, top, worst, levels) or None if depth is short."""
    remaining, base = quote_budget, ZERO
    top = worst = None
    used = 0
    for lvl in asks:
        if lvl.price <= 0 or lvl.size <= 0:
            continue
        if limit is not None and lvl.price > limit:
            break
        take = min(remaining, lvl.price * lvl.size)
        base += take / lvl.price
        remaining -= take
        top = lvl.price if top is None else top
        worst = lvl.price
        used += 1
        if remaining <= 0:
            break
    if remaining > 0 or base <= 0:
        return None
    return base, top, worst, used


def walk_sell(bids: Sequence[Level], base_amount: Decimal, limit: Optional[Decimal] = None):
    """Sell base_amount into bids. Returns (quote, top, worst, levels) or None."""
    remaining, quote = base_amount, ZERO
    top = worst = None
    used = 0
    for lvl in bids:
        if lvl.price <= 0 or lvl.size <= 0:
            continue
        if limit is not None and lvl.price < limit:
            break
        take = min(remaining, lvl.size)
        quote += take * lvl.price
        remaining -= take
        top = lvl.price if top is None else top
        worst = lvl.price
        used += 1
        if remaining <= 0:
            break
    if remaining > 0 or quote <= 0:
        return None
    return quote, top, worst, used


def validate_cycle(legs: Sequence[Leg], start_asset: str = "USD") -> Optional[str]:
    if not legs:
        return "empty cycle"
    asset = start_asset
    for i, leg in enumerate(legs):
        if leg.asset_in != asset:
            return f"leg {i} ({leg.side} {leg.pair}) needs {leg.asset_in} but holds {asset}"
        asset = leg.asset_out
    if asset != start_asset:
        return f"cycle ends in {asset}, not {start_asset}"
    return None


def simulate_cycle(
    books: Dict[Tuple[str, str], Book],
    legs: Sequence[Leg],
    start_usd: Decimal,
    fees: Dict[str, Decimal],
    *,
    now_ns: Optional[int] = None,
    max_age_ms: Optional[float] = None,
    default_fee: Decimal = Decimal("0.0004"),
) -> Tuple[Optional[CycleResult], Optional[str]]:
    err = validate_cycle(legs)
    if err:
        return None, err
    amount = start_usd
    fills: List[LegFill] = []
    for leg in legs:
        book = books.get((leg.venue, leg.pair))
        if book is None:
            return None, f"missing book {leg.pair} @ {leg.venue}"
        if max_age_ms is not None and now_ns is not None:
            age_ms = (now_ns - book.received_ns) / 1e6
            if age_ms > max_age_ms:
                return None, f"stale book {leg.pair} @ {leg.venue}: {age_ms:.0f}ms"
        if leg.side == "buy":
            walked = walk_buy(book.asks, amount)
        else:
            walked = walk_sell(book.bids, amount)
        if walked is None:
            return None, f"insufficient depth {leg.side} {leg.pair} @ {leg.venue}"
        out_gross, top, worst, used = walked
        if leg.side == "buy":
            vwap = amount / out_gross
            slip = (vwap - top) / top * BPS
        else:
            vwap = out_gross / amount
            slip = (top - vwap) / top * BPS
        fee = out_gross * fees.get(leg.venue, default_fee)
        out = out_gross - fee
        fills.append(LegFill(leg, amount, out, fee, vwap, top, slip, used, worst))
        amount = out
    return CycleResult(fills, start_usd, amount), None


def best_cycle(
    books, cycles: Sequence[Sequence[Leg]], start_usd, fees, **kw
) -> Tuple[Optional[CycleResult], Optional[Sequence[Leg]]]:
    best, best_legs = None, None
    for legs in cycles:
        res, _ = simulate_cycle(books, legs, start_usd, fees, **kw)
        if res is not None and (best is None or res.profit_usd > best.profit_usd):
            best, best_legs = res, legs
    return best, best_legs
