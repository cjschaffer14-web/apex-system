"""Isolated APEX paper pilot. Fixed Alpaca paper host; no live-order route."""
import datetime as dt
import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import broker_reconciliation as BR
import broker_lifecycle as BL

PAPER = 'https://paper-api.alpaca.markets'
DATA = 'https://data.alpaca.markets'
SYMBOL = 'BTC/USD'
MAX_NOTIONAL = Decimal('10')
HERE = Path(__file__).parent

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

class PilotError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)

class RemoteError(Exception):
    def __init__(self, status):
        self.status = status

class Transport:
    def json(self, method, url, headers=None, data=None):
        req = urllib.request.Request(url, method=method, headers=headers or {},
            data=json.dumps(data).encode() if data is not None else None)
        # All callers supply fixed trusted origins. Redirects are rejected so credentials
        # cannot be forwarded to a different host, or a paper call reach a live host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=12) as r:
                raw = r.read(1048577)
                if len(raw) > 1048576:
                    raise PilotError('provider_response_too_large', 502)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise RemoteError(e.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PilotError('provider_outcome_unknown', 503) from None
        except (ValueError, UnicodeError):
            raise PilotError('provider_response_invalid', 502) from None

class Alpaca:
    def __init__(self, env, transport):
        self.env, self.transport = env, transport

    def call(self, method, path, data=None, market=False):
        key, secret = self.env.get('APEX_PAPER_KEY'), self.env.get('APEX_PAPER_SECRET')
        if not key or not secret:
            raise PilotError('new_paper_account_not_connected', 424)
        return self.transport.json(method, (DATA if market else PAPER) + path,
            {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret,
             'Content-Type': 'application/json'}, data)

    def account(self):
        return self.call('GET', '/v2/account')

    def quote(self):
        d = self.call('GET', '/v1beta3/crypto/us/latest/quotes?symbols=BTC%2FUSD', market=True)
        try:
            q = d['quotes'][SYMBOL]
            bid, ask = Decimal(str(q['bp'])), Decimal(str(q['ap']))
            stamp = dt.datetime.fromisoformat(q['t'].replace('Z', '+00:00'))
            age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
            if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
                raise ValueError()
            if not -5 <= age <= 30:
                raise PilotError('quote_not_fresh', 424)
            return {'symbol': SYMBOL, 'bid': str(bid), 'ask': str(ask),
                    'source_time': q['t'], 'received_at': now()}
        except (KeyError, ValueError, TypeError, InvalidOperation):
            raise PilotError('quote_invalid', 502) from None

    def find(self, client_id):
        try:
            return self.call('GET', '/v2/orders:by_client_order_id?client_order_id=' + client_id)
        except RemoteError as e:
            if e.status == 404:
                return None
            raise

class MemoryStore:
    """Test-only store: deliberately rejected for cloud order submission."""
    durable = False
    def __init__(self):
        self.data, self.lock = {}, threading.Lock()
    def create(self, key, value):
        with self.lock:
            if key in self.data:
                return False
            self.data[key] = json.loads(json.dumps(value))
            return True
    def get(self, key):
        with self.lock:
            return self.data.get(key)
    def put(self, key, value):
        with self.lock:
            self.data[key] = json.loads(json.dumps(value))

class GCSStore:
    durable = True
    def __init__(self, bucket, transport, collection='orders'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]', bucket):
            raise PilotError('receipt_bucket_invalid', 500)
        if collection not in ('orders', 'capability-runs'):
            raise PilotError('receipt_collection_invalid', 500)
        self.bucket, self.transport, self.collection = bucket, transport, collection
    def headers(self):
        t = self.transport.json('GET', 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
                                {'Metadata-Flavor': 'Google'})['access_token']
        return {'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json'}
    def name(self, key):
        if not re.fullmatch('[a-f0-9]{64}', key):
            raise PilotError('receipt_key_invalid', 400)
        return urllib.parse.quote(self.collection + '/' + key + '.json', safe='')
    def create(self, key, value):
        url = f'https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o?uploadType=media&ifGenerationMatch=0&name={self.name(key)}'
        try:
            self.transport.json('POST', url, self.headers(), value)
            return True
        except RemoteError as e:
            if e.status in (409, 412):
                return False
            raise PilotError('receipt_reservation_failed', 503) from None
    def put(self, key, value):
        url = f'https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o?uploadType=media&name={self.name(key)}'
        self.transport.json('POST', url, self.headers(), value)
    def get(self, key):
        url = f'https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{self.name(key)}?alt=media'
        return self.transport.json('GET', url, self.headers())

class Pilot:
    def __init__(self, env=None, broker=None, store=None, report_store=None, snapshot_transport_factory=None, lifecycle_transport_factory=None):
        self.env = dict(os.environ if env is None else env)
        self.max_notional = Decimal(self.env.get('APEX_MAX_PAPER_NOTIONAL_USD', '10'))
        if not self.max_notional.is_finite() or not 0 < self.max_notional <= 12:
            raise PilotError('invalid_paper_notional_ceiling', 500)
        tr = Transport()
        self.broker = broker or Alpaca(self.env, tr)
        self.store = store or (GCSStore(self.env['APEX_RECEIPT_BUCKET'], tr) if self.env.get('APEX_RECEIPT_BUCKET') else MemoryStore())
        self.report_store = report_store or (GCSStore(self.env['APEX_RECEIPT_BUCKET'], tr, 'capability-runs') if self.env.get('APEX_RECEIPT_BUCKET') else MemoryStore())
        self.snapshot_transport_factory = snapshot_transport_factory or (lambda: BR.PaperReadOnly(
            (self.env.get('APEX_PAPER_KEY', ''), self.env.get('APEX_PAPER_SECRET', ''))))
        self.lifecycle_transport_factory = lifecycle_transport_factory or (lambda: BL.LifecycleReadOnly(
            (self.env.get('APEX_PAPER_KEY', ''), self.env.get('APEX_PAPER_SECRET', ''))))

    def account(self):
        expected = self.env.get('APEX_EXPECTED_ACCOUNT_ID', '')
        old = self.env.get('APEX_EXISTING_ACCOUNT_ID', '')
        if not expected or not old or expected == old:
            raise PilotError('distinct_new_and_existing_account_ids_required', 424)
        a = self.broker.account()
        if a.get('id') != expected or a.get('id') == old or a.get('account_number') == old:
            raise PilotError('account_identity_mismatch', 403)
        if a.get('status') != 'ACTIVE' or a.get('account_blocked') or a.get('trading_blocked') or a.get('trade_suspended_by_user'):
            raise PilotError('paper_account_not_trade_ready', 424)
        return a

    def status(self):
        checks = {'release': self.env.get('APEX_SOURCE_SHA', 'local-unreleased'),
                  'mode': 'paper-only', 'paper_host': PAPER, 'symbol': SYMBOL,
                  'max_order_notional_usd': str(self.max_notional), 'durable_receipts': self.store.durable,
                  'checked_at': now(), 'automatic_failover': False}
        try:
            a = self.account()
            checks.update(account='verified_distinct', account_suffix=a['id'][-4:],
                          equity=a.get('equity'), cash=a.get('cash'))
        except (PilotError, RemoteError) as e:
            checks.update(account='needs_input', account_issue=e.code if isinstance(e, PilotError) else 'alpaca_http_' + str(e.status))
        checks['paper_orders_enabled'] = self.env.get('APEX_ENABLE_PAPER_ORDERS') == 'true' and checks['account'] == 'verified_distinct' and self.store.durable
        return checks

    def broker_snapshot(self, after, until):
        try:
            start, end = BR.timestamp(after), BR.timestamp(until)
            if not 0 < (end-start).total_seconds() <= 86400 or end > BR.timestamp(BR.utc()):
                raise BR.Blocked('invalid_activity_window')
        except BR.Blocked as error:
            raise PilotError(str(error), 400) from None
        # Preserve the configured UUID/excluded-account gate before the
        # collector's additional exact account-number/currency validation.
        self.account()
        try:
            receipt = BR.snapshot(self.snapshot_transport_factory(), after, until)
        except BR.Blocked as error:
            raise PilotError(str(error), 424) from None
        receipt['cloud_source_release'] = self.env.get('APEX_SOURCE_SHA', 'local-unreleased')
        receipt['broker_snapshot_version'] = '1'
        receipt['collector_source_sha256'] = BR.digest(Path(BR.__file__).read_bytes())
        receipt['cloud_extension_source_sha256'] = BR.digest(Path(__file__).read_bytes())
        return receipt

    def broker_lifecycle(self, after, until):
        try:
            start, end = BR.timestamp(after), BR.timestamp(until)
            if not 0 < (end-start).total_seconds() <= 86400 or end > BR.timestamp(BR.utc()):
                raise BR.Blocked('invalid_activity_window')
        except BR.Blocked as error:
            raise PilotError(str(error), 400) from None
        self.account()
        try:
            receipt = BL.collect(self.lifecycle_transport_factory(), after, until)
        except BR.Blocked as error:
            raise PilotError(str(error), 424) from None
        receipt['cloud_source_release'] = self.env.get('APEX_SOURCE_SHA', 'local-unreleased')
        receipt['broker_lifecycle_version'] = '1'
        receipt['collector_source_sha256'] = BR.digest(Path(BL.__file__).read_bytes())
        receipt['cloud_extension_source_sha256'] = BR.digest(Path(__file__).read_bytes())
        return receipt

    def trade_context(self):
        a = self.account()
        positions = self.broker.call('GET', '/v2/positions')
        orders = self.broker.call('GET', '/v2/orders?status=open&limit=500')
        asset = self.broker.call('GET', '/v2/assets/BTC%2FUSD')
        btc = [p for p in positions if p.get('symbol') in ('BTCUSD', SYMBOL)]
        return {'release': self.env.get('APEX_SOURCE_SHA', 'local-unreleased'),
                'mode': 'paper-only', 'account_number': a.get('account_number'),
                'account_suffix': a['id'][-4:], 'observed_at': now(),
                'open_order_count': len(orders), 'btc_positions': [
                    {k: p.get(k) for k in ('symbol', 'qty', 'qty_available', 'market_value')}
                    for p in btc],
                'asset': {k: asset.get(k) for k in ('symbol', 'class', 'status', 'tradable',
                    'min_order_size', 'min_trade_increment', 'price_increment')},
                'quote': self.broker.quote()}

    def capability_status(self):
        key = hashlib.sha256(b'hermes.apex.paper-trade-loop:latest').hexdigest()
        try:
            return self.report_store.get(key) or {'capability': 'hermes.apex.paper-trade-loop', 'verdict': 'not_run'}
        except RemoteError as e:
            if e.status == 404:
                return {'capability': 'hermes.apex.paper-trade-loop', 'verdict': 'not_run'}
            raise

    def capability_report(self, report):
        fields = {'run_id', 'source_release', 'executor_task_id', 'requested_mode',
                  'verdict', 'blocker', 'buy_request_id', 'sell_request_id'}
        if not isinstance(report, dict) or set(report) != fields:
            raise PilotError('invalid_capability_report_fields', 400)
        if not all(isinstance(v, str) and len(v) <= 1500 for v in report.values()):
            raise PilotError('invalid_capability_report_value', 400)
        run_id = report['run_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,40}', run_id):
            raise PilotError('invalid_capability_run_id', 400)
        if report['source_release'] != self.env.get('APEX_SOURCE_SHA'):
            raise PilotError('capability_source_mismatch', 409)
        if report['requested_mode'] not in ('preflight', 'trade_loop') or report['verdict'] not in ('passed', 'blocked', 'failed'):
            raise PilotError('invalid_capability_verdict', 400)
        if not self.report_store.durable:
            raise PilotError('durable_capability_reports_required', 424)
        checks = {'cloud_endpoint': 'passed', 'source_release': 'passed', 'durable_reports': 'passed'}
        if report['verdict'] == 'passed' and report['requested_mode'] == 'trade_loop':
            a = self.account()
            for side in ('buy', 'sell'):
                expected = 'hermes_' + run_id + '_' + side
                if report[side + '_request_id'] != expected:
                    raise PilotError('capability_request_identity_mismatch', 409)
                receipt = self.store.get(hashlib.sha256((a['id'] + ':' + expected).encode()).hexdigest())
                order = self.broker.find(receipt['client_order_id']) if receipt else None
                if not receipt or receipt.get('release') != report['source_release'] or not order or order.get('status') != 'filled' or order.get('side') != side or order.get('symbol') not in ('BTCUSD', SYMBOL):
                    raise PilotError('capability_fill_not_verified', 409)
                if side == 'buy' and receipt.get('btc_qty_before') != '0':
                    raise PilotError('capability_baseline_not_verified', 409)
                checks[side + '_fill'] = 'passed'
            positions = self.broker.call('GET', '/v2/positions')
            if any(Decimal(str(p['qty'])) != 0 for p in positions if p.get('symbol') in ('BTCUSD', SYMBOL)) or self.broker.call('GET', '/v2/orders?status=open&limit=1'):
                raise PilotError('capability_not_flat', 409)
            checks.update(broker_account='passed', btc_position_flat='passed', no_open_orders='passed')
        elif report['verdict'] == 'passed':
            if not self.status()['paper_orders_enabled']:
                raise PilotError('capability_preflight_not_ready', 409)
            checks['broker_account'] = 'passed'
        record = {**report, 'capability': 'hermes.apex.paper-trade-loop', 'version': '1.0.0',
                  'checks': checks, 'recorded_at': now(), 'executor_evidence': 'Cross-check executor_task_id against Hermes Cloudbridge tool events.'}
        key = hashlib.sha256(('hermes.apex.paper-trade-loop:' + run_id).encode()).hexdigest()
        if not self.report_store.create(key, record):
            self.report_store.put(key, record)
        self.report_store.put(hashlib.sha256(b'hermes.apex.paper-trade-loop:latest').hexdigest(), record)
        return record

    def order_input(self, d):
        if not isinstance(d, dict) or set(d) != {'request_id', 'symbol', 'side', 'qty', 'limit_price'}:
            raise PilotError('invalid_order_fields', 400)
        if not isinstance(d['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', d['request_id']):
            raise PilotError('invalid_request_id', 400)
        if d['symbol'] != SYMBOL or d['side'] not in ('buy', 'sell'):
            raise PilotError('unsupported_symbol_or_side', 400)
        try:
            qty, price = Decimal(str(d['qty'])), Decimal(str(d['limit_price']))
            if not qty.is_finite() or not price.is_finite() or qty <= 0 or price <= 0 or qty * price > self.max_notional:
                raise ValueError()
            if qty.as_tuple().exponent < -9 or price.as_tuple().exponent < -2:
                raise ValueError()
        except (InvalidOperation, ValueError, TypeError):
            raise PilotError('invalid_or_oversize_order', 400) from None
        return qty, price

    @staticmethod
    def summary(order):
        fields = ['id', 'client_order_id', 'symbol', 'side', 'type', 'qty', 'limit_price', 'status', 'filled_qty', 'filled_avg_price', 'submitted_at', 'filled_at']
        return {k: order.get(k) for k in fields}

    def reconcile(self, receipt_key, record):
        if record.get('state') == 'rejected':
            return record
        order = self.broker.find(record['client_order_id'])
        if not order:
            # A missing broker result after an ambiguous POST is not proof of rejection.
            return {'state': 'uncertain', 'request_id': record['request_id'],
                    'client_order_id': record['client_order_id'], 'action': 'reconcile_same_request_do_not_resubmit'}
        record = {**record, 'state': 'complete', 'order': self.summary(order), 'reconciled_at': now()}
        self.store.put(receipt_key, record)
        return record

    def submit(self, d, reconcile_only=False):
        qty, price = self.order_input(d)
        if self.env.get('APEX_ENABLE_PAPER_ORDERS') != 'true':
            raise PilotError('paper_orders_disabled', 403)
        if not self.store.durable:
            raise PilotError('durable_receipts_required', 424)
        a = self.account()
        key = hashlib.sha256((a['id'] + ':' + d['request_id']).encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps(d, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        # Atomic cloud reservation is before any provider order POST.
        record = {'state': 'reserved', 'request_id': d['request_id'], 'fingerprint': fingerprint,
                  'client_order_id': 'apex-pilot-' + key[:40], 'reserved_at': now(),
                  'release': self.env.get('APEX_SOURCE_SHA', 'local-unreleased')}
        if reconcile_only:
            try:
                prior = self.store.get(key)
            except RemoteError as e:
                if e.status == 404:
                    raise PilotError('receipt_not_found_no_order_sent', 404) from None
                raise
            if not prior:
                raise PilotError('receipt_not_found_no_order_sent', 404)
            if prior['fingerprint'] != fingerprint:
                raise PilotError('idempotency_payload_conflict', 409)
            return self.reconcile(key, prior)
        if not self.store.create(key, record):
            prior = self.store.get(key)
            if prior['fingerprint'] != fingerprint:
                raise PilotError('idempotency_payload_conflict', 409)
            return self.reconcile(key, prior)
        posted = False
        try:
            q = self.broker.quote()
            bid, ask = Decimal(q['bid']), Decimal(q['ask'])
            if not bid * Decimal('.98') <= price <= ask * Decimal('1.02'):
                raise PilotError('limit_price_outside_quote_band', 400)
            if self.broker.call('GET', '/v2/orders?status=open&limit=1'):
                raise PilotError('existing_open_order_requires_review', 409)
            positions = self.broker.call('GET', '/v2/positions')
            record['btc_qty_before'] = str(sum((Decimal(str(p['qty'])) for p in positions if p.get('symbol') in ('BTCUSD', SYMBOL)), Decimal(0)))
            if d['side'] == 'buy' and min(Decimal(str(a.get('non_marginable_buying_power', '0'))),
                    Decimal(str(a.get('cash', '0')))) < qty * price:
                raise PilotError('insufficient_paper_buying_power', 409)
            if d['side'] == 'sell':
                available = sum((Decimal(str(p.get('qty_available', p.get('qty', '0')))) for p in positions if p.get('symbol') in ('BTCUSD', SYMBOL)), Decimal(0))
                if available < qty:
                    raise PilotError('insufficient_position_no_shorting', 409)
            body = {'symbol': SYMBOL, 'side': d['side'], 'qty': str(qty), 'limit_price': str(price),
                    'type': 'limit', 'time_in_force': 'gtc', 'client_order_id': record['client_order_id']}
            posted = True
            order = self.broker.call('POST', '/v2/orders', body)
            record.update(state='complete', order=self.summary(order), quote=q, completed_at=now())
            self.store.put(key, record)
            return record
        except PilotError as e:
            if not posted:
                record.update(state='rejected', error=e.code, completed_at=now())
                self.store.put(key, record)
                return record
            raise
        except Exception:
            # Keep reservation durable even after provider timeout/storage-write failure.
            # Retrying this request only reconciles with broker, never posts again.
            raise

class Handler(BaseHTTPRequestHandler):
    pilot = None
    def log_message(self, *args):
        pass  # No bodies, headers, query strings or broker secrets in logs.
    def send(self, status, body, mime='application/json'):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        for k,v in {'Content-Type':mime, 'Content-Length':str(len(data)), 'Cache-Control':'no-store',
                    'X-Content-Type-Options':'nosniff', 'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items():
            self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        try:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path in ('/api/broker-snapshot', '/api/broker-lifecycle'):
                try:
                    if len(self.path) > 1024:
                        raise ValueError()
                    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True, max_num_fields=2)
                    if set(query) != {'after', 'until'} or any(len(v) != 1 or not v[0] for v in query.values()):
                        raise ValueError()
                except ValueError:
                    raise PilotError('exact_after_until_query_required', 400) from None
                method = self.pilot.broker_lifecycle if parsed.path == '/api/broker-lifecycle' else self.pilot.broker_snapshot
                return self.send(200, method(query['after'][0], query['until'][0]))
            if self.path in ('/healthz', '/api/health'):
                return self.send(200, {'service':'apex-paper-pilot','status':'up','release':self.pilot.env.get('APEX_SOURCE_SHA','local-unreleased')})
            if self.path in ['/', '/app.js', '/style.css']:
                path = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[self.path]
                mime = {'/':'text/html; charset=utf-8','/app.js':'application/javascript','/style.css':'text/css'}[self.path]
                return self.send(200,(HERE/path).read_text(),mime)
            if self.path == '/api/status':
                return self.send(200,self.pilot.status())
            if self.path == '/api/trade-context':
                return self.send(200,self.pilot.trade_context())
            if self.path == '/api/capability-status':
                return self.send(200,self.pilot.capability_status())
            if self.path == '/api/quote':
                self.pilot.account()
                return self.send(200,self.pilot.broker.quote())
            self.send(404,{'error':'not_found'})
        except PilotError as e:
            self.send(e.status,{'error':e.code})
        except RemoteError as e:
            self.send(502,{'error':'alpaca_http_'+str(e.status)})
        except Exception:
            self.send(503,{'error':'dependency_unavailable'})
    def do_POST(self):
        try:
            if self.path not in ('/api/paper-orders', '/api/reconcile-paper-order', '/api/capability-reports'):
                return self.send(404,{'error':'not_found'})
            if self.headers.get('X-Apex-Request') != 'paper-pilot' or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                raise PilotError('same_origin_json_request_required',403)
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 4096:
                raise PilotError('invalid_body_size',400)
            d=json.loads(self.rfile.read(length))
            if self.path == '/api/capability-reports':
                return self.send(200,self.pilot.capability_report(d))
            self.send(200,self.pilot.submit(d, reconcile_only=self.path == '/api/reconcile-paper-order'))
        except (ValueError, UnicodeError):
            self.send(400,{'error':'invalid_json'})
        except PilotError as e:
            self.send(e.status,{'error':e.code})
        except RemoteError as e:
            self.send(502,{'error':'alpaca_http_'+str(e.status),'action':'reconcile_same_request'})
        except Exception:
            self.send(503,{'error':'dependency_unavailable','action':'reconcile_same_request'})

def main():
    Handler.pilot=Pilot()
    ThreadingHTTPServer((os.environ.get('HOST','127.0.0.1'),int(os.environ.get('PORT','8080'))),Handler).serve_forever()

if __name__ == '__main__':
    main()

