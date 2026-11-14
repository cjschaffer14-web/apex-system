#!/usr/bin/env python3
"""Read-only lifecycle evidence and independent paper-broker accounting."""
import argparse
import datetime as dt
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

import broker_reconciliation as B

READ_PATHS = {'/v2/account', '/v2/positions', '/v2/account/activities', '/v2/orders'}


class LifecycleReadOnly:
    def __init__(self, credentials):
        self.headers = {'APCA-API-KEY-ID': credentials[0], 'APCA-API-SECRET-KEY': credentials[1]}

    def get(self, path, query=None):
        if path not in READ_PATHS:
            raise B.Blocked('endpoint_not_read_allowlisted')
        url = B.HOST + path + ('?' + urllib.parse.urlencode(query) if query else '')
        try:
            with B.open_read(urllib.request.Request(url, headers=self.headers, method='GET')) as response:
                raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise B.Blocked('broker_response_too_large')
            return json.loads(raw), B.digest(raw)
        except B.Blocked:
            raise
        except urllib.error.HTTPError as error:
            raise B.Blocked('broker_http_' + str(error.code)) from None
        except Exception:
            raise B.Blocked('broker_read_unavailable') from None


def collect(transport, after, until, clock=B.utc):
    start, end = B.timestamp(after), B.timestamp(until)
    if not 0 < (end-start).total_seconds() <= 86400 or end > B.timestamp(clock()):
        raise B.Blocked('invalid_daily_activity_window')
    captured_start = clock()
    account, account_hash = transport.get('/v2/account')
    B.identity(account)
    positions, position_hash = transport.get('/v2/positions')
    activities, activity_hashes, seen, token = [], [], set(), None
    for _ in range(100):
        query = {'after': after, 'until': until, 'direction': 'asc', 'page_size': 100}
        if token:
            query['page_token'] = token
        page, raw_hash = transport.get('/v2/account/activities', query)
        activity_hashes.append(raw_hash)
        if not isinstance(page, list):
            raise B.Blocked('invalid_activity_response')
        for row in page:
            if row['id'] in seen:
                raise B.Blocked('activity_pagination_duplicate_or_cycle')
            seen.add(row['id']); activities.append(row)
        if len(page) < 100:
            break
        token = page[-1]['id']
    else:
        raise B.Blocked('activity_pagination_limit')
    # Orders have a timestamp cursor rather than an activity-ID cursor. A full
    # 500-row day refuses completeness rather than lose same-time boundary rows.
    orders, order_hash = transport.get('/v2/orders', {'status': 'all', 'after': after, 'until': until,
                                                     'direction': 'asc', 'limit': 500, 'nested': 'false'})
    if not isinstance(orders, list) or len(orders) >= 500:
        raise B.Blocked('orders_daily_page_limit_requires_narrower_window')
    final, final_hash = transport.get('/v2/account')
    B.identity(final)
    for key in ('cash', 'equity', 'long_market_value', 'short_market_value'):
        if B.number(account[key]) != B.number(final[key]):
            raise B.Blocked('broker_changed_during_snapshot')
    captured_end = clock()
    if not 0 <= (B.timestamp(captured_end)-B.timestamp(captured_start)).total_seconds() <= 120:
        raise B.Blocked('snapshot_capture_window_exceeded')
    selected = {key: account.get(key) for key in ('id', 'account_number', 'created_at', 'currency', 'status', 'cash', 'equity', 'long_market_value', 'short_market_value')}
    return {'schema': 'apex_broker_lifecycle_evidence/1', 'environment': 'paper', 'account_number': B.ACCOUNT,
            'capture_started_utc': captured_start, 'capture_ended_utc': captured_end, 'account': selected,
            'positions': positions, 'orders': orders, 'activities': activities,
            'coverage': {'start': after, 'end': until, 'activities_complete': True, 'orders_complete': True,
                         'boundary_policy': 'caller overlaps adjacent windows and deduplicates exact IDs',
                         'limit': 'retained provider creation-time activity history; delayed/revised postings possible'},
            'provenance': {'account_start_sha256': account_hash, 'account_end_sha256': final_hash,
                           'positions_sha256': position_hash, 'activities_page_sha256': activity_hashes,
                           'orders_sha256': order_hash, 'collector_source_sha256': B.digest(Path(__file__).read_bytes())},
            'profitability_verified': False, 'orders_submitted': 0}


