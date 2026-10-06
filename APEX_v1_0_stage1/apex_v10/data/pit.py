"""Point-in-time access to the v1.0 database.

Rules
  * macro: the latest observation period whose published_ts <= decision_ts; for that period, the latest vintage
    published by then. A value is never visible before it was published, revisions included.
  * legacy readings (day numbers): visible when day_start + publish_lag_s <= decision_ts (reading_availability).
  * funding: accrual happens only at recorded settlement events, for the position held at that instant.
"""
from __future__ import annotations

import bisect
import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

DAY = 86400


@dataclass(frozen=True)
class AsOfValue:
    value: float
    observation_ts: int
    published_ts: int
    availability_quality: str
    provenance_id: str


def macro_asof(con: sqlite3.Connection, source: str, series_id: str, decision_ts: int) -> Optional[AsOfValue]:
    row = con.execute(
        "SELECT value, observation_ts, published_ts, availability_quality, provenance_id FROM macro_observations "
        "WHERE source=? AND series_id=? AND published_ts<=? ORDER BY observation_ts DESC, published_ts DESC LIMIT 1",
        (source, series_id, decision_ts)).fetchone()
    return AsOfValue(*row) if row else None


class MacroSeries:
    """Vectorised as-of lookups for one series (sorted once, then binary search per decision time)."""

    def __init__(self, con: sqlite3.Connection, source: str, series_id: str) -> None:
        rows = con.execute(
            "SELECT published_ts, observation_ts, value, availability_quality, provenance_id FROM macro_observations "
            "WHERE source=? AND series_id=? ORDER BY published_ts, observation_ts", (source, series_id)).fetchall()
        # running "best (observation_ts, published_ts)" in publication order
        self._pub: list[int] = []
        self._best: list[AsOfValue] = []
        best = None
        for pub, obs, val, q, pid in rows:
            if best is None or (obs, pub) >= (best.observation_ts, best.published_ts):
                best = AsOfValue(val, obs, pub, q, pid)
            self._pub.append(pub)
            self._best.append(best)

    def asof(self, decision_ts: int) -> Optional[AsOfValue]:
        k = bisect.bisect_right(self._pub, decision_ts)
        return self._best[k - 1] if k else None


def reading_asof(con: sqlite3.Connection, source: str, metric: str, decision_ts: int) -> Optional[tuple[int, float]]:
    rule = con.execute("SELECT publish_lag_s FROM reading_availability WHERE source=? AND metric=?",
                       (source, metric)).fetchone()
    if rule is None:
        raise KeyError(f"no availability rule for legacy reading {source}/{metric}; it may not be used")
    lag = rule[0]
    last_visible_day = (decision_ts - lag) // DAY
    return con.execute("SELECT ts, value FROM readings WHERE source=? AND metric=? AND ts<=? ORDER BY ts DESC LIMIT 1",
                       (source, metric, last_visible_day)).fetchone()


@dataclass(frozen=True)
class FundingEvent:
    venue: str
    symbol: str
    funding_ts: int
    rate: float
    interval_s: Optional[int]
    rate_semantics: str


def funding_events(con: sqlite3.Connection, venue: str, symbol: str, t0: int, t1: int) -> list[FundingEvent]:
    """Recorded settlements with t0 < funding_ts <= t1."""
    return [FundingEvent(venue, symbol, *r) for r in con.execute(
        "SELECT funding_ts, rate, interval_s, rate_semantics FROM funding_events "
        "WHERE venue=? AND symbol=? AND funding_ts>? AND funding_ts<=? ORDER BY funding_ts", (venue, symbol, t0, t1))]


def accrue_funding(events: Iterable[FundingEvent], notional_at: Callable[[int], float]) -> list[tuple[int, float]]:
    """Signed funding paid at each recorded event: + means the account paid (a long pays a positive rate).
    `notional_at(ts)` returns the signed position notional held at that settlement instant (0 when flat)."""
    out = []
    for e in events:
        n = notional_at(e.funding_ts)
        if n:
            out.append((e.funding_ts, n * e.rate))
    return out
