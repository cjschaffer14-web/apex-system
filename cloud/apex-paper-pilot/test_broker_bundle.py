import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import broker_bundle as A
import broker_reconciliation as B


def window(start='2026-11-03T00:00:00Z', end='2026-11-03T01:00:00Z', capture='2026-11-03T01:00:01Z'):
    return {'schema': 'apex_broker_lifecycle_evidence/1', 'environment': 'paper', 'account_number': B.ACCOUNT,
            'account': {'id': 'account-uuid', 'account_number': B.ACCOUNT, 'created_at': '2026-11-03T00:00:00Z',
                        'currency': 'USD', 'status': 'ACTIVE', 'cash': '100', 'equity': '100', 'long_market_value': '0', 'short_market_value': '0'},
            'positions': [], 'orders': [{'id': 'order'}], 'activities': [{'id': 'activity', 'activity_type': 'JNLC', 'net_amount': '100'}],
            'coverage': {'start': start, 'end': end, 'activities_complete': True, 'orders_complete': True},
            'capture_started_utc': capture, 'capture_ended_utc': capture}


def raw(value):
    return B.canonical(value).encode()


class BundleTests(unittest.TestCase):
    def test_deterministic_overlap_dedup_and_exact_byte_provenance(self):
        first = window()
        second = window('2026-11-03T00:59:59Z', '2026-11-03T02:00:00Z', '2026-11-03T02:00:01Z')
        a, b = raw(first), raw(second)
        result = A.assemble([a, b, a])
        self.assertEqual(result, A.assemble([b, a]))
        self.assertEqual(len(result['activities']), 1); self.assertEqual(len(result['orders']), 1)
        self.assertEqual(result['provenance']['window_count'], 2)
        self.assertEqual(result['provenance']['window_receipt_sha256'], sorted([B.digest(a), B.digest(b)]))
        self.assertEqual(result['capture_ended_utc'], second['capture_ended_utc'])

    def test_coverage_gap_and_missing_creation_prefix_refuse(self):
        first = raw(window())
        gap = raw(window('2026-11-03T01:00:01Z', '2026-11-03T02:00:00Z', '2026-11-03T02:00:01Z'))
        with self.assertRaisesRegex(B.Blocked, 'coverage_gap'): A.assemble([first, gap])
        late = window(); late['coverage']['start'] = '2026-11-03T00:00:01Z'
        with self.assertRaisesRegex(B.Blocked, 'account_creation'): A.assemble([raw(late)])

    def test_conflicting_activity_order_and_account_creation_refuse(self):
        first = window()
        for field in ('activities', 'orders'):
            fork = copy.deepcopy(first); fork[field][0]['changed'] = 'value'
            with self.assertRaisesRegex(B.Blocked, 'identity_conflict'): A.assemble([raw(first), raw(fork)])
        fork = copy.deepcopy(first); fork['account']['created_at'] = '2026-11-02T00:00:00Z'
        with self.assertRaisesRegex(B.Blocked, 'scope_or_creation'): A.assemble([raw(first), raw(fork)])

    def test_incomplete_wrong_scope_and_stale_final_observation_refuse(self):
        value = window(); value['coverage']['orders_complete'] = False
        with self.assertRaisesRegex(B.Blocked, 'incomplete_window'): A.assemble([raw(value)])
        value = window(); value['account']['account_number'] = 'wrong'
        with self.assertRaisesRegex(B.Blocked, 'identity_mismatch'): A.assemble([raw(value)])
        value = window(capture='2026-11-03T02:00:00Z')
        with self.assertRaisesRegex(B.Blocked, 'outside_replay'): A.assemble([raw(value)])

    def test_same_time_conflicting_final_balances_refuse(self):
        first = window(); second = copy.deepcopy(first); second['account']['cash'] = '101'
        with self.assertRaisesRegex(B.Blocked, 'ambiguous_same_time'): A.assemble([raw(first), raw(second)])

    def test_cli_ignores_other_schemas_and_publishes_readback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); inputs = root/'windows'; inputs.mkdir()
            (inputs/'one.json').write_bytes(raw(window()))
            (inputs/'index.json').write_text('{"kind":"collection_index"}')
            run = subprocess.run([sys.executable, str(Path(A.__file__)), '--windows-dir', str(inputs), '--output', str(root/'output')], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            ack = json.loads(run.stdout); self.assertEqual(ack['ignored_other_schema_files'], 1)
            path = Path(ack['bundle']); self.assertEqual(B.digest(path.read_bytes()), ack['bundle_sha256'])
            self.assertEqual(json.loads(path.read_text())['schema'], 'apex_broker_lifecycle_bundle/1')


if __name__ == '__main__':
    unittest.main()
