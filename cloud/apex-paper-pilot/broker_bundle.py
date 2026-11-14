#!/usr/bin/env python3
"""Offline, deterministic assembly of exact-byte daily broker receipts."""
import argparse
import json
from pathlib import Path

import broker_reconciliation as B


def assemble(raw_windows):
    """Pure function: JSON receipt bytes in; validated lifecycle bundle out."""
    windows, activities, orders = {}, {}, {}
    intervals = []
    account_scope = None
    for raw in raw_windows:
        if not isinstance(raw, bytes):
            raise B.Blocked('exact_window_receipt_bytes_required')
        sha = B.digest(raw)
        if sha in windows:
            continue
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeError):
            raise B.Blocked('invalid_window_receipt_json') from None
        if item.get('schema') != 'apex_broker_lifecycle_evidence/1' or item.get('environment') != 'paper' or item.get('account_number') != B.ACCOUNT:
            raise B.Blocked('lifecycle_scope_mismatch')
        B.reject_floats(item); B.identity(item['account'])
        account = item['account']
        created = B.timestamp(account['created_at'])
        scope = (account['id'], account['account_number'], account['currency'], created)
        if account_scope is None:
            account_scope = scope
        elif scope != account_scope:
            raise B.Blocked('lifecycle_account_scope_or_creation_mismatch')
        coverage = item['coverage']
        if coverage.get('activities_complete') is not True or coverage.get('orders_complete') is not True:
            raise B.Blocked('lifecycle_incomplete_window')
        start, end = B.timestamp(coverage['start']), B.timestamp(coverage['end'])
        captured_start, captured_end = B.timestamp(item['capture_started_utc']), B.timestamp(item['capture_ended_utc'])
        if not 0 < (end-start).total_seconds() <= 86400 or end > captured_end:
            raise B.Blocked('invalid_daily_window_or_future_cutoff')
        if not 0 <= (captured_end-captured_start).total_seconds() <= 120:
            raise B.Blocked('snapshot_capture_window_exceeded')
        if not isinstance(item['positions'], list):
            raise B.Blocked('positions_array_required')
        for collection, field in ((activities, 'activities'), (orders, 'orders')):
            if not isinstance(item[field], list):
                raise B.Blocked('window_records_array_required')
            for row in item[field]:
                key = row.get('id')
                if not isinstance(key, str) or not key:
                    raise B.Blocked('broker_record_identity_required')
                if key in collection and collection[key] != row:
                    raise B.Blocked('lifecycle_duplicate_identity_conflict')
                collection[key] = row
        windows[sha] = item
        intervals.append((start, end))
    if not windows:
        raise B.Blocked('lifecycle_windows_missing')
    intervals.sort()
    covered = intervals[0][1]
    for start, end in intervals[1:]:
        if start > covered:
            raise B.Blocked('lifecycle_coverage_gap')
        covered = max(covered, end)
    if intervals[0][0] > account_scope[3]:
        raise B.Blocked('coverage_must_start_at_account_creation')
    latest_time = max(B.timestamp(item['capture_ended_utc']) for item in windows.values())
    latest = [(sha, item) for sha, item in windows.items() if B.timestamp(item['capture_ended_utc']) == latest_time]
    latest.sort(key=lambda pair: pair[0])
    latest_sha, selected = latest[0]
    selected_positions = sorted(selected['positions'], key=lambda row: row['symbol'])
    for _, candidate in latest[1:]:
        if candidate['account'] != selected['account'] or sorted(candidate['positions'], key=lambda row: row['symbol']) != selected_positions:
            raise B.Blocked('ambiguous_same_time_final_broker_observation')
    if not 0 <= (latest_time-covered).total_seconds() <= 120:
        raise B.Blocked('final_broker_observation_outside_replay_capture_window')
    return {'schema': 'apex_broker_lifecycle_bundle/1', 'account_number': B.ACCOUNT, 'environment': 'paper',
            'account': selected['account'], 'positions': selected_positions,
            'orders': sorted(orders.values(), key=lambda row: row['id']),
            'activities': sorted(activities.values(), key=lambda row: row['id']),
            'coverage': {'start': intervals[0][0].isoformat(), 'end': covered.isoformat(),
                         'activities_complete': True, 'orders_complete': True,
                         'retention_limit': 'retained provider history; delayed/revised postings remain possible'},
            'capture_started_utc': selected['capture_started_utc'], 'capture_ended_utc': selected['capture_ended_utc'],
            'provenance': {'assembler_version': '1.0', 'window_receipt_sha256': sorted(windows), 'window_count': len(windows),
                           'selected_observation_window_sha256': latest_sha, 'start_at_account_creation_verified': True},
            'profitability_verified': False, 'orders_submitted': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window', type=Path, action='append', default=[], help='Exact daily receipt; repeat as needed')
    parser.add_argument('--windows-dir', type=Path, help='Read *.json daily receipts, ignoring explicitly different schemas')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.window and not args.windows_dir:
        parser.error('at least one --window or --windows-dir is required')
    try:
        raw_windows = [path.read_bytes() for path in args.window]
        ignored = 0
        if args.windows_dir:
            for path in sorted(args.windows_dir.glob('*.json')):
                raw = path.read_bytes()
                try:
                    schema = json.loads(raw).get('schema')
                except (ValueError, UnicodeError, AttributeError):
                    raise B.Blocked('invalid_json_in_selected_windows_directory') from None
                if schema == 'apex_broker_lifecycle_evidence/1':
                    raw_windows.append(raw)
                else:
                    ignored += 1
        result = assemble(raw_windows)
        result['provenance']['assembler_code_sha256'] = B.digest(Path(__file__).read_bytes())
        path = B.publish(result, args.output)
        print(B.canonical({'state': 'retained_history_assembled', 'bundle': str(path), 'bundle_sha256': B.digest(path.read_bytes()),
                           'windows': result['provenance']['window_count'], 'ignored_other_schema_files': ignored,
                           'coverage': result['coverage'], 'capture_ended_utc': result['capture_ended_utc'],
                           'profitability_verified': False, 'orders_submitted': 0}), end='')
        return 0
    except B.Blocked as error:
        print(B.canonical({'state': 'blocked', 'reason': str(error)}), end='')
        return 2
    except Exception:
        print(B.canonical({'state': 'blocked', 'reason': 'invalid_local_receipt_or_schema'}), end='')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
