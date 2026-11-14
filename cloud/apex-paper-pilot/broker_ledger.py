#!/usr/bin/env python3
"""Independent event reconstruction of one Alpaca paper broker account."""
import argparse
from collections import Counter, defaultdict, deque
from decimal import Decimal, ROUND_HALF_EVEN
import fcntl
import json
import os
from pathlib import Path
import tempfile

import broker_reconciliation as B

POLICY = {
    'id': 'alpaca_nonregulatory_usd_nearest_cent_half_even/1',
    'url': 'https://forum.alpaca.markets/t/does-alpaca-rounds-up-or-down-to-the-nearest-penny-when-dealing-with-account-balances/17303',
    'author': 'Dan_Whitnable_Alpaca', 'published_utc': '2025-08-07T23:53:00Z',
    'source_excerpt': 'Other than the regulatory fees, other transactions are rounded according to the IEEE 754 standard for floating-point arithmetic.',
    'rule': 'USD transaction cash rounded to 0.01 ROUND_HALF_EVEN; preserve posted fee net_amount and base-asset quantity without re-rounding',
    'interpretation': 'Apply provider transaction rule to each paper crypto FILL cash posting; the cited reply does not explicitly identify crypto paper FILL granularity. Corroborate against independent historical checkpoints.',
}
POLICY_SHA = B.digest(B.canonical(POLICY).encode())


def symbol(value):
    if not isinstance(value, str) or not value.endswith('USD') or not value.replace('/', '').isalnum():
        raise B.Blocked('unsupported_usd_asset_symbol')
    return value.replace('/', '')


def activity_time(row):
    value = row.get('transaction_time') if row.get('activity_type') == 'FILL' else row.get('created_at')
    if not value:
        raise B.Blocked('activity_exact_timestamp_missing')
    return B.timestamp(value)


def baseline_from_preflight(preflight, source_sha256):
    """Extract prior observation only; never initialize from the current balance."""
    status, context = preflight['cloud_status'], preflight['preflight_context']
    if preflight.get('account_number') != B.ACCOUNT or context.get('account_number') != B.ACCOUNT:
        raise B.Blocked('baseline_account_mismatch')
    if status.get('account') != 'verified_distinct' or context.get('mode') != 'paper-only':
        raise B.Blocked('baseline_not_verified_paper_account')
    if B.number(status['cash']) != B.number(status['equity']) or context.get('btc_positions') != [] or context.get('open_order_count') != 0:
        raise B.Blocked('baseline_not_flat_preflight')
    if status.get('account_suffix') != context.get('account_suffix') or not B.source_hash(source_sha256):
        raise B.Blocked('baseline_identity_or_source_missing')
    return {'schema': 'apex_broker_opening_baseline/1', 'account_number': B.ACCOUNT, 'mode': 'paper', 'currency': 'USD',
            'asof_utc': status['checked_at'], 'account_id_suffix': status['account_suffix'],
            'cash': str(B.number(status['cash'])), 'equity': str(B.number(status['equity'])), 'positions': {},
            'flat_proof': 'observed cash equals equity, BTC empty and no open orders; independently require lifecycle from account creation with no prior security activities',
            'source_sha256': source_sha256, 'source_kind': 'historical_cloud_broker_preflight', 'source_run_id': preflight['run_id']}


def take(lots, amount):
    basis = Decimal(0)
    while amount > 0:
        if not lots:
            raise B.Blocked('fifo_sell_or_fee_exceeds_reconstructed_inventory')
        quantity, cost = lots[0]
        used = min(quantity, amount)
        removed = cost * used / quantity
        basis += removed; amount -= used
        if used == quantity:
            lots.popleft()
        else:
            lots[0] = (quantity-used, cost-removed)
    return basis


