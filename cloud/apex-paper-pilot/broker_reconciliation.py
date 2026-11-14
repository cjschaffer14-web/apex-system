#!/usr/bin/env python3
"""Read-only Alpaca paper evidence. No trading methods or automatic authorization."""
import argparse
import base64
import datetime as dt
from decimal import Decimal, Context, localcontext, ROUND_HALF_EVEN
from functools import wraps
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

VERSION = '1.2'
ACCOUNT = 'PA3YUD5NA'
HOST = 'https://paper-api.alpaca.markets'
PROJECT = 'alert-maker-509913-m7'
SECRET_NAMES = ('apex-pilot-paper-key', 'apex-pilot-paper-secret')
PATHS = {'/v2/account', '/v2/positions', '/v2/account/activities'}
TOL = Decimal('0.01')


class Blocked(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Blocked('credential_bearing_redirect_refused')


def open_read(request):
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=15)


def number(v):
    if isinstance(v, (bool, float)):
        raise Blocked('decimal_string_required')
    try:
        n = Decimal(v)
    except Exception:
        raise Blocked('invalid_decimal') from None
    if not n.is_finite():
        raise Blocked('nonfinite_decimal')
    return n


def timestamp(v):
    try:
        t = dt.datetime.fromisoformat(v.replace('Z', '+00:00'))
        if t.tzinfo is None:
            raise ValueError()
        return t.astimezone(dt.timezone.utc)
    except Exception:
        raise Blocked('invalid_aware_timestamp') from None


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'


def decimal_context(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
            return function(*args, **kwargs)
    return wrapped


def reject_floats(value):
    if isinstance(value, float):
        raise Blocked('decimal_string_required')
    if isinstance(value, dict):
        for item in value.values():
            reject_floats(item)
    elif isinstance(value, list):
        for item in value:
            reject_floats(item)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def source_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def workload_keys():
    """Explicit machine ADC only; never fallback to human gcloud or a key file."""
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.auth.external_account import Credentials as External
        from google.auth.compute_engine.credentials import Credentials as Metadata
    except ImportError:
        raise Blocked('google_auth_dependency_missing') from None
    try:
        credential, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        # Reject user ADC, service-account private keys, impersonation sourced by
        # a user, and arbitrary credential types. WIF and attached identity only.
        if not isinstance(credential, (External, Metadata)):
            raise Blocked('unattended_requires_workload_identity')
        credential.refresh(Request())
        values = []
        for name in SECRET_NAMES:
            url = 'https://secretmanager.googleapis.com/v1/projects/' + PROJECT + '/secrets/' + name + '/versions/latest:access'
            request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + credential.token}, method='GET')
            with open_read(request) as response:
                values.append(base64.b64decode(json.load(response)['payload']['data'], validate=True).decode().strip())
        if not all(values):
            raise Blocked('empty_broker_credentials')
        return tuple(values)
    except Blocked:
        raise
    except Exception:
        # Provider exceptions can contain credential material: never serialize them.
        raise Blocked('workload_identity_or_secret_access_unavailable') from None


