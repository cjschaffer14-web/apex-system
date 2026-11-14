import copy
from decimal import localcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import broker_reconciliation as B
import broker_lifecycle as L
import broker_ledger as G

ROOT = Path(__file__).parent
AFTER = '2026-10-22T09:59:59Z'
BASE = '2026-10-22T11:00:00Z'
END = '2026-10-22T12:05:00Z'


def fixture():
    a = {'id': 'id-suffix', 'account_number': B.ACCOUNT, 'created_at': '2026-10-22T10:00:00Z',
         'currency': 'USD', 'status': 'ACTIVE', 'cash': '100.01', 'equity': '100.01', 'long_market_value': '0', 'short_market_value': '0'}
    activities = [{'id': 'fund', 'activity_type': 'JNLC', 'created_at': '2026-10-22T10:30:00Z', 'currency': 'USD', 'net_amount': '100'},
                  {'id': 'buy', 'activity_type': 'FILL', 'transaction_time': '2026-10-22T12:00:00Z', 'order_id': 'buy-order', 'symbol': 'BTC/USD', 'side': 'buy', 'qty': '1', 'price': '1.005'},
                  {'id': 'sell', 'activity_type': 'FILL', 'transaction_time': '2026-10-22T12:01:00Z', 'order_id': 'sell-order', 'symbol': 'BTC/USD', 'side': 'sell', 'qty': '1', 'price': '1.015'},
                  {'id': 'fee', 'activity_type': 'CFEE', 'created_at': '2026-10-22T12:02:00Z', 'currency': 'USD', 'status': 'executed', 'net_amount': '-0.01'}]
    bundle = {'schema': 'apex_broker_lifecycle_bundle/1', 'environment': 'paper', 'account_number': B.ACCOUNT, 'account': a,
              'positions': [], 'orders': [{'id': 'buy-order', 'symbol': 'BTC/USD', 'side': 'buy', 'filled_qty': '1'}, {'id': 'sell-order', 'symbol': 'BTC/USD', 'side': 'sell', 'filled_qty': '1'}],
              'activities': activities, 'coverage': {'start': AFTER, 'end': END, 'activities_complete': True, 'orders_complete': True},
              'capture_started_utc': END, 'capture_ended_utc': END}
    baseline = {'schema': 'apex_broker_opening_baseline/1', 'mode': 'paper', 'currency': 'USD', 'account_number': B.ACCOUNT,
                'asof_utc': BASE, 'cash': '100', 'equity': '100', 'positions': {}, 'account_id_suffix': 'suffix',
                'source_kind': 'historical_cloud_broker_preflight', 'source_sha256': 'a'*64}
    checkpoints = [{'account_number': B.ACCOUNT, 'asof_utc': '2026-10-22T12:03:00Z', 'cash': '100.01', 'positions': {}, 'source_sha256': 'b'*64}]
    return bundle, baseline, checkpoints


def reconstruct(bundle=None, baseline=None, checkpoints=None):
    b, a, c = fixture()
    return G.reconstruct(bundle or b, baseline or a, 'c'*64, 'd'*64, c if checkpoints is None else checkpoints)


