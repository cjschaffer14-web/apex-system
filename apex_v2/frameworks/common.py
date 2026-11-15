"""Shared helpers for the framework bridges.

The bridges are duck-typed: none of hummingbot, freqtrade, vnpy or Lean needs to be
importable. They convert framework objects into APEX's own read-only types, so the
APEX mode rules stay in one place.
"""
import time
from decimal import Decimal

from ..connectivity.interfaces import BookSnapshot
from ..connectivity.markets import pair_name
from ..core import Book, Level
from ..economics.formulas import finite

MODES = ('live', 'shadow', 'backtest')


def require_mode(mode):
    """Every bridge funnels through this. Paper mode no longer exists."""
    if mode not in MODES:
        raise ValueError('unknown mode: %r (allowed: %s)' % (mode, ', '.join(MODES)))
    return mode


def dec(value, name='value'):
    d = Decimal(str(value))
    if not d.is_finite():
        raise ValueError('non-finite ' + name)
    return d


def levels(rows, reverse):
    """rows: iterable of (price, size). Drops empty/zero levels, sorts, rejects duplicates."""
    out = {}
    for price, size in rows:
        p, s = dec(price, 'price'), dec(size, 'size')
        if p <= 0 or s <= 0:
            continue  # exchanges send zero-size deletions and padded empty levels
        if p in out:
            raise ValueError('duplicate price level')
        out[p] = s
    return [Level(p, out[p]) for p in sorted(out, reverse=reverse)]


def build_snapshot(venue, endpoint, source, pair, bids, asks, request_ns=None,
                   received_ns=None, source_ns=None, fee_bps=None):
    pair = pair_name(pair)
    now = time.time_ns()
    request_ns = request_ns or now
    received_ns = received_ns or max(now, request_ns)
    if fee_bps is not None:
        finite(float(fee_bps))
        fee_bps = float(fee_bps)
    book = Book(venue, pair, levels(bids, True), levels(asks, False), received_ns)
    return BookSnapshot(venue, endpoint, source, book, request_ns, received_ns,
                        source_ns, fee_bps).validate()


def split_pair(pair, sep):
    base, _, quote = pair.partition(sep)
    if not base or not quote or sep in quote:
        raise ValueError('unsupported pair format: %r' % pair)
    return base.upper(), quote.upper()
