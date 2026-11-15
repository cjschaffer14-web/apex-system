import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from unittest.mock import Mock, patch
from .connectivity.public import CoinbaseConnector, KrakenConnector
from .connectivity.interfaces import BookSnapshot
from .connectivity.pipeline import CandidatePipeline, Policy, SnapshotStateEstimator, dex_cycle_packet
from .connectivity.dex import CurveSnapshot, DexQuoteAdapter
from .connectivity.runner import PublicSnapshotStream, run
from .core import Book, Level
from .execution.interfaces import OrderRequest
from .episodes.tracker import EpisodeStore
from .dexdata.rpc import Rpc, RpcError

FIXTURE=json.loads((Path(__file__).parent/'connectivity/fixtures/books.json').read_text())
T=10_000_000_000

def books(fees=10):
    a=CoinbaseConnector(fees).normalize('BTC/USD',FIXTURE['coinbase'],T,T+1)
    b=KrakenConnector(fees).normalize('BTC/USD',FIXTURE['kraken'],T,T+1)
    return [replace(x,synthetic=True) for x in (a,b)]

def curves():
    return [CurveSnapshot(8453,'0x'+'1'*40,'A','B',1000000,2000000,997,1000,5,'hash',T,T+1,'rpc1',True),
            CurveSnapshot(8453,'0x'+'2'*40,'B','A',1000000,600000,997,1000,5,'hash',T,T+1,'rpc2',True)]

