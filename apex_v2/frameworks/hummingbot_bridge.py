"""Hummingbot -> APEX: connector order books and fees.

What Hummingbot adds: ~30 CEX/DEX spot and perp connectors with maintained websocket
order books, trading rules and fee schedules.
APEX uses it as a *market-data and rules source*; it never calls buy()/sell().
"""
from decimal import Decimal

from ..connectivity.interfaces import VenueConnector
from ..connectivity.markets import SpotMarket
from .common import build_snapshot, split_pair, dec


def _entries(book, side):
    fn = getattr(book, side + '_entries')  # hummingbot OrderBook API
    return [(r.price, r.amount) for r in fn()]


def fee_bps_from_connector(connector, pair_hb, is_maker=False):
    """Percent fee -> bps via connector.get_fee; returns None if it cannot be determined."""
    try:
        base, quote = split_pair(pair_hb, '-')
        fee = connector.get_fee(base, quote, None, None, Decimal(1), Decimal(1), is_maker)
        return float(Decimal(str(fee.percent)) * 10000)
    except Exception:
        return None  # APEX treats unknown fees as non-executable, so None is the safe answer


def snapshot_from_connector(connector, venue, pair_hb, depth=20, fee_bps='auto'):
    """connector: a hummingbot ExchangePyBase (live data). pair like 'BTC-USDT'."""
    base, quote = split_pair(pair_hb, '-')
    ob = connector.get_order_book(pair_hb)
    if fee_bps == 'auto':
        fee_bps = fee_bps_from_connector(connector, pair_hb)
    ts = getattr(ob, 'snapshot_uid', None)
    return build_snapshot(venue, 'hummingbot:' + getattr(connector, 'name', venue),
                          'hummingbot', '%s/%s' % (base, quote),
                          _entries(ob, 'bid')[:depth], _entries(ob, 'ask')[:depth],
                          fee_bps=fee_bps)


def market_from_trading_rule(venue, pair_hb, rule, observed_ns):
    """hummingbot TradingRule -> APEX SpotMarket (increments/minimums APEX already validates)."""
    base, quote = split_pair(pair_hb, '-')
    g = lambda n: (dec(getattr(rule, n)) if getattr(rule, n, None) is not None else None)
    return SpotMarket(venue, '%s/%s' % (base, quote), pair_hb, g('min_base_amount_increment'),
                      g('min_price_increment'), g('min_order_size'), g('min_notional_size'),
                      True, observed_ns)


class HummingbotMarketData(VenueConnector):
    """Read-only VenueConnector backed by an already-running hummingbot connector."""

    def __init__(self, connector, venue, depth=20):
        self.connector, self.venue, self.depth = connector, venue, depth

    def snapshot(self, pair):
        base, quote = pair.split('/')
        return snapshot_from_connector(self.connector, self.venue, '%s-%s' % (base, quote), self.depth)