class LedgerTests(unittest.TestCase):
    def test_history_recursively_narrows_full_order_pages(self):
        bundle, _, _ = fixture()
        class AccountTransport:
            def get(self, path):
                self_path = '/v2/account'
                if path != self_path: raise AssertionError(path)
                return bundle['account'], 'a'*64
        calls = []
        def collect(transport, after, until, clock):
            calls.append((after, until))
            if (B.timestamp(until)-B.timestamp(after)).total_seconds() > 5400:
                raise B.Blocked('orders_daily_page_limit_requires_narrower_window')
            return {'schema': 'apex_broker_lifecycle_evidence/1', 'environment': 'paper', 'account_number': B.ACCOUNT,
                    'account': bundle['account'], 'positions': [], 'orders': [], 'activities': [],
                    'coverage': {'start': after, 'end': until, 'activities_complete': True, 'orders_complete': True},
                    'capture_started_utc': END, 'capture_ended_utc': END}
        saved = []
        def save(receipt):
            saved.append(receipt); return B.digest(B.canonical(receipt).encode())
        with patch.object(L, 'collect', side_effect=collect):
            report = L.collect_history(AccountTransport(), END, save, lambda: END)
        self.assertEqual(len(calls), 3); self.assertEqual(len(saved), 2)
        self.assertTrue(report['coverage']['orders_complete'])
        self.assertEqual(report['coverage']['end'], B.timestamp(END).isoformat())

    def test_independent_cent_posting_and_external_cash_baseline(self):
        report = reconstruct()
        self.assertTrue(report['independently_matched'])
        self.assertEqual(report['reconstructed']['cash'], '100.01')
        self.assertEqual(report['reconstructed']['paper_broker_pnl_after_capital_flows_usd'], '0.01')
        self.assertEqual(report['residuals']['cash_usd'], '0.00')
        self.assertFalse(report['profitability_verified']); self.assertFalse(report['live_trading_authorized'])
        self.assertEqual([r['cash_delta_usd'] for r in report['journal']], ['-1.00', '1.02', '-0.01'])

    def test_cannot_copy_current_broker_cash_into_shadow(self):
        bundle, baseline, checks = fixture(); bundle['account']['cash'] = '777'; bundle['account']['equity'] = '777'
        report = reconstruct(bundle, baseline, checks)
        self.assertEqual(report['reconstructed']['cash'], '100.01')
        self.assertFalse(report['independently_matched'])
        self.assertEqual(report['residuals']['cash_usd'], '-676.99')

    def test_missing_coverage_unknown_journal_and_missing_orders_refuse_or_block(self):
        bundle, baseline, checks = fixture(); bundle['coverage']['activities_complete'] = False
        with self.assertRaisesRegex(B.Blocked, 'coverage_incomplete'): reconstruct(bundle, baseline, checks)
        bundle, baseline, checks = fixture(); bundle['orders'].pop()
        with self.assertRaisesRegex(B.Blocked, 'order_history_missing'): reconstruct(bundle, baseline, checks)
        bundle, baseline, checks = fixture(); bundle['activities'].append({'id': 'unknown', 'activity_type': 'JNLC', 'created_at': '2026-10-22T12:04:00Z', 'net_amount': '3'})
        report = reconstruct(bundle, baseline, checks); self.assertFalse(report['independently_matched'])
        self.assertEqual(report['unknown_activities'][0]['id'], 'unknown')

    def test_historical_baseline_verified_against_opening_funding(self):
        bundle, baseline, checks = fixture(); baseline['cash'] = '101'
        with self.assertRaisesRegex(B.Blocked, 'funding_does_not_confirm'): reconstruct(bundle, baseline, checks)
        bundle, baseline, checks = fixture(); bundle['coverage']['start'] = BASE
        with self.assertRaisesRegex(B.Blocked, 'account_creation'): reconstruct(bundle, baseline, checks)
        bundle, baseline, checks = fixture(); bundle['activities'][0]['activity_type'] = 'JNLS'
        with self.assertRaisesRegex(B.Blocked, 'security_or_unknown'): reconstruct(bundle, baseline, checks)

    def test_checkpoint_mismatch_is_not_ignored(self):
        bundle, baseline, checks = fixture(); checks[0]['cash'] = '101'
        self.assertFalse(reconstruct(bundle, baseline, checks)['independently_matched'])
        self.assertFalse(reconstruct(checkpoints=[])['independently_matched'])

    def test_order_cumulative_filled_quantity_is_independently_checked(self):
        bundle, baseline, checks = fixture(); bundle['orders'][0]['filled_qty'] = '2'
        report = reconstruct(bundle, baseline, checks)
        self.assertFalse(report['independently_matched'])
        self.assertEqual(report['order_filled_quantity_residuals']['buy-order'], '-1')

    def test_capital_deposit_is_not_profit(self):
        bundle, baseline, checks = fixture(); bundle['activities'].append({'id': 'deposit', 'activity_type': 'CSD', 'created_at': '2026-10-22T12:04:00Z', 'currency': 'USD', 'net_amount': '5'})
        bundle['account']['cash'] = bundle['account']['equity'] = '105.01'
        report = reconstruct(bundle, baseline, checks)
        self.assertEqual(report['reconstructed']['net_external_flows_after_baseline_usd'], '5')
        self.assertEqual(report['reconstructed']['paper_broker_pnl_after_capital_flows_usd'], '0.01')

    def test_float_nan_duplicate_and_negative_inventory_refuse(self):
        for key, value in [('qty', 1.0), ('price', 'NaN')]:
            bundle, baseline, checks = fixture(); bundle['activities'][1][key] = value
            with self.assertRaises(B.Blocked): reconstruct(bundle, baseline, checks)
        bundle, baseline, checks = fixture(); bundle['activities'].append(bundle['activities'][1])
        with self.assertRaisesRegex(B.Blocked, 'duplicate_activity'): reconstruct(bundle, baseline, checks)
        bundle, baseline, checks = fixture(); bundle['activities'][2]['qty'] = '2'
        with self.assertRaisesRegex(B.Blocked, 'exceeds_reconstructed'): reconstruct(bundle, baseline, checks)

    def test_low_ambient_precision_does_not_change_ledger(self):
        with localcontext() as context:
            context.prec = 2; report = reconstruct()
        self.assertEqual(report['reconstructed']['cash'], '100.01')
        self.assertTrue(report['independently_matched'])

    def test_immutable_publish_pointer_readback_and_rewind_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); report = reconstruct(); path, pointer = G.publish(report, root)
            self.assertEqual(path, G.publish(report, root)[0])
            self.assertEqual(json.loads(pointer.read_text())['report_sha256'], B.digest(path.read_bytes()))
            older = copy.deepcopy(report); older['capture_ended_utc'] = BASE
            with self.assertRaisesRegex(B.Blocked, 'rewind'): G.publish(older, root)

    def test_source_archive_preserves_original_bytes_and_refuses_collision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root/'input.json'; source.write_bytes(b'{  "source": "unchanged" }\n')
            ref = G.archive_source(source, root/'archive')
            self.assertEqual(Path(ref['path']).read_bytes(), source.read_bytes())
            self.assertEqual(ref['sha256'], B.digest(source.read_bytes()))
            Path(ref['path']).write_text('different')
            with self.assertRaisesRegex(B.Blocked, 'collision'): G.archive_source(source, root/'archive')

    def test_actual_retained_history_reconstructs_current_and_prior_flat_checkpoint(self):
        inputs = ROOT/'evidence'
        bundle_path, baseline_path = inputs/'lifecycle-20261103.json', inputs/'opening-baseline.json'
        bundle, baseline = json.loads(bundle_path.read_text()), json.loads(baseline_path.read_text())
        report = G.reconstruct(bundle, baseline, B.digest(bundle_path.read_bytes()), B.digest(baseline_path.read_bytes()), json.loads((inputs/'checkpoints.json').read_text()))
        self.assertTrue(report['independently_matched'])
        self.assertEqual(report['reconstructed']['cash'], '999968.00')
        self.assertEqual(report['reconstructed']['equity'], '999968.00')
        self.assertEqual(report['residuals']['cash_usd'], '0.00')
        self.assertTrue(all(B.number(v) == 0 for v in report['residuals']['quantity'].values()))
        self.assertEqual(report['activity_type_counts']['FILL'], 1244)
        self.assertEqual(report['activity_type_counts']['CFEE'], 1244)
        self.assertEqual(report['reconstructed']['posted_cash_fees_usd'], '16.12')
        self.assertEqual(report['exact_unrounded_notional_diagnostic']['cash_residual_usd'], '0.637055291698323484')
        self.assertTrue(report['historical_checkpoints'][0]['within_tolerance'])
        self.assertLess(len(B.canonical(report['display_summary'])), 20000)

    def test_merged_windows_refuse_gaps_and_duplicate_forks(self):
        bundle, _, _ = fixture()
        window = {'schema': 'apex_broker_lifecycle_evidence/1', 'environment': 'paper', 'account_number': B.ACCOUNT,
                  'account': bundle['account'], 'positions': [], 'activities': bundle['activities'], 'orders': bundle['orders'],
                  'coverage': bundle['coverage'], 'capture_started_utc': END, 'capture_ended_utc': END}
        merged = L.merge_windows([(window, 'a'*64), (copy.deepcopy(window), 'b'*64)])
        self.assertEqual(len(merged['activities']), 4)
        fork = copy.deepcopy(window); fork['activities'][0]['net_amount'] = '101'
        with self.assertRaisesRegex(B.Blocked, 'identity_conflict'): L.merge_windows([(window, 'a'*64), (fork, 'b'*64)])
        gap = copy.deepcopy(window); gap['coverage']['start'] = '2026-10-23T12:05:00Z'; gap['coverage']['end'] = '2026-10-23T13:00:00Z'
        with self.assertRaisesRegex(B.Blocked, 'coverage_gap'): L.merge_windows([(window, 'a'*64), (gap, 'b'*64)])


if __name__ == '__main__':
    unittest.main()
