"""Accounting invariants and fail-closed Layer 7 contract checks."""
import unittest, math, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataclasses import replace
import numpy as np
from apex_v10.interfaces import RiskAllocation, ExecutionKind
from apex_v10.stage2_layer7 import (FundingAccrual, FundingPositionClose, FundingPositionOpen, Settlement, FundingLedger,deribit_hourly_sample,
                                    VenueSchedule,Quote,Account,ExecutionSimulator,timestamped_returns)
from apex_v10.stage2_statistics import dsr,expected_max_sharpe,cscv

def alloc(w,ts=100): return RiskAllocation(ts,'fixture',{'ETH':w},2.,3.,.5,'independent_fractional_kelly',1.)
def schedule(**kw):
    d=dict(schedule_id='research-fixture',venue='fixture',symbol='ETH-USD',valid_from=0,valid_until=10000,
           known_at_ts=0,maker_bps=-1.,taker_bps=40.,initial_margin=.5,maintenance_margin=.1,
           liquidation_buffer=.05,liquidation_bps=100.,source='synthetic test fixture',research_only=True)
    d.update(kw);return VenueSchedule(**d)
def quote(**kw):
    d=dict(symbol='ETH-USD',ts=100,known_at_ts=100,bid=99.,ask=101.,depth_quote=100000.,max_participation=1.,impact_bps=0.,mark=100.)
    d.update(kw);return Quote(**d)

