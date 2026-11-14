"""Public spot-market discovery. Listing is not account eligibility or trade authority."""
from dataclasses import dataclass
from decimal import Decimal
import re


def pair_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z0-9]+/[A-Z0-9]+', value):
        raise ValueError('invalid BASE/QUOTE pair')
    base, quote = value.split('/')
    # Only an actual naming alias: never equate USD with a stablecoin.
    return '/'.join('BTC' if x == 'XBT' else x for x in (base, quote))


def positive(value):
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError('invalid market constraint')
    return number


@dataclass(frozen=True)
class SpotMarket:
    venue: str
    pair: str
    native_symbol: str
    base_increment: Decimal | None
    price_increment: Decimal | None
    min_base: Decimal | None
    min_quote: Decimal | None
    market_orders: bool
    observed_ns: int


def coinbase_markets(rows, observed_ns):
    markets = {}
    for row in rows:
        if row.get('status') != 'online' or any(row.get(k) for k in
                ('trading_disabled', 'cancel_only', 'auction_mode')):
            continue
        pair = pair_name(row['base_currency'] + '/' + row['quote_currency'])
        if pair in markets:
            raise ValueError('ambiguous Coinbase market')
        markets[pair] = SpotMarket('coinbase_spot', pair, row['id'],
            positive(row.get('base_increment')), positive(row.get('quote_increment')),
            positive(row.get('base_min_size')), positive(row.get('min_market_funds')),
            not (row.get('limit_only') or row.get('post_only')), observed_ns)
    return markets


def kraken_markets(data, observed_ns):
    if data.get('error'):
        raise ValueError('Kraken market discovery failed')
    markets = {}
    for native, row in data['result'].items():
        if native.endswith('.d') or row.get('status') != 'online' or not row.get('wsname'):
            continue
        if row.get('lot_multiplier', 1) != 1:
            continue
        pair = pair_name(row['wsname'])
        if pair in markets:
            raise ValueError('ambiguous Kraken market')
        markets[pair] = SpotMarket('kraken_spot', pair, row.get('altname', native),
            Decimal(10) ** -int(row['lot_decimals']),
            positive(row['tick_size']) if row.get('tick_size') else Decimal(10) ** -int(row['pair_decimals']),
            positive(row.get('ordermin')), positive(row.get('costmin')), True, observed_ns)
    return markets
