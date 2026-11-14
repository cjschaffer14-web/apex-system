import copy
from decimal import localcontext
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import broker_reconciliation as B

START = '2026-11-03T10:00:00+00:00'
END = '2026-11-03T11:00:00+00:00'
CAPTURE = '2026-11-03T11:00:01+00:00'


def account():
    return {'account_number': B.ACCOUNT, 'status': 'ACTIVE', 'currency': 'USD', 'cash': '90', 'equity': '100', 'long_market_value': '10', 'short_market_value': '0'}


class Fake:
    def __init__(self, pages=None):
        self.calls = []
        self.accounts = [account(), account()]
        self.pages = pages or [[]]

    def get(self, path, query=None):
        self.calls.append((path, query))
        if path == '/v2/account':
            value = self.accounts.pop(0)
        elif path == '/v2/positions':
            value = [{'symbol': 'XYZ', 'qty': '2', 'market_value': '10'}]
        elif path == '/v2/account/activities':
            value = self.pages.pop(0)
        else:
            raise AssertionError(path)
        return value, B.digest(B.canonical(value).encode())


def observed(fake=None):
    return B.snapshot(fake or Fake(), START, END, lambda: CAPTURE)


def shadow(snapshot):
    return {'schema': 'apex_broker_shadow/1', 'ledger_kind': 'broker_shadow', 'venue': 'alpaca', 'mode': 'paper', 'account_number': B.ACCOUNT,
            'currency': 'USD', 'valuation_window': {'started_utc': snapshot['capture_started_utc'], 'ended_utc': snapshot['capture_ended_utc']},
            'source_sha256': 'a'*64, 'cash': '90', 'equity': '100', 'positions': {'XYZ': {'qty': '2', 'market_value': '10'}}}