class FundingTests(unittest.TestCase):
    def accrual(self,**kw):
        d=dict(event_id='a',start_ts=25200,end_ts=28800,known_at_ts=28800,symbol='BTC-PERPETUAL',currency='BTC',payment=.01,provenance_id='fixture')
        d.update(kw);return FundingAccrual(**d)
    def test_accrual_then_settlement_conserves_equity(self):
        l=FundingLedger('BTC',1.);l.apply(self.accrual(),28800)
        self.assertAlmostEqual(l.cash,1.); self.assertAlmostEqual(l.equity,.99)
        l.apply(Settlement('s',28800,28800,'BTC','fixture'),28800)
        self.assertAlmostEqual(l.cash,.99);self.assertEqual(l.pending,0.);self.assertAlmostEqual(l.equity,.99)
    def test_short_credit(self):
        l=FundingLedger('BTC');l.apply(self.accrual(payment=-.01),28800);self.assertAlmostEqual(l.equity,.01)
    def test_future_event_refused(self):
        with self.assertRaises(ValueError): FundingLedger('BTC').apply(self.accrual(),28799)
    def test_duplicate_refused(self):
        l=FundingLedger('BTC');a=self.accrual();l.apply(a,28800)
        with self.assertRaises(ValueError):l.apply(a,28800)
    def test_currency_refused(self):
        with self.assertRaises(ValueError):FundingLedger('ETH').apply(self.accrual(),28800)
    def test_settlement_boundary_crossing_refused(self):
        with self.assertRaises(ValueError):FundingLedger('BTC').apply(self.accrual(end_ts=29000,known_at_ts=29000),29000)
    def test_gap_refused(self):
        l=FundingLedger('BTC');l.apply(self.accrual(),28800)
        with self.assertRaises(ValueError):l.apply(self.accrual(event_id='b',start_ts=28900,end_ts=32400,known_at_ts=32400),32400)
    def test_wrong_settlement_time(self):
        with self.assertRaises(ValueError):Settlement('s',30000,30000,'BTC','fixture')
    def test_missing_coverage_at_settlement(self):
        l=FundingLedger('BTC');l.apply(self.accrual(start_ts=21600,end_ts=25200,known_at_ts=25200),25200)
        with self.assertRaises(ValueError):l.apply(Settlement('s',28800,28800,'BTC','fixture'),28800)
    def test_hourly_sample_fails_closed_and_no_eightfold_division(self):
        kw=dict(end_ts=28800,known_at_ts=28800,symbol='BTC-PERPETUAL',rate_1h=.0001,index_price=10000.,signed_usd_position=10000.,provenance_id='fixture')
        with self.assertRaises(ValueError):deribit_hourly_sample(**kw)
        a=deribit_hourly_sample(**kw,allow_approximate=True)
        self.assertAlmostEqual(a.payment,.0001);self.assertTrue(a.approximate)
        with self.assertRaises(ValueError):FundingLedger('BTC').apply(a,28800)
    def test_nan_refused(self):
        with self.assertRaises(ValueError):self.accrual(payment=math.nan)
    def test_explicit_close_removes_settlement_coverage_requirement(self):
        l=FundingLedger('BTC');l.apply(self.accrual(start_ts=21600,end_ts=25200,known_at_ts=25200),25200)
        l.apply(FundingPositionClose('c',25200,25200,'BTC-PERPETUAL','BTC','fixture'),25200)
        l.apply(Settlement('s',28800,28800,'BTC','fixture'),28800)
        with self.assertRaises(ValueError): l.apply(self.accrual(event_id='later',start_ts=25200),28800)
    def test_explicit_reopen_starts_later_funding_session(self):
        l=FundingLedger('BTC')
        l.apply(self.accrual(start_ts=21600,end_ts=25200,known_at_ts=25200),25200)
        l.apply(FundingPositionClose('c',25200,25200,'BTC-PERPETUAL','BTC','fixture'),25200)
        l.apply(Settlement('s',28800,28800,'BTC','fixture'),28800)
        l.apply(FundingPositionOpen('o',30000,30000,'BTC-PERPETUAL','BTC','fixture'),30000)
        l.apply(self.accrual(event_id='b',start_ts=30000,end_ts=32400,known_at_ts=32400),32400)
        self.assertEqual(l.ends['BTC-PERPETUAL'],32400)
    def test_reopen_requires_closed_symbol_and_settled_session(self):
        l=FundingLedger('BTC')
        with self.assertRaises(ValueError):
            l.apply(FundingPositionOpen('o',100,100,'BTC-PERPETUAL','BTC','fixture'),100)
        l.apply(self.accrual(start_ts=21600,end_ts=25200,known_at_ts=25200),25200)
        l.apply(FundingPositionClose('c',25200,25200,'BTC-PERPETUAL','BTC','fixture'),25200)
        with self.assertRaises(ValueError):
            l.apply(FundingPositionOpen('o2',26000,26000,'BTC-PERPETUAL','BTC','fixture'),26000)
    def test_reopen_anchors_coverage_at_open_timestamp(self):
        l=FundingLedger('BTC')
        l.apply(self.accrual(start_ts=21600,end_ts=25200,known_at_ts=25200),25200)
        l.apply(FundingPositionClose('c',25200,25200,'BTC-PERPETUAL','BTC','fixture'),25200)
        l.apply(Settlement('s',28800,28800,'BTC','fixture'),28800)
        l.apply(FundingPositionOpen('o',30000,30000,'BTC-PERPETUAL','BTC','fixture'),30000)
        with self.assertRaises(ValueError):
            l.apply(self.accrual(event_id='flat-charge',start_ts=28800,end_ts=32400,known_at_ts=32400),32400)
    def test_zero_net_close_still_requires_recorded_settlement(self):
        l=FundingLedger('BTC')
        l.apply(self.accrual(start_ts=21600,end_ts=25200,known_at_ts=25200,payment=0.),25200)
        l.apply(FundingPositionClose('c',25200,25200,'BTC-PERPETUAL','BTC','fixture'),25200)
        with self.assertRaises(ValueError):
            l.apply(FundingPositionOpen('o',26000,26000,'BTC-PERPETUAL','BTC','fixture'),26000)
    def test_other_symbol_pending_does_not_block_reopen_after_settlement(self):
        l=FundingLedger('BTC')
        l.apply(self.accrual(start_ts=21600,end_ts=25200,known_at_ts=25200),25200)
        l.apply(FundingPositionClose('c',25200,25200,'BTC-PERPETUAL','BTC','fixture'),25200)
        l.apply(Settlement('s',28800,28800,'BTC','fixture'),28800)
        l.apply(self.accrual(event_id='other',start_ts=28800,end_ts=30000,known_at_ts=30000,
                             symbol='BTC-OTHER',payment=.02),30000)
        l.apply(FundingPositionOpen('o',30000,30000,'BTC-PERPETUAL','BTC','fixture'),30000)
        self.assertEqual(l.ends['BTC-PERPETUAL'],30000)

