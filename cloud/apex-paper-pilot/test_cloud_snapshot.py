"""Existing Cloud Run app extension; fake broker/transport, no cloud requests."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from urllib.parse import urlencode

import broker_reconciliation as B

SOURCE = Path(__file__).parent/'cloud-pilot/app.py'
spec = importlib.util.spec_from_file_location('cloud_snapshot_app', SOURCE)
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
AFTER = '2026-11-03T10:00:00Z'
UNTIL = '2026-11-03T11:00:00Z'


def account():
    return {'id': 'expected-uuid', 'account_number': B.ACCOUNT, 'status': 'ACTIVE', 'currency': 'USD',
            'created_at': '2026-10-22T19:47:00Z',
            'cash': '90', 'equity': '100', 'long_market_value': '10', 'short_market_value': '0'}


class Broker:
    def __init__(self):
        self.value, self.calls = account(), []
    def account(self):
        self.calls.append('account')
        return copy.deepcopy(self.value)


class Reads:
    def __init__(self):
        self.accounts = [account(), account()]
        self.calls = []
    def get(self, path, query=None):
        self.calls.append((path, query))
        if path == '/v2/account':
            value = self.accounts.pop(0)
        elif path == '/v2/positions':
            value = [{'symbol': 'XYZ', 'qty': '2', 'market_value': '10'}]
        elif path == '/v2/account/activities':
            value = [{'id': 'fee', 'activity_type': 'CFEE', 'net_amount': '-0.05'}]
        else:
            raise AssertionError('Unexpected endpoint')
        return value, B.digest(B.canonical(value).encode())


class NoStorageWrites:
    durable = True
    def __getattr__(self, name):
        raise AssertionError('Storage method accessed: ' + name)


def fixture():
    broker, reads, factories = Broker(), Reads(), []
    def factory():
        factories.append(True)
        return reads
    pilot = C.Pilot(env={'APEX_SOURCE_SHA': 'base-release', 'APEX_EXPECTED_ACCOUNT_ID': 'expected-uuid',
                         'APEX_EXISTING_ACCOUNT_ID': 'excluded-uuid', 'APEX_PAPER_KEY': 'sentinel-key',
                         'APEX_PAPER_SECRET': 'sentinel-secret'}, broker=broker, store=NoStorageWrites(),
                    report_store=NoStorageWrites(), snapshot_transport_factory=factory)
    return pilot, broker, reads, factories


def route(pilot, query=None, path='/api/broker-snapshot', post=False):
    handler = object.__new__(C.Handler)
    handler.path = path + ('?' + query if query is not None else '')
    handler.pilot = pilot
    result = []
    handler.send = lambda status, body, mime='application/json': result.append((status, body))
    (C.Handler.do_POST if post else C.Handler.do_GET)(handler)
    return result[0]


class CloudSnapshotTests(unittest.TestCase):
    def test_lifecycle_route_returns_full_records_with_existing_identity(self):
        pilot, broker, reads, factories = fixture()
        class LifecycleReads(Reads):
            def get(self, path, query=None):
                if path == '/v2/orders':
                    self.calls.append((path, query))
                    rows = [{'id': 'filled-order', 'status': 'filled', 'filled_qty': '1', 'filled_avg_price': '10'}]
                    return rows, B.digest(B.canonical(rows).encode())
                return super().get(path, query)
        life = LifecycleReads(); pilot.lifecycle_transport_factory = lambda: life
        status, receipt = route(pilot, urlencode({'after': AFTER, 'until': UNTIL}), path='/api/broker-lifecycle')
        self.assertEqual(status, 200)
        self.assertEqual(receipt['schema'], 'apex_broker_lifecycle_evidence/1')
        self.assertEqual(receipt['account']['account_number'], B.ACCOUNT)
        self.assertEqual(receipt['orders'][0]['id'], 'filled-order')
        self.assertEqual(receipt['broker_lifecycle_version'], '1')
        self.assertEqual([p for p, _ in life.calls], ['/v2/account', '/v2/positions', '/v2/account/activities', '/v2/orders', '/v2/account'])
        self.assertEqual(life.calls[3][1]['status'], 'all')
        self.assertEqual(receipt['orders_submitted'], 0); self.assertFalse(receipt['profitability_verified'])
        self.assertNotIn('sentinel-secret', B.canonical(receipt))

    def test_protected_get_returns_full_snapshot_without_storage_or_trades(self):
        pilot, broker, reads, factories = fixture()
        status, receipt = route(pilot, urlencode({'after': AFTER, 'until': UNTIL}))
        self.assertEqual(status, 200)
        self.assertEqual(receipt['account']['account_number'], B.ACCOUNT)
        self.assertEqual(receipt['positions']['XYZ']['qty'], '2')
        self.assertEqual(receipt['activities'][0]['net_amount'], '-0.05')
        self.assertEqual(broker.calls, ['account']); self.assertEqual(len(factories), 1)
        self.assertEqual([p for p, _ in reads.calls], ['/v2/account', '/v2/positions', '/v2/account/activities', '/v2/account'])
        self.assertEqual(receipt['broker_snapshot_version'], '1')
        self.assertEqual(receipt['cloud_source_release'], 'base-release')
        self.assertEqual(receipt['collector_source_sha256'], B.digest(Path(B.__file__).read_bytes()))
        self.assertEqual(receipt['cloud_extension_source_sha256'], B.digest(SOURCE.read_bytes()))
        self.assertFalse(receipt['profitability_verified']); self.assertEqual(receipt['orders_submitted'], 0)
        self.assertNotIn('sentinel-key', B.canonical(receipt)); self.assertNotIn('sentinel-secret', B.canonical(receipt))

    def test_invalid_queries_400_before_broker_access(self):
        invalid = [None, '', 'after=x', 'after=x&until=y', 'after=x&until=y&extra=z',
                   'after=x&after=y&until=z', 'after=&until=z',
                   urlencode({'after': UNTIL, 'until': AFTER}),
                   urlencode({'after': '2020-01-01T00:00:00Z', 'until': UNTIL}),
                   urlencode({'after': '2099-01-01T00:00:00Z', 'until': '2099-01-01T01:00:00Z'}),
                   'after=' + 'x'*1025 + '&until=z']
        for query in invalid:
            with self.subTest(query=query):
                pilot, broker, reads, factories = fixture()
                status, body = route(pilot, query)
                self.assertEqual(status, 400); self.assertEqual(broker.calls, [])
                self.assertEqual(reads.calls, []); self.assertEqual(factories, [])
                self.assertNotIn('sentinel-secret', B.canonical(body))
                self.assertEqual(route(pilot, query, path='/api/broker-lifecycle')[0], 400)

    def test_original_uuid_gate_precedes_collector(self):
        pilot, broker, reads, factories = fixture(); broker.value['id'] = 'wrong-uuid'
        status, body = route(pilot, urlencode({'after': AFTER, 'until': UNTIL}))
        self.assertEqual(status, 403); self.assertEqual(body, {'error': 'account_identity_mismatch'})
        self.assertEqual(reads.calls, []); self.assertEqual(factories, [])

    def test_collector_checks_account_number_independently(self):
        pilot, broker, reads, factories = fixture(); reads.accounts[0]['account_number'] = 'WRONG'
        status, body = route(pilot, urlencode({'after': AFTER, 'until': UNTIL}))
        self.assertEqual(status, 424); self.assertEqual(body, {'error': 'paper_account_identity_mismatch'})
        self.assertEqual([p for p, _ in reads.calls], ['/v2/account'])

    def test_all_unexpected_collector_failures_are_sanitized(self):
        pilot, broker, reads, factories = fixture()
        def bad_factory(): raise ValueError('sentinel-secret')
        pilot.snapshot_transport_factory = bad_factory
        status, body = route(pilot, urlencode({'after': AFTER, 'until': UNTIL}))
        self.assertEqual(status, 503); self.assertEqual(body, {'error': 'dependency_unavailable'})

    def test_existing_health_and_status_unchanged_and_post_route_refused(self):
        pilot, broker, reads, factories = fixture()
        self.assertEqual(route(pilot, path='/api/health')[1], {'service': 'apex-paper-pilot', 'status': 'up', 'release': 'base-release'})
        self.assertEqual(route(pilot, path='/api/status')[1]['cash'], '90')
        self.assertEqual(route(pilot, post=True), (404, {'error': 'not_found'}))
        self.assertEqual(reads.calls, []); self.assertEqual(factories, [])

    def test_existing_write_handler_and_submission_ast_unchanged(self):
        tree = ast.parse(SOURCE.read_text())
        # Explicit field serialization avoids ast.dump's changed empty-list
        # presentation between the host Python3.15 and deployed Python3.12.
        def normalize(node):
            if isinstance(node, ast.AST):
                return {'node': type(node).__name__, 'fields': {k: normalize(v) for k, v in ast.iter_fields(node)}}
            if isinstance(node, list):
                return [normalize(v) for v in node]
            return node
        expected = {('Handler', 'do_POST'): '3237a024ce028458efaff2ea79ad58b1063a88868894d0bbaccf16b17a09900b',
                    ('Pilot', 'submit'): '2ecdab81589a184a54bcbe50c2513b0762f5c104106b19b21096d65d33d26249'}
        for (cls, name), value in expected.items():
            method = next(m for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls
                          for m in n.body if isinstance(m, ast.FunctionDef) and m.name == name)
            encoded = json.dumps(normalize(method), sort_keys=True, separators=(',', ':')).encode()
            self.assertEqual(hashlib.sha256(encoded).hexdigest(), value)


if __name__ == '__main__':
    unittest.main()
