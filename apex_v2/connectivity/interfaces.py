"""Small read-only interfaces; timestamps are UTC Unix nanoseconds."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from ..core import Book
from ..economics.formulas import finite
from ..observatory.observations import MarketObservation, Lane

@dataclass(frozen=True)
class BookSnapshot:
    economic_venue_id: str
    endpoint_id: str
    source_id: str
    book: Book
    request_ns: int
    received_ns: int
    source_ns: int | None = None
    fee_bps: float | None = None
    sequence: int | None = None
    synthetic: bool = False

    def validate(self):
        if not self.economic_venue_id or not self.endpoint_id or not self.source_id:
            raise ValueError('missing identity')
        if self.book.venue != self.economic_venue_id or self.book.pair.count('/') != 1:
            raise ValueError('book identity mismatch')
        if not all(isinstance(t,int) and t > 0 for t in (self.request_ns,self.received_ns)):
            raise ValueError('invalid timestamp')
        if self.source_ns is not None and (not isinstance(self.source_ns,int) or self.source_ns <= 0):
            raise ValueError('invalid source timestamp')
        if self.received_ns < self.request_ns: raise ValueError('negative request duration')
        if self.fee_bps is not None:
            finite(self.fee_bps)
            if not 0 <= self.fee_bps < 10000: raise ValueError('invalid fee')
        if not self.book.bids or not self.book.asks: raise ValueError('empty book')
        for rows, reverse in ((self.book.bids,True),(self.book.asks,False)):
            if any(not x.price.is_finite() or not x.size.is_finite() or x.price <= 0 or x.size <= 0 for x in rows):
                raise ValueError('invalid depth')
            if rows != sorted(rows,key=lambda x:x.price,reverse=reverse): raise ValueError('unsorted book')
            if len({x.price for x in rows}) != len(rows): raise ValueError('duplicate price level')
        if self.book.bids[0].price >= self.book.asks[0].price: raise ValueError('crossed/locked book')
        return self

    def fresh(self, now_ns, max_age_s=2):
        self.validate()
        finite(max_age_s)
        if max_age_s <= 0: raise ValueError('invalid freshness limit')
        times = [self.request_ns, self.received_ns]
        if self.source_ns is not None: times.append(self.source_ns)
        # Reject future clocks and slow responses, not merely old receive time.
        if any(t > now_ns for t in times) or now_ns-min(times) > max_age_s*1e9:
            raise ValueError('stale/future snapshot')
        return self

    def observation(self):
        self.validate()
        b = self.book
        return MarketObservation(
            min(self.request_ns, self.source_ns or self.request_ns), b.pair,
            self.economic_venue_id, 'cex', self.source_id,
            float(b.bids[0].price), float(b.asks[0].price),
            float(sum(x.price*x.size for x in b.bids)),
            float(sum(x.price*x.size for x in b.asks)),
            explicit_fee_bps=self.fee_bps or 0, source_kind='cex', lane=Lane.CEX_DEX,
            metadata={'endpoint_id': self.endpoint_id, 'received_ns': self.received_ns,
                      'source_ns': self.source_ns, 'timestamp_basis': 'source_and_request' if self.source_ns else 'request_start',
                      'fees_known': self.fee_bps is not None, 'synthetic': self.synthetic,
                      'depth_is_snapshot': True})

class VenueConnector(ABC):
    @abstractmethod
    def snapshot(self, pair: str): """Read a public snapshot; never place an order."""

class MarketDataStream(ABC):
    @abstractmethod
    def poll(self, pair: str): """Yield/return normalized observations."""