class ExecutionTests(unittest.TestCase):
    def sim(self, **kw): return ExecutionSimulator(schedule(),max_quote_age_s=kw.pop('max_quote_age_s',60),asset_to_symbol=kw.pop('asset_to_symbol',{'ETH':'ETH-USD'}),**kw)
    def test_timestamped_adapter_refuses_missing_or_future(self):
        with self.assertRaises(KeyError):timestamped_returns(('ETH',),[{'values':(.1,)}],60,100)
        with self.assertRaises(ValueError):timestamped_returns(('ETH',),[{'values':(.1,),'known_at_ts':101}],60,100)
    def test_allocator_to_execution_contract(self):
        from apex_v10.risk.allocator import LedoitWolfKellyAllocator
        from apex_v10.interfaces import ExpertForecast,StrategyMixture
        ts=6000
        rows=[{'known_at_ts':60*(i+1),'values':((.01 if i%2 else -.01),)} for i in range(80)]
        # Synthetic integration fixture; production must supply actual known_at timestamps.
        window=timestamped_returns(('ETH',),rows,60,ts)
        f=ExpertForecast('test','ETH',ts,1,60,.0001,None,1.,1.)
        mixture=StrategyMixture(ts,'test','test',{f.key:1.},(f,))
        allocation=LedoitWolfKellyAllocator().allocate(mixture,window,('ETH',))
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(allocation,'ETH',Account(1000.,0.),quote(ts=ts,known_at_ts=ts),ts=ts)
        self.assertEqual(r.event.kind,ExecutionKind.FILL)
    def test_delta_and_spread_and_fee(self):
        s=self.sim();r=s.rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(),ts=100)
        self.assertEqual(r.event.quantity,10.);self.assertEqual(r.event.price,101.)
        self.assertAlmostEqual(r.event.fee_paid,4.04);self.assertAlmostEqual(r.account.cash,995.96)
        self.assertEqual(r.account.entry_price,101.)
    def test_configured_legacy_tiers(self):
        for bps in (25.,40.,85.):
            r=ExecutionSimulator(schedule(taker_bps=bps),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(),ts=100)
            self.assertAlmostEqual(r.event.fee_paid,1010*bps/10000)
    def test_existing_position_uses_delta(self):
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,5.,100.),quote(),ts=100)
        self.assertEqual(r.requested_quantity,5.)
    def test_partial_depth(self):
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(depth_quote=200.),ts=100)
        self.assertEqual(r.event.quantity,2.);self.assertEqual(r.unfilled_quantity,8.)
    def test_impact_curve(self):
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(impact_bps=100.,depth_quote=1000.),ts=100)
        self.assertAlmostEqual(r.event.price,102.01)
    def test_passive_touch_does_not_fill(self):
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(),ts=100,passive_limit=99.)
        self.assertEqual(r.event.kind,ExecutionKind.UNFILLED);self.assertEqual(r.event.fee_paid,0.)
    def test_maker_rebate_requires_evidence(self):
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(),ts=100,passive_limit=99.,confirmed_maker_quantity=2.)
        self.assertAlmostEqual(r.event.rebate_received,.0198);self.assertEqual(r.event.quantity,2.)
    def test_crossing_postonly_refused(self):
        with self.assertRaises(ValueError):ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(),ts=100,passive_limit=101.)
    def test_margin_rejection_is_atomic(self):
        a=Account(1000.,0.);r=ExecutionSimulator(schedule(initial_margin=.9),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(2.),'ETH',a,quote(),ts=100)
        self.assertEqual(r.status,'margin_rejected');self.assertEqual(r.account,a)
    def test_future_quote_and_schedule_refused(self):
        for s,q in [(schedule(known_at_ts=101),quote()),(schedule(),quote(known_at_ts=101))]:
            with self.assertRaises(ValueError):ExecutionSimulator(s,max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),q,ts=100)
    def test_quote_symbol_mismatch_refused(self):
        with self.assertRaises(ValueError):
            self.sim().rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(symbol='BTC-PERPETUAL'),ts=100)
        with self.assertRaises(ValueError):
            self.sim(asset_to_symbol={'ETH':'BTC-PERPETUAL'}).rebalance(alloc(1.),'ETH',Account(1000.,0.),quote(),ts=100)
    def test_stale_quote_refused_in_rebalance_and_liquidation(self):
        s=self.sim(max_quote_age_s=10); q=quote(ts=89,known_at_ts=89)
        with self.assertRaises(ValueError): s.rebalance(alloc(1.),'ETH',Account(1000.,0.),q,ts=100)
        with self.assertRaises(ValueError): s.liquidation_required(Account(100.,10.,100.),q,100)
    def test_spot_no_borrow(self):
        a=Account(1000.,0.);r=ExecutionSimulator(schedule(),'spot',max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(1.),'ETH',a,quote(),ts=100)
        self.assertEqual(r.status,'margin_rejected');self.assertEqual(r.account,a)
    def test_close_realizes_pnl(self):
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(0.),'ETH',Account(1000.,10.,90.),quote(),ts=100)
        self.assertEqual(r.account.position,0.);self.assertAlmostEqual(r.account.cash,1086.04)
    def test_reduce_only_never_reverses(self):
        r=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'}).rebalance(alloc(-1.),'ETH',Account(1000.,5.,100.),quote(),ts=100,reduce_only=True)
        self.assertEqual(r.account.position,0.)
    def test_inverse_execution_refused(self):
        with self.assertRaises(ValueError):ExecutionSimulator(schedule(),'inverse',max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'})
    def test_liquidation_needs_mark_and_buffer(self):
        s=ExecutionSimulator(schedule(),max_quote_age_s=60,asset_to_symbol={'ETH':'ETH-USD'});a=Account(100.,10.,100.)
        with self.assertRaises(ValueError):s.liquidation_required(a,quote(mark=None),100)
        self.assertTrue(s.liquidation_required(a,quote(),100))
        r=s.liquidate(a,quote(),100);self.assertEqual(r.account.position,0.)
        self.assertTrue(r.event.liquidation_approximate);self.assertAlmostEqual(r.event.fee_paid,9.9)

class StatisticsTests(unittest.TestCase):
    def test_no_search_reference_probability(self):
        self.assertEqual(expected_max_sharpe(1,.1),0.)
        self.assertEqual(dsr(0.,100,0.,3.,1,.1)['probability'],.5)
    def test_increasing_n_deflates(self):
        self.assertGreater(dsr(.1,1000,0,3,2,.01)['probability'],dsr(.1,1000,0,3,1483,.01)['probability'])
    def test_moments_fail_closed(self):
        for t,k in [(2,3),(100,math.nan),(100,.5)]:
            with self.assertRaises(ValueError):dsr(.1,t,0,k,2,.01)
    def test_cscv_symmetric_ties(self):
        v=np.array([.01,-.01,.02,-.02]*4);r=cscv(np.column_stack((v,v)))
        self.assertEqual(r['splits'],70);self.assertEqual(r['tie_splits'],70);self.assertEqual(r['pbo'],1.)
    def test_stable_best_rank(self):
        v=np.array([.01,-.01,.02,-.02]*4);r=cscv(np.column_stack((v,v+.02)))
        self.assertEqual(r['pbo'],0.)
    def test_tail_logged_not_mutated(self):
        v=np.arange(19.)%3;x=np.column_stack((v,v+.1));old=x.copy();r=cscv(x)
        self.assertEqual(r['tail_rows_excluded'],3);np.testing.assert_array_equal(x,old)
    def test_sparse_zero_cash_column_allowed(self):
        v=np.array([.01,-.01,.02,-.02]*4);r=cscv(np.column_stack((np.zeros(16),v+.02)))
        self.assertEqual(r['pbo'],0.)
    def test_invalid_matrix_refused(self):
        for x in (np.ones((16,2)),np.full((16,2),math.nan),np.ones((4,2))):
            with self.assertRaises(ValueError):cscv(x)

if __name__=='__main__':unittest.main()