class ConnectivityTests(unittest.TestCase):
    def test_normalization(self):
        a,b=books()
        self.assertEqual(a.book.bids[0].price,D(99))
        self.assertEqual(a.book.asks[0].size,D(2)) # not multiplied by num-orders
        self.assertEqual(b.book.bids[0].price,D(103))
        self.assertIsNone(b.source_ns) # level update time isn't snapshot time
        self.assertEqual(a.sequence,42)
        self.assertEqual(a.observation().asset,'BTC/USD')
    def test_source_timestamp(self):
        data={**FIXTURE['coinbase'],'time':'1970-01-01T00:00:10Z'}
        a=CoinbaseConnector().normalize('BTC/USD',data,T,T+1)
        self.assertEqual(a.source_ns,T)
        with self.assertRaises(ValueError): replace(a,source_ns=1).fresh(T+1)
    def test_freshness(self):
        a=books()[0]
        for x,now in ((a,T+3_000_000_000),(replace(a,request_ns=T+100),T+1),(replace(a,request_ns=T-3_000_000_000),T+1)):
            with self.assertRaises(ValueError): x.fresh(now)
    def test_crossed_and_nonfinite_rejected(self):
        a=books()[0]
        for price in (D(101),D('NaN')):
            b=Book(a.economic_venue_id,'BTC/USD',[Level(price,D(1))],a.book.asks,T)
            with self.assertRaises(ValueError): replace(a,book=b).validate()
    def test_duplicate_prices_rejected(self):
        a=books()[0]
        b=replace(a.book,bids=a.book.bids+a.book.bids)
        with self.assertRaises(ValueError): replace(a,book=b).validate()
    def test_auction_and_error_rejected(self):
        with self.assertRaises(ValueError): CoinbaseConnector().normalize('BTC/USD',{**FIXTURE['coinbase'],'auction_mode':True},T,T+1)
        with self.assertRaises(ValueError): KrakenConnector().normalize('BTC/USD',{'error':['bad']},T,T+1)
    def test_redundant_endpoints(self):
        a=books()[0]; redundant=replace(a,endpoint_id='proxy',source_id='proxy:BTC/USD')
        chosen,states,_=SnapshotStateEstimator().update([a,redundant],T+2)
        self.assertEqual(len(chosen),1)
        self.assertEqual(states['BTC/USD'].shadow_price.independent_venues,1)
        self.assertEqual(CandidatePipeline().observe([a,redundant],T+2),[])
    def test_stale_rejection_and_state(self):
        fresh,states,rejected=SnapshotStateEstimator().update(books(),T+3_000_000_000)
        self.assertEqual(fresh,[]); self.assertEqual(states,{})
        self.assertEqual(len(rejected),2)
    def test_costs_and_packet(self):
        pipeline=CandidatePipeline(inventory={'coinbase_spot:USD':1000,'kraken_spot:BTC':10})
        p=pipeline.observe(books(),T+2)[0]
        # size 100 buys .999 BTC after first fee; sell at 103, second fee.
        expected=100/100*.999*103*.999-100-.1
        self.assertAlmostEqual(p['opportunity']['gross_usd'],expected)
        self.assertAlmostEqual(p['prediction']['expected_net_value_usd'],.1*expected-.9-.1)
        self.assertFalse(p['decision']['orders_authorized'])
        self.assertTrue(p['observations']['synthetic'])
        with tempfile.TemporaryDirectory() as d:
            store=EpisodeStore(str(Path(d)/'ep.sqlite')); store.save(p)
            self.assertEqual(store.packets()[0]['episode_id'],p['episode_id']); store.close()
    def test_unknown_fees_log_rejection(self):
        p=CandidatePipeline().observe(books(None),T+2)[0]
        self.assertIsNone(p['opportunity']['gross_usd'])
        self.assertIn('unknown_fees',p['decision']['reason_codes'])
    def test_insufficient_depth(self):
        p=CandidatePipeline(Policy(size_usd=10000)).observe(books(),T+2)[0]
        self.assertIn('insufficient_depth',p['decision']['reason_codes'])
    def test_outcome_preserves_prediction(self):
        pipeline=CandidatePipeline(); old=pipeline.observe(books(),T+2)[0]
        later=[replace(x,request_ns=T+500_000_000,received_ns=T+500_000_001) for x in books()]
        updated=pipeline.observe(later,T+500_000_002)[0]
        self.assertEqual(updated['episode_id'],old['episode_id'])
        self.assertEqual(updated['prediction'],old['prediction'])
        self.assertEqual(updated['realized_shadow_outcome']['status'],'later_snapshot_observation')
        self.assertFalse(updated['realized_shadow_outcome']['capture_evidence'])
    def test_censored_outcome(self):
        pipeline=CandidatePipeline(); pipeline.observe(books(),T+2)
        p=pipeline.observe([],T+3_000_000_000)[0]
        self.assertTrue(p['censoring']['right_censored'])
        self.assertIsNone(p['realized_shadow_outcome']['net_usd'])
    def test_skew_rejection(self):
        a,b=books(); b=replace(b,request_ns=T+1_500_000_000,received_ns=T+1_500_000_001)
        self.assertEqual(CandidatePipeline().observe([a,b],T+1_500_000_002),[])
    def test_no_paper_mode(self):
        a=books()[0]
        self.assertEqual(OrderRequest(a.economic_venue_id,'BTC/USD','buy',D(100)).mode,'live')
        import apex_v2.execution as execution
        self.assertFalse(hasattr(execution,'simulated'))
        from .frameworks.common import require_mode
        self.assertEqual(require_mode('live'),'live')
        with self.assertRaisesRegex(ValueError,'unknown mode'): require_mode('paper')
        self.assertFalse(hasattr(CoinbaseConnector(),'submit_order'))
    def test_rpc_no_send(self):
        rpc=Rpc(['https://example.invalid'],retries=1)
        for method in ('eth_sendRawTransaction','eth_sendTransaction','personal_sign','eth_sign'):
            with self.assertRaises(RpcError): rpc.call(method,[])
    def test_dex_exact_fee_not_double_charged(self):
        c=curves(); p=dex_cycle_packet(c,'A',1000,T+2,native_unit_usd=.01,gas_usd=.1)
        terminal=c[1].quote('B',c[0].quote('A',1000))
        self.assertEqual(p['opportunity']['terminal_native'],terminal)
        self.assertAlmostEqual(p['opportunity']['gross_usd'],terminal*.01-10-.1-.01)
        self.assertFalse(p['decision']['orders_authorized'])
    def test_dex_unknown_cost_blocks_valuation(self):
        p=dex_cycle_packet(curves(),'A',1000,T+2)
        self.assertIsNone(p['prediction']['expected_net_value_usd'])
    def test_dex_block_and_identity(self):
        a,b=curves()
        for rows in ([a,replace(b,block_hash='other')],[a,replace(a,endpoint_id='redundant')]):
            with self.assertRaises(ValueError): dex_cycle_packet(rows,'A',1000,T+2)
        with self.assertRaises(ValueError): dex_cycle_packet([a],'A',1000,T+2)
        with self.assertRaises(ValueError): a.fresh(T+11_000_000_000)
    def test_dex_adapter_pinned_block_and_reorg(self):
        a,b='0x'+'a'*40,'0x'+'b'*40
        header={'number':'0x5','timestamp':hex(T//10**9),'hash':'hash'}
        rpc=Mock(); rpc.call.side_effect=['0x2105',header,header]
        rpc.batch.return_value=['0x'+a[2:].rjust(64,'0'),'0x'+b[2:].rjust(64,'0'),'0x'+''.join(f'{x:064x}' for x in (100,200,10))]
        adapter=DexQuoteAdapter('https://unused',8453,'0x'+'1'*40,a,b,rpc=rpc)
        with patch('apex_v2.connectivity.dex.time.time_ns',return_value=T+1): result=adapter.snapshot()
        self.assertEqual(result.reserve0,100)
        self.assertTrue(all(params[1]=='0x5' for _,params in rpc.batch.call_args.args[0]))
        rpc.call.side_effect=['0x2105',header,{**header,'hash':'reorg'}]
        with self.assertRaisesRegex(ValueError,'reorg'): adapter.snapshot()
    def test_unvalued_followup_is_not_missing_data(self):
        pipeline=CandidatePipeline(); pipeline.observe(books(None),T+2)
        rows=[replace(x,request_ns=T+1_000_000_000,received_ns=T+1_000_000_001) for x in books(None)]
        p=pipeline.observe(rows,T+1_000_000_002)[0]
        self.assertEqual(p['realized_shadow_outcome']['status'],'later_snapshot_unvalued')
        self.assertEqual(p['censoring']['reason'],'unknown_fees_or_depth')
    def test_curve_integer_validation(self):
        a=curves()[0]
        with self.assertRaises(ValueError): replace(a,reserve0=1.5).fresh(T+2)
    def test_dex_probe_offline_blocked(self):
        from .connectivity.dex_runner import probe
        with tempfile.TemporaryDirectory() as d, patch('apex_v2.connectivity.dex_runner.Rpc') as cls:
            cls.return_value.call.side_effect=RpcError('fixture failure')
            result=probe(d)
            self.assertEqual(len(result['endpoints']),3)
            self.assertEqual(result['candidate_records'],0)
            self.assertFalse(result['orders_authorized'])
    def test_curve_state_estimate_raw_units(self):
        a,b=curves()
        rows,state,rejected=SnapshotStateEstimator().update_curves([a,b,replace(a,endpoint_id='redundant')],T+2)
        self.assertEqual(len(rows),2)
        self.assertIsNone(state.shadow_price)
        self.assertEqual(len(state.source_status),2)
        self.assertEqual(rejected,{})
        rows,_,rejected=SnapshotStateEstimator().update_curves([a],T+11_000_000_000)
        self.assertEqual(rows,[]); self.assertEqual(len(rejected),1)

    def test_policy_inputs(self):
        for policy in (Policy(capture_probability=2),Policy(buffer_bps=-1),Policy(size_usd=float('nan'))):
            with self.assertRaises(ValueError): CandidatePipeline(policy)
    def test_finite_runner_mock(self):
        with tempfile.TemporaryDirectory() as d, patch.object(PublicSnapshotStream,'poll',return_value=(books(),{})):
            with patch('apex_v2.connectivity.runner.time.time_ns',return_value=T+2): summary=run(1,1,d)
            self.assertEqual(summary['candidate_records'],1)
            self.assertFalse(summary['continuous_runner'])
            self.assertTrue((Path(d)/'status.json').exists())
        with self.assertRaises(ValueError): run(0,1,'unused')

if __name__=='__main__': unittest.main()