class BrokerTests(unittest.TestCase):
    def test_snapshot_read_only_endpoints_and_hashes(self):
        f = Fake(); result = observed(f)
        self.assertEqual(result['state'], 'broker_snapshot_observed')
        self.assertEqual([p for p, _ in f.calls], ['/v2/account', '/v2/positions', '/v2/account/activities', '/v2/account'])
        self.assertFalse(result['profitability_verified']); self.assertEqual(result['orders_submitted'], 0)
        self.assertFalse(result['atomic_provider_snapshot']); self.assertEqual(len(result['raw_response_sha256']['positions']), 64)

    def test_wrong_account_stops_before_other_reads(self):
        f = Fake(); f.accounts[0]['account_number'] = 'WRONG'
        with self.assertRaisesRegex(B.Blocked, 'identity_mismatch'): observed(f)
        self.assertEqual(len(f.calls), 1)

    def test_currency_and_concurrent_change_block(self):
        f = Fake(); f.accounts[0]['currency'] = 'EUR'
        with self.assertRaisesRegex(B.Blocked, 'currency_mismatch'): observed(f)
        f = Fake(); f.accounts[1]['cash'] = '91'
        with self.assertRaisesRegex(B.Blocked, 'changed_during'): observed(f)

    def test_pagination_advances_and_duplicate_refuses(self):
        page = [{'id': str(i), 'activity_type': 'FILL', 'price': '1'} for i in range(100)]
        f = Fake([page, [{'id': 'last', 'activity_type': 'CFEE', 'net_amount': '-1'}]])
        result = observed(f)
        self.assertEqual(len(result['activities']), 101)
        self.assertEqual(f.calls[3][1]['page_token'], '99')
        with self.assertRaisesRegex(B.Blocked, 'duplicate_or_cycle'): observed(Fake([page, [page[0]]]))

    def test_endpoint_allowlist_has_no_order_route(self):
        transport = B.PaperReadOnly(('sentinel-key', 'sentinel-secret'))
        with patch.object(B, 'open_read') as op:
            with self.assertRaisesRegex(B.Blocked, 'allowlisted'): transport.get('/v2/orders')
            op.assert_not_called()

    def test_network_error_and_redirect_do_not_expose_secrets(self):
        with patch.object(B, 'open_read', side_effect=ValueError('sentinel-secret')):
            with self.assertRaises(B.Blocked) as error: B.PaperReadOnly(('k', 's')).get('/v2/account')
        self.assertEqual(str(error.exception), 'broker_read_unavailable')
        with self.assertRaisesRegex(B.Blocked, 'redirect_refused'):
            B.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.invalid')

    def test_matched_nav_and_position_quantity_gate(self):
        result = observed(); ledger = shadow(result)
        self.assertEqual(B.reconcile(result, ledger)['state'], 'matched_within_tolerance')
        ledger['positions']['XYZ']['qty'] = '2.000001'
        self.assertEqual(B.reconcile(result, ledger)['state'], 'blocked_balance_or_position_mismatch')

    def test_virtual_book_wrong_time_and_scope_refuse(self):
        result = observed()
        with self.assertRaisesRegex(B.Blocked, 'virtual_books_refused'): B.reconcile(result, {'ledger_kind': 'quote_observed_virtual_v1'})
        for field, value in [('account_number', 'OTHER'), ('currency', 'USDT'), ('valuation_window', {})]:
            ledger = shadow(result); ledger[field] = value
            with self.assertRaises(B.Blocked): B.reconcile(result, ledger)

    def test_nav_equity_alone_cannot_pass_bad_cash_or_positions(self):
        result = observed(); ledger = shadow(result); ledger['cash'] = '89'
        self.assertEqual(B.reconcile(result, ledger)['state'], 'blocked_balance_or_position_mismatch')
        ledger = shadow(result); ledger['positions'] = {}
        with self.assertRaisesRegex(B.Blocked, 'position_set'): B.reconcile(result, ledger)

    def test_external_deposit_is_not_profit_and_withdrawal_sign(self):
        prev = observed(); prev['capture_started_utc'] = START; prev['capture_ended_utc'] = START
        current = observed(); current['capture_started_utc'] = END; current['capture_ended_utc'] = END; current['account']['equity'] = '112'
        flows = {'schema': 'apex_external_flows/1', 'account_number': B.ACCOUNT, 'currency': 'USD', 'after': START, 'until': END,
                 'complete': True, 'source_sha256': 'b'*64,
                 'flows': [{'id': 'deposit', 'at_utc': END, 'kind': 'deposit', 'amount_usd': '15'},
                           {'id': 'withdraw', 'at_utc': END, 'kind': 'withdrawal', 'amount_usd': '5'}]}
        report = B.flow_adjusted_pnl(prev, current, flows)
        self.assertEqual(report['net_external_flows_usd'], '10'); self.assertEqual(report['broker_paper_pnl_usd'], '2')
        self.assertIsNone(report['time_weighted_return']); self.assertFalse(report['profitability_verified'])
        flows['complete'] = False
        with self.assertRaisesRegex(B.Blocked, 'complete_external'): B.flow_adjusted_pnl(prev, current, flows)

    def test_receipt_exact_byte_idempotency(self):
        with tempfile.TemporaryDirectory() as td:
            receipt = observed(); path = B.publish(receipt, Path(td)); self.assertEqual(path, B.publish(receipt, Path(td)))
            self.assertEqual(json.loads(path.read_text()), receipt)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_offline_cli_reconciles_without_credential_access(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); result = observed()
            (root/'snapshot.json').write_text(B.canonical(result))
            (root/'shadow.json').write_text(B.canonical(shadow(result)))
            run = subprocess.run([sys.executable, str(Path(B.__file__)), '--snapshot-input', str(root/'snapshot.json'),
                                  '--shadow', str(root/'shadow.json'), '--output', str(root/'receipts')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            receipt = json.loads(Path(json.loads(run.stdout)['receipt']).read_text())
            self.assertEqual(receipt['auth_mode'], 'offline_saved_evidence')
            self.assertEqual(receipt['nav_reconciliation'], 'matched_within_tolerance')
            self.assertFalse(receipt['profitability_verified'])

    def test_shadow_source_hash_must_be_hex(self):
        result = observed(); ledger = shadow(result); ledger['source_sha256'] = 'g'*64
        with self.assertRaisesRegex(B.Blocked, 'source_hash'): B.reconcile(result, ledger)

    def test_offline_cli_shadow_mismatch_preserves_snapshot_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); result = observed(); ledger = shadow(result); ledger['cash'] = '89'
            (root/'snapshot.json').write_text(B.canonical(result))
            (root/'shadow.json').write_text(B.canonical(ledger))
            run = subprocess.run([sys.executable, str(Path(B.__file__)), '--snapshot-input', str(root/'snapshot.json'),
                                  '--shadow', str(root/'shadow.json'), '--output', str(root/'receipts')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stderr)
            acknowledgement = json.loads(run.stdout)
            self.assertEqual(acknowledgement['nav_reconciliation'], 'blocked_balance_or_position_mismatch')
            receipt = json.loads(Path(acknowledgement['receipt']).read_text())
            self.assertEqual(receipt['state'], 'broker_snapshot_observed')
            self.assertEqual(receipt['account'], result['account'])
            self.assertEqual(receipt['reconciliation']['residuals']['cash'], '-1')
            self.assertEqual(receipt['reconciliation']['residuals']['shadow_cash_plus_positions'], '-1')
            self.assertFalse(receipt['profitability_verified'])

    def test_financial_results_ignore_low_ambient_decimal_precision(self):
        result = observed(); ledger = shadow(result)
        ledger['cash'] = '90.009'; ledger['equity'] = '100.009'
        with localcontext() as context:
            context.prec = 2
            reconciled = B.reconcile(result, ledger)
        self.assertEqual(reconciled['residuals']['cash'], '0.009')
        self.assertEqual(reconciled['state'], 'matched_within_tolerance')
        prev = observed(); prev['capture_started_utc'] = START; prev['capture_ended_utc'] = START
        current = observed(); current['capture_started_utc'] = END; current['capture_ended_utc'] = END; current['account']['equity'] = '100.123456789'
        flows = {'schema': 'apex_external_flows/1', 'account_number': B.ACCOUNT, 'currency': 'USD', 'after': START, 'until': END,
                 'complete': True, 'source_sha256': 'b'*64, 'flows': []}
        with localcontext() as context:
            context.prec = 2
            pnl = B.flow_adjusted_pnl(prev, current, flows)
        self.assertEqual(pnl['broker_paper_pnl_usd'], '0.123456789')

    def test_imported_float_nan_and_nonfinite_activity_refuse(self):
        result = observed(); result['activities'] = [{'qty': 0.1}]
        with self.assertRaisesRegex(B.Blocked, 'decimal_string'): B.reconcile(result, shadow(result))
        result['activities'] = [{'qty': float('nan')}]
        with self.assertRaisesRegex(B.Blocked, 'decimal_string'): B.validate_snapshot(result)
        with self.assertRaises(ValueError): B.canonical({'value': float('nan')})
        with self.assertRaisesRegex(B.Blocked, 'nonfinite'): observed(Fake([[{'id': '1', 'qty': 'NaN'}]]))

    def test_unattended_rejects_user_adc_and_private_key(self):
        class External: pass
        class Metadata: pass
        auth = types.ModuleType('google.auth'); auth.default = lambda **kw: (object(), None)
        google = types.ModuleType('google'); google.auth = auth
        external = types.ModuleType('google.auth.external_account'); external.Credentials = External
        metadata = types.ModuleType('google.auth.compute_engine.credentials'); metadata.Credentials = Metadata
        requests = types.ModuleType('google.auth.transport.requests'); requests.Request = object
        modules = {'google': google, 'google.auth': auth, 'google.auth.external_account': external,
                   'google.auth.compute_engine.credentials': metadata, 'google.auth.transport.requests': requests}
        with patch.dict(sys.modules, modules), patch.object(B, 'open_read') as op:
            with self.assertRaisesRegex(B.Blocked, 'requires_workload_identity'): B.workload_keys()
            op.assert_not_called()


if __name__ == '__main__':
    unittest.main()