@B.decimal_context
def reconstruct(bundle, baseline, bundle_sha256, baseline_sha256, checkpoints=None):
    if bundle.get('schema') != 'apex_broker_lifecycle_bundle/1' or bundle.get('environment') != 'paper' or bundle.get('account_number') != B.ACCOUNT:
        raise B.Blocked('broker_lifecycle_bundle_required')
    if baseline.get('schema') != 'apex_broker_opening_baseline/1' or baseline.get('account_number') != B.ACCOUNT or baseline.get('mode') != 'paper' or baseline.get('currency') != 'USD':
        raise B.Blocked('verified_opening_baseline_required')
    if not all(B.source_hash(value) for value in (bundle_sha256, baseline_sha256, baseline.get('source_sha256'))):
        raise B.Blocked('source_hash_required')
    B.reject_floats(bundle); B.reject_floats(baseline); B.identity(bundle['account'])
    if baseline.get('source_kind') != 'historical_cloud_broker_preflight' or baseline.get('positions') != {}:
        raise B.Blocked('supported_flat_historical_baseline_required')
    if not bundle['account']['id'].endswith(baseline['account_id_suffix']):
        raise B.Blocked('baseline_account_uuid_mismatch')
    cover = bundle['coverage']
    if cover.get('activities_complete') is not True or cover.get('orders_complete') is not True:
        raise B.Blocked('lifecycle_coverage_incomplete')
    created, start, end = map(B.timestamp, (bundle['account']['created_at'], cover['start'], cover['end']))
    base_time = B.timestamp(baseline['asof_utc'])
    if start > created or not created <= base_time < end:
        raise B.Blocked('coverage_must_start_at_account_creation')
    activity_ids, order_ids = set(), set()
    for row in bundle['activities']:
        if row['id'] in activity_ids:
            raise B.Blocked('duplicate_activity_id')
        activity_ids.add(row['id'])
    orders = {}
    for row in bundle['orders']:
        if row['id'] in order_ids:
            raise B.Blocked('duplicate_order_id')
        order_ids.add(row['id']); orders[row['id']] = row
    before = [row for row in bundle['activities'] if activity_time(row) <= base_time]
    # Opening flat inference is independently constrained by all retained events
    # since account creation. General journals are not assumed to be deposits.
    if not before or any(row.get('activity_type') != 'JNLC' or B.number(row.get('net_amount', '0')) <= 0 or row.get('currency') != 'USD' for row in before):
        raise B.Blocked('opening_baseline_security_or_unknown_activity')
    opening_funding = sum((B.number(row['net_amount']) for row in before), Decimal(0))
    if opening_funding != B.number(baseline['cash']) or B.number(baseline['equity']) != opening_funding:
        raise B.Blocked('opening_funding_does_not_confirm_historical_baseline')
    cash = B.number(baseline['cash']); exact_cash = cash
    lots, inventory, base_fees = defaultdict(deque), defaultdict(Decimal), defaultdict(Decimal)
    posted_gross = exact_gross = cash_fees = fee_basis = realized_gross = Decimal(0)
    external_flows, unknown, counts, matched_orders, journal = [], [], Counter(), set(), []
    fill_quantity_by_order = defaultdict(Decimal)
    checkpoint_specs = sorted(checkpoints or [], key=lambda row: B.timestamp(row['asof_utc']))
    pending_checks, checked = deque(checkpoint_specs), []
    def record_checkpoint(spec):
        if not B.source_hash(spec.get('source_sha256')) or spec.get('account_number') != B.ACCOUNT:
            raise B.Blocked('checkpoint_scope_or_source_missing')
        if not base_time < B.timestamp(spec['asof_utc']) <= end:
            raise B.Blocked('checkpoint_outside_replay_window')
        quantities = {s: str(q) for s, q in inventory.items() if q != 0}
        residual = cash-B.number(spec['cash'])
        flat = quantities == {} and spec.get('positions') == {}
        checked.append({'asof_utc': spec['asof_utc'], 'source_sha256': spec['source_sha256'],
                        'cash_residual_usd': str(residual), 'flat_inventory_matched': flat,
                        'within_tolerance': abs(residual) <= B.TOL and flat,
                        'scope': 'independent historical observed broker cash and flat positions'})
    events = sorted((row for row in bundle['activities'] if activity_time(row) > base_time), key=lambda row: (activity_time(row), row['id']))
    for row in events:
        when = activity_time(row)
        while pending_checks and B.timestamp(pending_checks[0]['asof_utc']) < when:
            record_checkpoint(pending_checks.popleft())
        kind = row['activity_type']; counts[kind] += 1; cash_delta = Decimal(0); qty_delta = Decimal(0); market = None
        if kind == 'FILL':
            if row.get('order_id') not in orders:
                raise B.Blocked('fill_order_history_missing')
            order = orders[row['order_id']]
            if order.get('side') != row.get('side') or symbol(order['symbol']) != symbol(row['symbol']):
                raise B.Blocked('fill_order_scope_mismatch')
            matched_orders.add(row['order_id']); market = symbol(row['symbol'])
            quantity, price = B.number(row['qty']), B.number(row['price'])
            if quantity <= 0 or price <= 0 or row.get('side') not in ('buy', 'sell'):
                raise B.Blocked('invalid_fill')
            fill_quantity_by_order[row['order_id']] += quantity
            notional = quantity*price
            sign = Decimal(-1) if row['side'] == 'buy' else Decimal(1)
            exact_delta = sign*notional
            cash_delta = exact_delta.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
            exact_cash += exact_delta; exact_gross += exact_delta; posted_gross += cash_delta
            qty_delta = -sign*quantity
            if row['side'] == 'buy':
                lots[market].append((quantity, -cash_delta))
            else:
                realized_gross += cash_delta-take(lots[market], quantity)
            inventory[market] += qty_delta
        elif kind in ('CFEE', 'FEE'):
            if row.get('status') != 'executed' or row.get('currency', 'USD') != 'USD':
                raise B.Blocked('unsupported_fee_currency_or_status')
            cash_delta = B.number(row.get('net_amount', '0'))
            if cash_delta > 0:
                raise B.Blocked('positive_fee_requires_explicit_rebate_classification')
            if 'qty' in row:
                market = symbol(row['symbol']); qty_delta = B.number(row['qty'])
                if kind != 'CFEE' or cash_delta != 0 or qty_delta >= 0 or row.get('description') != 'Coin Pair Transaction Fee (Non USD)':
                    raise B.Blocked('unsupported_base_fee_shape')
                fee_basis += take(lots[market], -qty_delta)
                inventory[market] += qty_delta; base_fees[market] -= qty_delta
            cash_fees -= cash_delta; exact_cash += cash_delta
        elif kind in ('CSD', 'CSW'):
            if row.get('currency', 'USD') != 'USD':
                raise B.Blocked('unsupported_capital_flow_currency')
            cash_delta = B.number(row['net_amount'])
            if (kind == 'CSD' and cash_delta <= 0) or (kind == 'CSW' and cash_delta >= 0):
                raise B.Blocked('capital_flow_sign_mismatch')
            external_flows.append({'id': row['id'], 'at_utc': when.isoformat(), 'net_amount_usd': str(cash_delta), 'kind': kind})
            exact_cash += cash_delta
        else:
            # A later JNLC might be a cash correction rather than external capital;
            # unknown activity is preserved and blocks a complete match.
            unknown.append({'id': row['id'], 'activity_type': kind})
        cash += cash_delta
        if market is not None and inventory[market] < 0:
            raise B.Blocked('negative_reconstructed_inventory')
        journal.append({'activity_id': row['id'], 'activity_type': kind, 'posting_time': when.isoformat(),
                        'cash_delta_usd': str(cash_delta), 'symbol': market, 'quantity_delta': str(qty_delta)})
    while pending_checks:
        record_checkpoint(pending_checks.popleft())
    order_quantity_residuals = {}
    for order_id, order in orders.items():
        filled = B.number(order['filled_qty'])
        if filled < 0:
            raise B.Blocked('negative_order_filled_quantity')
        residual = fill_quantity_by_order[order_id]-filled
        if residual != 0:
            order_quantity_residuals[order_id] = str(residual)
    broker_positions = {}
    for position in bundle['positions']:
        s = symbol(position['symbol'])
        if s in broker_positions:
            raise B.Blocked('duplicate_broker_position')
        broker_positions[s] = B.number(position['qty'])
    quantity_residuals = {s: str(inventory.get(s, Decimal(0))-broker_positions.get(s, Decimal(0))) for s in sorted(set(inventory)|set(broker_positions))}
    flat = all(q == 0 for q in inventory.values())
    # Non-flat NAV requires a separately sourced contemporaneous valuation; no
    # copying provider position market values into the reconstructed equity.
    equity = cash if flat else None
    cash_residual = cash-B.number(bundle['account']['cash'])
    equity_residual = equity-B.number(bundle['account']['equity']) if equity is not None else None
    qty_match = all(B.number(q) == 0 for q in quantity_residuals.values())
    checkpoints_match = bool(checked) and all(row['within_tolerance'] for row in checked)
    capture_gap = (B.timestamp(bundle['capture_ended_utc'])-end).total_seconds()
    matched = not unknown and not order_quantity_residuals and qty_match and flat and abs(cash_residual) <= B.TOL and abs(equity_residual) <= B.TOL and checkpoints_match and 0 <= capture_gap <= 120
    state = 'independently_matched_paper_broker_ledger' if matched else 'blocked_unmatched_broker_ledger'
    fee_state = {'state': 'all_retained_posted_fees_parsed' if not unknown else 'unknown_activity_blocks_completeness',
                 'cash_fee_usd': str(cash_fees), 'base_fee_quantity': {s: str(q) for s, q in sorted(base_fees.items())},
                 'fee_posting_count': counts['CFEE']+counts['FEE'], 'order_attribution': 'CFEE without order_id remains unallocated to individual orders',
                 'late_postings': 'possible; refresh overlapping historical windows', 'actual_live_fees_observed': False}
    residuals = {'cash_usd': str(cash_residual), 'equity_usd': str(equity_residual) if equity_residual is not None else None,
                 'quantity': quantity_residuals, 'unexplained_difference_usd': str(cash_residual)}
    baseline_ref = {'asof_utc': baseline['asof_utc'], 'cash': baseline['cash'], 'source_sha256': baseline['source_sha256'],
                    'baseline_sha256': baseline_sha256, 'opening_funding_activity_ids': [row['id'] for row in before]}
    display = {'state': state, 'reconstruction_state': state, 'independently_matched': matched, 'broker_asof_utc': bundle['capture_ended_utc'],
               'replay_cutoff_utc': cover['end'], 'cash_reconstructed_usd': str(cash), 'equity_reconstructed_usd': str(equity) if equity is not None else None,
               'broker_cash_usd': bundle['account']['cash'], 'broker_equity_usd': bundle['account']['equity'],
               'residuals': residuals, 'absolute_usd_tolerance': str(B.TOL), 'quantity_tolerance': '0', 'baseline': baseline_ref,
               'source_bundle_sha256': bundle_sha256, 'rounding_policy_sha256': POLICY_SHA,
               'precision_interpretation': POLICY['interpretation'], 'fee_evidence_completeness': fee_state,
               'historical_checkpoint_count': len(checked), 'historical_checkpoints_matched': checkpoints_match,
               'fill_count': counts['FILL'], 'order_history_count': len(orders), 'matched_fill_order_count': len(matched_orders),
               'unmatched_fill_count': 0, 'capture_after_replay_cutoff_seconds': capture_gap,
               'order_filled_quantity_mismatch_count': len(order_quantity_residuals),
               'profitability_verified': False, 'live_trading_authorized': False, 'orders_submitted': 0,
               'scope': 'Alpaca paper broker account only; separate from frozen virtual books and actual live trading'}
    return {'schema': 'apex_broker_ledger_report/1', 'version': '1.2', 'state': state, 'mode': 'paper', 'account_number': B.ACCOUNT,
            'independently_matched': matched, 'capture_ended_utc': bundle['capture_ended_utc'], 'display_summary': display,
            'baseline': baseline_ref, 'coverage': cover, 'rounding_policy': POLICY, 'rounding_policy_sha256': POLICY_SHA,
            'reconstructed': {'cash': str(cash), 'equity': str(equity) if equity is not None else None,
                              'positions': {s: str(q) for s, q in sorted(inventory.items())},
                              'fifo_open_cost_basis_usd': {s: str(sum((cost for _, cost in rows), Decimal(0))) for s, rows in sorted(lots.items())},
                              'fifo_realized_gross_pnl_usd': str(realized_gross), 'fifo_base_fee_cost_basis_usd': str(fee_basis),
                              'posted_fill_cashflow_usd': str(posted_gross), 'posted_cash_fees_usd': str(cash_fees),
                              'net_external_flows_after_baseline_usd': str(sum((B.number(f['net_amount_usd']) for f in external_flows), Decimal(0))),
                              'paper_broker_pnl_after_capital_flows_usd': str(cash-B.number(baseline['cash'])-sum((B.number(f['net_amount_usd']) for f in external_flows), Decimal(0))) if flat else None},
            'residuals': residuals, 'fee_evidence_completeness': fee_state, 'activity_type_counts': dict(counts),
            'external_flows': external_flows, 'unknown_activities': unknown, 'historical_checkpoints': checked,
            'exact_unrounded_notional_diagnostic': {'cash': str(exact_cash), 'cash_residual_usd': str(exact_cash-B.number(bundle['account']['cash'])),
                                                   'gross_fill_cashflow_usd': str(exact_gross), 'difference_from_posted_cash_usd': str(exact_cash-cash),
                                                   'classification': 'exact economic notional diagnostic; does not reflect provider USD posting precision'},
            'journal': journal, 'source_bundle_sha256': bundle_sha256, 'code_sha256': B.digest(Path(__file__).read_bytes()),
            'order_filled_quantity_residuals': order_quantity_residuals,
            'limits': ['Provider precision reply applies generally; crypto-paper per-FILL interpretation is corroborated by independent observed flat-account checkpoints.',
                       'Fee posting time can lag execution; FIFO base-fee allocation at posting time is not per-order cost attribution.',
                       'API retained-history coverage and historical observations are evidence, not a guarantee against future provider corrections.',
                       'Non-flat equity requires independent marked valuations; current broker market values are never copied into shadow equity.'],
            'profitability_verified': False, 'live_trading_authorized': False, 'orders_submitted': 0}