def keys(mode):
    if mode == 'workload':
        return workload_keys()
    if mode != 'legacy-manual':
        raise Blocked('unsupported_auth_mode')
    try:
        path = Path.home() / 'apex-live/creds.py'
        spec = importlib.util.spec_from_file_location('apex_existing_creds', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.alpaca_paper_keys()
    except Exception:
        raise Blocked('legacy_human_cloud_auth_or_secret_access_unavailable') from None


class PaperReadOnly:
    def __init__(self, credentials):
        self.headers = {'APCA-API-KEY-ID': credentials[0], 'APCA-API-SECRET-KEY': credentials[1]}

    def get(self, path, query=None):
        if path not in PATHS:
            raise Blocked('endpoint_not_read_allowlisted')
        url = HOST + path
        if query:
            url += '?' + urllib.parse.urlencode(query)
        try:
            req = urllib.request.Request(url, headers=self.headers, method='GET')
            with open_read(req) as response:
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise Blocked('broker_response_too_large')
            return json.loads(raw), digest(raw)
        except Blocked:
            raise
        except urllib.error.HTTPError as e:
            raise Blocked('broker_http_' + str(e.code)) from None
        except Exception:
            raise Blocked('broker_read_unavailable') from None


def identity(account):
    if account.get('account_number') != ACCOUNT:
        raise Blocked('paper_account_identity_mismatch')
    if account.get('currency') != 'USD':
        raise Blocked('broker_currency_mismatch')
    if account.get('status') != 'ACTIVE':
        raise Blocked('broker_account_not_active')
    for field in ('cash', 'equity', 'long_market_value', 'short_market_value'):
        number(account[field])


def snapshot(transport, after, until, clock=utc):
    if timestamp(after) >= timestamp(until):
        raise Blocked('invalid_activity_window')
    started = clock()
    if timestamp(until) > timestamp(started):
        raise Blocked('activity_window_in_future')
    account, account_hash = transport.get('/v2/account')
    identity(account)  # No further endpoints called for a wrong account.
    positions, positions_hash = transport.get('/v2/positions')
    if not isinstance(positions, list):
        raise Blocked('invalid_positions_response')
    parsed = {}
    for p in positions:
        symbol = p['symbol']
        if symbol in parsed:
            raise Blocked('duplicate_position_symbol')
        parsed[symbol] = {'qty': str(number(p['qty'])), 'market_value': str(number(p['market_value']))}
    activities, hashes, seen, page_token = [], [], {}, None
    for _ in range(100):
        query = {'after': after, 'until': until, 'direction': 'asc', 'page_size': 100}
        if page_token:
            query['page_token'] = page_token
        page, raw_hash = transport.get('/v2/account/activities', query)
        hashes.append(raw_hash)
        if not isinstance(page, list):
            raise Blocked('invalid_activity_response')
        for a in page:
            aid = a['id']
            if aid in seen:
                raise Blocked('activity_pagination_duplicate_or_cycle')
            seen[aid] = True
            fields = ('id', 'activity_type', 'date', 'transaction_time', 'net_amount', 'symbol', 'qty', 'price', 'side', 'order_id')
            selected = {k: a[k] for k in fields if k in a}
            reject_floats(selected)
            for k in ('qty', 'price', 'net_amount'):
                if k in selected:
                    selected[k] = str(number(selected[k]))
            activities.append(selected)
        if len(page) < 100:
            break
        page_token = page[-1]['id']
    else:
        raise Blocked('activity_pagination_limit')
    final, final_hash = transport.get('/v2/account')
    identity(final)
    # Account reads sandwich the evidence. This rejects observed concurrent
    # changes, but does not assert an atomic provider snapshot.
    for field in ('cash', 'equity', 'long_market_value', 'short_market_value'):
        if number(final[field]) != number(account[field]):
            raise Blocked('broker_changed_during_snapshot')
    ended = clock()
    duration = (timestamp(ended) - timestamp(started)).total_seconds()
    if duration < 0 or duration > 120:
        raise Blocked('snapshot_capture_window_exceeded')
    values = {k: account[k] for k in ('account_number', 'currency', 'status', 'cash', 'equity', 'long_market_value', 'short_market_value')}
    return {'schema': 'apex_broker_snapshot/1', 'version': VERSION, 'state': 'broker_snapshot_observed', 'mode': 'paper',
            'venue': 'alpaca', 'ledger_kind': 'broker_account', 'capture_started_utc': started, 'capture_ended_utc': ended,
            'account': values, 'positions': parsed, 'activities': activities,
            'activity_window': {'after': after, 'until': until, 'pagination_complete': True,
                                'coverage': 'creation_time_query; delayed provider postings remain possible'},
            'raw_response_sha256': {'account_start': account_hash, 'account_end': final_hash, 'positions': positions_hash, 'activities_pages': hashes},
            'atomic_provider_snapshot': False, 'nav_reconciliation': 'not_established', 'profitability_verified': False, 'orders_submitted': 0}


@decimal_context
def reconcile(observed, shadow):
    validate_snapshot(observed)
    reject_floats(shadow)
    if shadow.get('schema') != 'apex_broker_shadow/1' or shadow.get('ledger_kind') != 'broker_shadow':
        raise Blocked('matched_broker_shadow_required_virtual_books_refused')
    a = observed['account']
    for key, expected in (('account_number', ACCOUNT), ('currency', 'USD'), ('mode', 'paper'), ('venue', 'alpaca')):
        if shadow.get(key) != expected:
            raise Blocked('shadow_scope_mismatch_' + key)
    # The matched ledger must cover the provider capture window. This explicit
    # declaration is evidence to audit, not a timestamp alignment assumption.
    if shadow.get('valuation_window') != {'started_utc': observed['capture_started_utc'], 'ended_utc': observed['capture_ended_utc']}:
        raise Blocked('shadow_valuation_window_mismatch')
    if not source_hash(shadow.get('source_sha256')):
        raise Blocked('shadow_source_hash_required')
    s_positions = shadow.get('positions', {})
    if set(s_positions) != set(observed['positions']):
        raise Blocked('shadow_position_set_mismatch')
    qty_residual = {s: str(number(s_positions[s]['qty']) - number(p['qty'])) for s, p in observed['positions'].items()}
    market_residual = {s: str(number(s_positions[s]['market_value']) - number(p['market_value'])) for s, p in observed['positions'].items()}
    cash, equity = number(shadow['cash']), number(shadow['equity'])
    residuals = {'cash': str(cash-number(a['cash'])), 'equity': str(equity-number(a['equity'])),
                 'shadow_cash_plus_positions': str(cash+sum((number(p['market_value']) for p in s_positions.values()), Decimal(0))-equity),
                 'broker_cash_plus_positions': str(number(a['cash'])+sum((number(p['market_value']) for p in observed['positions'].values()), Decimal(0))-number(a['equity']))}
    matched = all(number(v) == 0 for v in qty_residual.values()) and all(abs(number(v)) <= TOL for v in list(residuals.values()) + list(market_residual.values()))
    return {'state': 'matched_within_tolerance' if matched else 'blocked_balance_or_position_mismatch',
            'absolute_usd_tolerance': str(TOL), 'quantity_tolerance': '0', 'residuals': residuals,
            'quantity_residuals': qty_residual, 'market_value_residuals': market_residual,
            'shadow_source_sha256': shadow['source_sha256'], 'profitability_verified': False, 'orders_submitted': 0}


def validate_snapshot(value):
    reject_floats(value)
    if value.get('schema') != 'apex_broker_snapshot/1' or value.get('state') != 'broker_snapshot_observed':
        raise Blocked('broker_snapshot_missing')
    if value.get('mode') != 'paper' or value.get('venue') != 'alpaca' or value.get('ledger_kind') != 'broker_account':
        raise Blocked('broker_snapshot_scope_mismatch')
    identity(value['account'])
    for position in value['positions'].values():
        number(position['qty'])
        number(position['market_value'])
    for activity in value['activities']:
        for key in ('qty', 'price', 'net_amount'):
            if key in activity:
                number(activity[key])
    duration = (timestamp(value['capture_ended_utc'])-timestamp(value['capture_started_utc'])).total_seconds()
    if duration < 0 or duration > 120:
        raise Blocked('snapshot_capture_window_exceeded')


@decimal_context
def flow_adjusted_pnl(previous, current, external_flows):
    """Dollar P&L only; no fabricated TWR/IRR without flow-time valuations."""
    for item in (previous, current):
        validate_snapshot(item)
    reject_floats(external_flows)
    if previous['account']['account_number'] != current['account']['account_number'] or previous['account']['currency'] != current['account']['currency']:
        raise Blocked('performance_account_or_currency_mismatch')
    start, end = previous['capture_ended_utc'], current['capture_ended_utc']
    if timestamp(start) >= timestamp(end):
        raise Blocked('performance_window_invalid')
    if external_flows.get('schema') != 'apex_external_flows/1' or external_flows.get('account_number') != ACCOUNT or external_flows.get('currency') != 'USD':
        raise Blocked('verified_external_flow_scope_required')
    if external_flows.get('after') != start or external_flows.get('until') != end or external_flows.get('complete') is not True:
        raise Blocked('complete_external_flow_window_required')
    if not source_hash(external_flows.get('source_sha256')):
        raise Blocked('external_flow_source_hash_required')
    seen, total = set(), Decimal(0)
    for f in external_flows['flows']:
        if f['id'] in seen:
            raise Blocked('duplicate_external_flow')
        seen.add(f['id'])
        if not timestamp(start) < timestamp(f['at_utc']) <= timestamp(end):
            raise Blocked('external_flow_outside_window')
        if f['kind'] not in ('deposit', 'withdrawal'):
            raise Blocked('unsupported_external_flow_kind')
        amount = number(f['amount_usd'])
        if amount < 0:
            raise Blocked('external_flow_amount_must_be_unsigned')
        total += amount if f['kind'] == 'deposit' else -amount
    pnl = number(current['account']['equity']) - number(previous['account']['equity']) - total
    return {'state': 'external_flow_adjusted_dollar_pnl', 'after': start, 'until': end, 'net_external_flows_usd': str(total),
            'broker_paper_pnl_usd': str(pnl), 'time_weighted_return': None, 'internal_rate_of_return': None,
            'limit': 'Flow evidence completeness is asserted by its source; delayed postings may revise it. Not frozen virtual-book P&L or actual profit.',
            'external_flow_source_sha256': external_flows['source_sha256'], 'profitability_verified': False}


def publish(receipt, output):
    raw = canonical(receipt).encode()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = output / ('receipt-' + digest(raw) + '.json')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        if path.read_bytes() != raw:
            raise Blocked('immutable_receipt_collision')
    if path.read_bytes() != raw:
        raise Blocked('receipt_readback_mismatch')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-mode', choices=('workload', 'legacy-manual'), default='workload')
    parser.add_argument('--after')
    parser.add_argument('--until')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--shadow', type=Path)
    parser.add_argument('--snapshot-input', type=Path, help='Offline saved broker receipt; no authentication or network')
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--external-flows', type=Path)
    args = parser.parse_args()
    if not args.snapshot_input and not (args.after and args.until):
        parser.error('network snapshot requires --after and --until')
    if bool(args.previous) != bool(args.external_flows):
        parser.error('--previous and --external-flows must be supplied together')
    try:
        if args.snapshot_input:
            result = json.loads(args.snapshot_input.read_text())
            validate_snapshot(result)
            result['input_receipt_sha256'] = digest(args.snapshot_input.read_bytes())
        else:
            result = snapshot(PaperReadOnly(keys(args.auth_mode)), args.after, args.until)
        if args.shadow:
            result['reconciliation'] = reconcile(result, json.loads(args.shadow.read_text()))
            result['nav_reconciliation'] = result['reconciliation']['state']
        if args.previous:
            result['flow_adjusted_performance'] = flow_adjusted_pnl(json.loads(args.previous.read_text()), result, json.loads(args.external_flows.read_text()))
    except Blocked as e:
        result = {'schema': 'apex_broker_snapshot/1', 'version': VERSION, 'state': 'blocked', 'reason': str(e), 'observed_utc': utc(),
                  'mode': 'paper', 'auth_mode': args.auth_mode, 'nav_reconciliation': 'not_established', 'profitability_verified': False, 'orders_submitted': 0}
    except Exception:
        result = {'schema': 'apex_broker_snapshot/1', 'version': VERSION, 'state': 'blocked', 'reason': 'invalid_local_input_or_provider_schema', 'observed_utc': utc(),
                  'mode': 'paper', 'nav_reconciliation': 'not_established', 'profitability_verified': False, 'orders_submitted': 0}
    result['auth_mode'] = 'offline_saved_evidence' if args.snapshot_input else args.auth_mode
    result['source_sha256'] = digest(Path(__file__).read_bytes())
    path = publish(result, args.output)
    print(canonical({'state': result['state'], 'nav_reconciliation': result.get('nav_reconciliation'),
                     'reason': result.get('reason'), 'receipt': str(path), 'sha256': digest(path.read_bytes()), 'orders_submitted': 0}), end='')
    successful = result['state'] == 'broker_snapshot_observed' and not result.get('nav_reconciliation', '').startswith('blocked_')
    return 0 if successful else 2


if __name__ == '__main__':
    raise SystemExit(main())
