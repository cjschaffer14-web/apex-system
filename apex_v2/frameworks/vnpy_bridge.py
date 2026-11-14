"""vn.py -> APEX: tick depth, event-bus recorder.

What vn.py adds: an event engine, a gateway abstraction over many (mostly Asian CTP/futures
and crypto) venues, a datafeed/database layer and the `vnpy.alpha` ML research lab.
APEX uses TickData depth (5 levels) as another snapshot source and its EventEngine as a
low-latency fan-out for APEX episodes. No OrderRequest is ever sent to a gateway.
"""
from .common import build_snapshot

EVENT_TICK = 'eTick.'  # vnpy.trader.event.EVENT_TICK


def _ns(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise ValueError('naive datetime: vnpy tick timezone must be explicit')
    return int(dt.timestamp() * 1e9)


def snapshot_from_tick(tick, pair, venue=None, fee_bps=None, received_ns=None):
    """vnpy TickData -> BookSnapshot. `pair` is explicit 'BASE/QUOTE': vnpy symbols are venue-local."""
    bids = [(getattr(tick, 'bid_price_%d' % i, 0), getattr(tick, 'bid_volume_%d' % i, 0)) for i in range(1, 6)]
    asks = [(getattr(tick, 'ask_price_%d' % i, 0), getattr(tick, 'ask_volume_%d' % i, 0)) for i in range(1, 6)]
    ex = getattr(getattr(tick, 'exchange', None), 'value', getattr(tick, 'exchange', 'vnpy'))
    venue = venue or str(ex).lower()
    src = _ns(getattr(tick, 'datetime', None))
    return build_snapshot(venue, 'vnpy:' + getattr(tick, 'gateway_name', 'gateway'), 'vnpy', pair,
                          bids, asks, request_ns=src, received_ns=received_ns, source_ns=src, fee_bps=fee_bps)


class ApexTickRecorder:
    """Register on a vnpy EventEngine: `engine.register(EVENT_TICK, rec.on_tick)`."""

    def __init__(self, pair_by_vt_symbol, fee_bps=None, sink=None):
        self.pairs, self.fee_bps = dict(pair_by_vt_symbol), fee_bps
        self.sink, self.rejected = sink if sink is not None else [], 0

    def on_tick(self, event):
        tick = getattr(event, 'data', event)
        pair = self.pairs.get(getattr(tick, 'vt_symbol', None))
        if pair is None:
            return  # unmapped instrument: ignore rather than guess a pair
        try:
            self.sink.append(snapshot_from_tick(tick, pair, fee_bps=self.fee_bps))
        except ValueError:
            self.rejected += 1  # crossed/empty/stale ticks are counted, never repaired