def archive_source(path, archive_root):
    raw = path.read_bytes(); sha = B.digest(raw)
    archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    archived = archive_root/(sha+'.json')
    try:
        fd = os.open(archived, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        if archived.read_bytes() != raw:
            raise B.Blocked('source_archive_collision')
    if archived.read_bytes() != raw:
        raise B.Blocked('source_archive_readback_mismatch')
    return {'path': str(archived.resolve()), 'sha256': sha}


def publish(report, output):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = B.canonical(report).encode(); sha = B.digest(raw); path = output/('ledger-'+sha+'.json')
    with (output/'.ledger.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            if path.read_bytes() != raw:
                raise B.Blocked('immutable_ledger_collision')
        if path.read_bytes() != raw:
            raise B.Blocked('ledger_readback_mismatch')
        pointer = {'schema': 'apex_broker_ledger_pointer/1', 'report_path': str(path.resolve()), 'report_sha256': sha,
                   'capture_ended_utc': report['capture_ended_utc'], 'account_number': B.ACCOUNT, 'mode': 'paper',
                   'independently_matched': report['independently_matched'], 'profitability_verified': False,
                   'live_trading_authorized': False, 'orders_submitted': 0}
        latest = output/'latest-ledger.json'
        if latest.exists():
            old = json.loads(latest.read_text())
            if B.timestamp(old['capture_ended_utc']) > B.timestamp(pointer['capture_ended_utc']):
                raise B.Blocked('ledger_pointer_would_rewind')
        fd, temp = tempfile.mkstemp(prefix='.ledger-pointer-', dir=output)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(B.canonical(pointer).encode()); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, latest)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return path, latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True); parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--checkpoints', type=Path); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive-sources', type=Path)
    parser.add_argument('--baseline-source', type=Path)
    parser.add_argument('--checkpoint-source', type=Path)
    args = parser.parse_args()
    try:
        bundle, baseline = json.loads(args.bundle.read_text()), json.loads(args.baseline.read_text())
        checkpoints = json.loads(args.checkpoints.read_text()) if args.checkpoints else []
        report = reconstruct(bundle, baseline, B.digest(args.bundle.read_bytes()), B.digest(args.baseline.read_bytes()), checkpoints)
        if args.archive_sources:
            refs = {key: archive_source(path, args.archive_sources) for key, path in
                    [('bundle', args.bundle), ('baseline', args.baseline), ('checkpoints', args.checkpoints)] if path}
            if args.baseline_source:
                ref = archive_source(args.baseline_source, args.archive_sources)
                if ref['sha256'] != baseline['source_sha256']:
                    raise B.Blocked('baseline_source_archive_hash_mismatch')
                refs['baseline_source'] = ref
            if args.checkpoint_source:
                ref = archive_source(args.checkpoint_source, args.archive_sources)
                if ref['sha256'] not in {row['source_sha256'] for row in checkpoints}:
                    raise B.Blocked('checkpoint_source_archive_hash_mismatch')
                refs['checkpoint_source'] = ref
            report['archival_refs'] = refs
        path, pointer = publish(report, args.output)
        print(B.canonical({'state': report['state'], 'report': str(path), 'pointer': str(pointer), 'display_summary': report['display_summary']}), end='')
        return 0 if report['independently_matched'] else 2
    except B.Blocked as error:
        print(B.canonical({'state': 'blocked', 'reason': str(error), 'profitability_verified': False, 'orders_submitted': 0}), end='')
        return 2
    except Exception:
        print(B.canonical({'state': 'blocked', 'reason': 'invalid_local_source_or_schema', 'profitability_verified': False, 'orders_submitted': 0}), end='')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