def collect_history(transport, until, save_window, clock=B.utc):
    """Bounded daily overlap; adapt orders windows instead of losing cursor ties."""
    account, _ = transport.get('/v2/account'); B.identity(account)
    start = B.timestamp(account['created_at'])-dt.timedelta(seconds=1)
    end = B.timestamp(until)
    if end > B.timestamp(clock()) or start >= end or (end-start).days > 366:
        raise B.Blocked('invalid_lifecycle_history_window')
    windows = []
    def run_window(begin, finish, depth=0):
        try:
            receipt = collect(transport, begin.isoformat(), finish.isoformat(), clock)
        except B.Blocked as error:
            if str(error) != 'orders_daily_page_limit_requires_narrower_window' or depth >= 10:
                raise
            midpoint = begin+(finish-begin)/2
            run_window(begin, midpoint+dt.timedelta(microseconds=1), depth+1)
            run_window(midpoint-dt.timedelta(microseconds=1), finish, depth+1)
            return
        raw_hash = save_window(receipt)
        if not B.source_hash(raw_hash):
            raise B.Blocked('saved_window_hash_required')
        windows.append((receipt, raw_hash))
    while start < end:
        finish = min(start+dt.timedelta(hours=24)-dt.timedelta(seconds=1), end)
        run_window(start, finish)
        if finish == end:
            break
        start = finish-dt.timedelta(seconds=1)
    return merge_windows(windows)


def merge_windows(windows):
    """Merge retained provider evidence; refuse gaps, forks or inconsistent scope."""
    if not windows:
        raise B.Blocked('lifecycle_windows_missing')
    activities, orders, sources, intervals = {}, {}, [], []
    for item, source_hash in windows:
        if item.get('schema') != 'apex_broker_lifecycle_evidence/1' or item.get('environment') != 'paper' or item.get('account_number') != B.ACCOUNT:
            raise B.Blocked('lifecycle_scope_mismatch')
        B.identity(item['account']); B.reject_floats(item)
        coverage = item['coverage']
        if coverage.get('activities_complete') is not True or coverage.get('orders_complete') is not True:
            raise B.Blocked('lifecycle_incomplete_window')
        start, end = B.timestamp(coverage['start']), B.timestamp(coverage['end'])
        if not 0 < (end-start).total_seconds() <= 86400:
            raise B.Blocked('invalid_daily_activity_window')
        intervals.append((start, end)); sources.append(source_hash)
        for collection, records in ((activities, item['activities']), (orders, item['orders'])):
            for row in records:
                previous = collection.get(row['id'])
                if previous is not None and previous != row:
                    raise B.Blocked('lifecycle_duplicate_identity_conflict')
                collection[row['id']] = row
    intervals.sort(); covered = intervals[0][1]
    for start, end in intervals[1:]:
        if start > covered:
            raise B.Blocked('lifecycle_coverage_gap')
        covered = max(covered, end)
    latest = max((item for item, _ in windows), key=lambda item: B.timestamp(item['capture_ended_utc']))
    if len({item['account']['id'] for item, _ in windows}) != 1:
        raise B.Blocked('lifecycle_account_uuid_mismatch')
    return {'schema': 'apex_broker_lifecycle_bundle/1', 'account_number': B.ACCOUNT, 'environment': 'paper',
            'account': latest['account'], 'positions': latest['positions'], 'orders': sorted(orders.values(), key=lambda row: row['id']),
            'activities': sorted(activities.values(), key=lambda row: row['id']),
            'coverage': {'start': intervals[0][0].isoformat(), 'end': covered.isoformat(), 'activities_complete': True,
                         'orders_complete': True, 'retention_limit': 'retained provider activity/order history; delayed/revised postings remain possible'},
            'capture_started_utc': latest['capture_started_utc'], 'capture_ended_utc': latest['capture_ended_utc'],
            'provenance': {'window_receipt_sha256': sorted(set(sources)), 'window_count': len(windows),
                           'collector_source_sha256': B.digest(Path(__file__).read_bytes())},
            'profitability_verified': False, 'orders_submitted': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--after'); parser.add_argument('--until', required=True)
    parser.add_argument('--since-account-creation', action='store_true')
    parser.add_argument('--auth-mode', choices=('workload', 'legacy-manual'), default='workload')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.after) == args.since_account_creation:
        parser.error('choose --after or --since-account-creation')
    try:
        transport = LifecycleReadOnly(B.keys(args.auth_mode))
        if args.since_account_creation:
            def save_window(item):
                return B.digest(B.publish(item, args.output/'windows').read_bytes())
            receipt = collect_history(transport, args.until, save_window)
        else:
            receipt = collect(transport, args.after, args.until)
    except B.Blocked as error:
        receipt = {'schema': 'apex_broker_lifecycle_evidence/1', 'state': 'blocked', 'reason': str(error),
                   'observed_utc': B.utc(), 'profitability_verified': False, 'orders_submitted': 0}
    except Exception:
        receipt = {'schema': 'apex_broker_lifecycle_evidence/1', 'state': 'blocked', 'reason': 'invalid_input_or_provider_schema',
                   'observed_utc': B.utc(), 'profitability_verified': False, 'orders_submitted': 0}
    path = B.publish(receipt, args.output)
    print(B.canonical({'receipt': str(path), 'state': receipt.get('state', 'observed'), 'reason': receipt.get('reason'),
                       'activities': len(receipt.get('activities', [])), 'orders': len(receipt.get('orders', []))}), end='')
    return 2 if receipt.get('state') == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
