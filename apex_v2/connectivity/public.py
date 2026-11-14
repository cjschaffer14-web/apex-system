"""Credential-free Coinbase L2 and Kraken depth snapshots, stdlib transport.
Independent HTTP snapshots avoid maintaining unaudited incremental books.
"""
import json
import re
import ssl
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote
from datetime import datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from ..core import Book, Level
from .interfaces import BookSnapshot, VenueConnector
from .markets import pair_name, coinbase_markets, kraken_markets

def iso_ns(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None: raise ValueError('source time must have timezone')
    return int(dt.timestamp()*1e9)

def get_public(url, *, max_cache_s=1, max_response_age_s=2):
    started = time.time_ns()
    req = urllib.request.Request(url, headers={'User-Agent':'apex-public-shadow/1', 'Cache-Control':'no-cache'})
    # Some framework Python installations have no bundled CA file. Use the
    # installed system trust bundle; certificate verification remains enabled.
    paths = ssl.get_default_verify_paths()
    context = ssl.create_default_context(cafile='/etc/ssl/cert.pem') if paths.cafile is None and Path('/etc/ssl/cert.pem').is_file() else ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=8, context=context) as response:
        data = json.loads(response.read(4_000_000))
        # HTTP cache evidence is checked separately from per-level update times.
        age = float(response.headers.get('Age', '0'))
        date = response.headers.get('Date')
    ended = time.time_ns()
    if age < 0 or age > max_cache_s: raise ValueError('cached response rejected')
    if date:
        server_ns = int(parsedate_to_datetime(date).timestamp()*1e9)
        if ended-server_ns > max_response_age_s*1_000_000_000 or server_ns-ended > 1_000_000_000:
            raise ValueError('stale/future HTTP response')
    return data, started, ended

def get_public_metadata(url):
    # Market listings do not have the two-second trading-book freshness rule.
    return get_public(url, max_cache_s=86400, max_response_age_s=86400)

def normalized(venue, endpoint, pair, raw, started, ended, *, fee_bps=None, source_ns=None, sequence=None):
    levels = lambda key, rev: sorted([Level(Decimal(str(x[0])), Decimal(str(x[1]))) for x in raw[key]], key=lambda x:x.price, reverse=rev)
    book = Book(venue, pair, levels('bids', True), levels('asks', False), started)
    result = BookSnapshot(venue, endpoint, endpoint+':'+pair, book, started, ended, source_ns, fee_bps, sequence)
    result.validate()
    return result

class CoinbaseConnector(VenueConnector):
    economic_venue_id = 'coinbase_spot'
    endpoint_id = 'coinbase_exchange_rest'
    def __init__(self, fee_bps=None, transport=get_public):
        self.fee_bps, self.transport = fee_bps, transport
        self.metadata_transport = get_public_metadata if transport is get_public else transport
    def markets(self):
        rows, _, ended = self.metadata_transport('https://api.exchange.coinbase.com/products')
        return coinbase_markets(rows, ended)
    def normalize(self, pair, data, started, ended):
        if data.get('auction_mode'): raise ValueError('indicative auction book rejected')
        return normalized(self.economic_venue_id, self.endpoint_id, pair, data, started, ended,
                          fee_bps=self.fee_bps, source_ns=iso_ns(data['time']) if data.get('time') else None,
                          sequence=data.get('sequence'))
    def snapshot(self, pair):
        pair = pair_name(pair)
        return self.normalize(pair, *self.transport('https://api.exchange.coinbase.com/products/'+pair.replace('/', '-')+'/book?level=2'))

class KrakenConnector(VenueConnector):
    economic_venue_id = 'kraken_spot'
    endpoint_id = 'kraken_spot_rest'
    def __init__(self, fee_bps=None, transport=get_public):
        self.fee_bps, self.transport = fee_bps, transport
        self.metadata_transport = get_public_metadata if transport is get_public else transport
        self._markets = None
    def markets(self):
        data, _, ended = self.metadata_transport('https://api.kraken.com/0/public/AssetPairs')
        self._markets = kraken_markets(data, ended)
        return dict(self._markets)
    def normalize(self, pair, data, started, ended):
        if data.get('error'): raise ValueError('Kraken public API error')
        result = data['result']
        if len(result) != 1: raise ValueError('ambiguous Kraken pair')
        # Kraken level timestamps describe last level update, not snapshot time.
        return normalized(self.economic_venue_id, self.endpoint_id, pair, next(iter(result.values())),
                          started, ended, fee_bps=self.fee_bps)
    def snapshot(self, pair):
        pair = pair_name(pair)
        symbols = {'BTC/USD':'XBTUSD', 'ETH/USD':'ETHUSD'}
        if self._markets is not None or pair not in symbols:
            markets = self._markets if self._markets is not None else self.markets()
            if pair not in markets: raise ValueError('unsupported Kraken pair')
            native = markets[pair].native_symbol
        else:
            native = symbols[pair]
        return self.normalize(pair, *self.transport('https://api.kraken.com/0/public/Depth?pair='+quote(native, safe='')+'&count=100'))
