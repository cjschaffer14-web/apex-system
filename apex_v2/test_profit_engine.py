import unittest,tempfile
from pathlib import Path
from dataclasses import replace
from decimal import Decimal as D
from .economics.formulas import *
from .economics.opportunity_value import Candidate
from .agent.balance_sheet import AgentState
from .optimizer.allocator import allocate
from .episodes.survival_model import SurvivalModel
from .episodes.tracker import EpisodeStore
from .episodes.detector import PersistentDetector
from .observatory.observations import *
from .observatory.state_estimator import aggregate_source_status
from .research.promotion import qualify,ModelCard
from .reporting.shadow_engine import ShadowEngine
from .reporting.ai_export import export_packets
from .optimizer.rebalance_policy import compare_matched
from .evaluation.shadow_replay import evaluate
from .evaluation.baselines import STAGES
from .optimizer.candidate_generator import dex_closed_cycle,cex_cycle
from .core import Book,Level,Leg
class ProfitEngineTests(unittest.TestCase):
    def state(self): return AgentState(10,10,{'A:USD':100},{'A':100},frozenset({'A'}))
    def c(self,id,ep,g=5,capital=5,**kw): return Candidate(id,ep,g,1,0,0,capital,1,**kw)
    def obs(self,venue,source,depth=10,executable=True): return MarketObservation(100,'ETH',venue,'cex',source,100,101,depth,depth,executable=executable)
    def test_formulas(self):
        self.assertEqual(gross_value(110,100,2),8); self.assertEqual(net_expected_value(.8,8,2,1),5)
        self.assertEqual(capital_time_efficiency(5,10,2),.25); self.assertIsNone(capital_time_efficiency(5,0,2))
    def test_nonfinite(self):
        with self.assertRaises(ValueError): net_expected_value(float('nan'),1,1,1)
        with self.assertRaises(ValueError): AgentState(float('inf'),10)
        with self.assertRaises(ValueError): allocate([self.c('a','a',capital=-1)],self.state())
    def test_exact_beats_greedy(self):
        a=allocate([self.c('large','1',8,10),self.c('small1','2'),self.c('small2','3')],self.state())
        self.assertEqual(a.objective_usd,10); self.assertEqual(len(a.selected),2); self.assertFalse(a.orders_authorized)
    def test_shared_resources(self):
        rows=[self.c('a','a',inventory_required={'A:USD':60}),self.c('b','b',inventory_required={'A:USD':60})]
        self.assertEqual(len(allocate(rows,self.state()).selected),1)
        self.assertFalse(allocate([self.c('a','a',margin_usd=11)],self.state()).selected)
        self.assertFalse(allocate([self.c('a','a',venue_usage={'unknown':1})],self.state()).selected)
    def test_hard_vetoes(self):
        for kw in ({'quality_ok':False},{'settlement_ok':False},{'liquidity_ok':False},{'feature_status':'qualified'},{'feature_status':'research'}):
            self.assertFalse(allocate([self.c('a','a',**kw)],self.state()).selected)
        with self.assertRaises(ValueError): replace(self.state(),mode='paper')
        self.assertEqual(replace(self.state(),mode='live').mode,'live')
        self.assertFalse(allocate([self.c('a','a')],replace(self.state(),legal_allowed=False)).selected)
    def test_episode_alternatives(self): self.assertEqual(len(allocate([self.c('a','same'),self.c('b','same')],self.state()).selected),1)
    def test_reference_and_redundant_depth(self):
        rows=[self.obs('a','a1'),self.obs('a','a2',100),self.obs('b','ref',executable=False)]
        s=ShadowPriceEngine().build('ETH',rows,100)
        self.assertEqual(s.independent_venues,1); self.assertEqual(s.effective_depth_usd,10); self.assertIn('ref',s.rejected_sources)
    def test_future_rejected(self):
        with self.assertRaises(ValueError): ShadowPriceEngine().build('ETH',[self.obs('a','a')],99)
    def test_source_partial(self): self.assertEqual(aggregate_source_status({'BTC':{'a':'reachable'},'ETH':{'a':'blocked'}})['a']['status'],'partial')
    def test_censoring_survival(self):
        m=SurvivalModel.fit([(1,True),(1,False),(2,True),(3,False)])
        self.assertEqual(m.survival(1),.75); self.assertEqual(m.survival(2),.375); self.assertEqual(m.half_life,2)
    def measurement(self,t,spread): return OpportunityMeasurement(t,Lane.CEX_DEX,'ETH','a','b','cex',100,99,101,spread,10,CostEstimate(),1,20,1)
    def test_detector_restart_and_decay(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'episodes.sqlite'); t=PersistentDetector(path); first=t.ingest(self.measurement(100,10)).episode_id; t.close()
            t=PersistentDetector(path); self.assertEqual(next(iter(t.active.values())).episode_id,first)
            ep=t.ingest(self.measurement(200,1)); self.assertIsNone(ep.capture_ns); t.close()
    def test_packet_feedback_and_export(self):
        with tempfile.TemporaryDirectory() as d:
            store=EpisodeStore(str(Path(d)/'p.db')); engine=ShadowEngine(store,'commit+dirty',{'capture':'prior'})
            p=engine.observe('ep',100,'ETH/USD','cex_cycle',['A'],{'freshness_seconds':0,'uncertainty':1},{'gross_usd':5,'cost_usd':0,'net_usd':5,'optimal_size_usd':5,'half_life_seconds':None},self.state(),[self.c('a','ep')],['fixture'])
            self.assertFalse(p['decision']['orders_authorized']); self.assertTrue(p['censoring']['right_censored'])
            engine.feedback('ep',{'mode':'shadow','status':'measured','net_usd':3},{'net_usd':3})
            self.assertEqual(len(store.packets()),1); export_packets(store.packets(),Path(d)/'p.jsonl'); p['api_key']='do-not-export'
            with self.assertRaises(ValueError): export_packets([p],Path(d)/'bad')
            store.close()
    def row(self): return {'episode_id':'e','birth_ns':10,'outcome_ns':20,'predictions':{s:{'asof_ns':10,'select':True,'capture_probability':.8,'compute_seconds':.1} for s in STAGES},'outcomes':{s:{'net_usd':-2,'turnover_usd':10,'movement_cost_usd':1,'capital_seconds':20,'capture':0,'failed':1,'risk_proxy':1,'censored':False} for s in STAGES}}
    def test_seven_stage_evaluation(self):
        r=evaluate([self.row()],1,2)
        for s in STAGES:
            self.assertEqual(r['stages'][s]['net_usd'],-2); self.assertEqual(r['stages'][s]['drawdown_usd'],2); self.assertAlmostEqual(r['stages'][s]['brier'],.64)
    def test_leakage_missing_and_censoring(self):
        row=self.row(); row['predictions']['spread_only']['asof_ns']=11
        with self.assertRaises(ValueError): evaluate([row],1,2)
        row=self.row(); del row['outcomes']['competition']; self.assertIsNone(evaluate([row],1,2)['stages']['competition']['net_usd'])
        row=self.row(); row['outcomes']['spread_only']['censored']=True; self.assertEqual(evaluate([row],1,2)['stages']['spread_only']['censored'],1)
    def test_promotion(self):
        self.assertEqual(qualify({}, {})['status'],'research')
        row={'episode_ids':['e'],'held_out':True,'net_usd':2,'brier':.2,'drawdown_usd':0,'failure_rate':0,'compute_seconds':1,'capital_time_efficiency':.1,'turnover_usd':2}
        self.assertEqual(qualify(row,row,min_episodes=1)['status'],'research'); feature={**row,'net_usd':3}
        self.assertEqual(qualify(row,feature,min_episodes=1)['status'],'qualified'); self.assertFalse(qualify(row,feature,min_episodes=1)['orders_authorized'])
        with self.assertRaises(ValueError): ModelCard('m','capture',(),(0,10),(10,20),{},{}).validate()
    def test_matched_hypothesis(self):
        keys=('net_usd','turnover_usd','movement_cost_usd','capital_seconds','inventory_utilization','failure_proxy','risk_proxy'); a=dict.fromkeys(keys,1); b={**a,'net_usd':-1}
        self.assertEqual(compare_matched({'e':a},{'e':b})['metrics']['net_usd']['delta'],-2)
        with self.assertRaises(ValueError): compare_matched({'e':a},{})
    def test_dex_integer_reference_free(self):
        r=dex_closed_cycle('a','e',[(1000000,2000000,997,1000),(1000000,600000,997,1000)],[('USD','ETH'),('ETH','USD')],1000,.5,1,0,1)
        self.assertEqual(r['accounting'],'reference_free_closed_cycle'); self.assertIsInstance(r['terminal_native'],int)
        with self.assertRaises(ValueError): dex_closed_cycle('a','e',[(1,1,997,1000)],[('USD','ETH')],1,.5,1,0,1)
    def test_cex_fee_and_freshness(self):
        books={('A','ETH/USD'):Book('A','ETH/USD',[Level(D(99),D(100))],[Level(D(100),D(100))],100)}; legs=[Leg('A','ETH/USD','buy'),Leg('A','ETH/USD','sell')]
        c=cex_cycle('c','e',books,legs,100,{'A':D('.01')},100,1,0,0,1); self.assertAlmostEqual(c.gross_usd,99*.99*.99-100)
        self.assertIsNone(cex_cycle('c','e',books,legs,100,{},3000000000,1,0,0,1))

    def test_repeated_observation_preserves_prediction_and_feedback(self):
        with tempfile.TemporaryDirectory() as d:
            store=EpisodeStore(str(Path(d)/'p.db')); engine=ShadowEngine(store,'commit',{'capture':'prior'})
            args=('ep',100,'ETH/USD','cycle',['A'],{}, {},self.state(),[self.c('a','ep')],['fixture'])
            first=engine.observe(*args); engine.feedback('ep',{'mode':'shadow','net_usd':3},{})
            later=list(args); later[1]=200; later[8]=[]; p=engine.observe(*later)
            self.assertEqual(p['timestamp_ns'],100); self.assertEqual(p['realized_shadow_outcome']['net_usd'],3); self.assertEqual(p['prediction'],first['prediction']); store.close()
    def test_missing_promotion_metric_blocks(self):
        row={'episode_ids':['e'],'held_out':True,'net_usd':None,'brier':None,'drawdown_usd':0,'failure_rate':0,'compute_seconds':1,'capital_time_efficiency':None,'turnover_usd':0}
        self.assertEqual(qualify(row,row)['status'],'research')
    def test_pipeline_persists_without_authorization(self):
        from .observatory.pipeline import observe_snapshot
        with tempfile.TemporaryDirectory() as d:
            rows=[self.obs('A','a'),MarketObservation(100,'ETH','B','cex','b',110,111,10,10)]
            packets=observe_snapshot(rows,self.state(),d,100,'commit')
            self.assertTrue(packets); self.assertFalse(packets[0]['decision']['orders_authorized']); self.assertIsNone(packets[0]['opportunity']['net_usd'])
            self.assertTrue((Path(d)/'observations.jsonl').exists())
    def test_open_transition_requires_declared_valuation(self):
        from .optimizer.rebalance_policy import value_open_transition
        with self.assertRaises(ValueError): value_open_transition({'ETH':1},{'ETH':2},{'ETH':100},'')
        self.assertEqual(value_open_transition({'ETH':1},{'ETH':2},{'ETH':100},'shadow-v1')['terminal_minus_initial_usd'],100)
    def test_baseline_generation_is_shadow_and_missing_science_unavailable(self):
        from .evaluation.baselines import build_predictions
        from .economics.capture_model import CaptureModel
        features={'terminal_minus_initial_usd':6,'success_cost_usd':1,'observatory_select':True,'age_seconds':0,'latency_seconds':.1,'reliability':.9,'uncertainty':.1,'failure_loss_usd':2,'holding_cost_usd':.1,'agent_feasible':False}
        p=build_predictions(features,CaptureModel(),SurvivalModel.fit([(1,True)]),100,50)
        self.assertNotIn('scientific_features',p);self.assertNotIn('competition',p);self.assertFalse(p['agent_inventory']['select'])
        with self.assertRaises(ValueError): build_predictions(features,CaptureModel(),SurvivalModel.fit([]),50,50)
    def test_unpromoted_competition_blocked_in_economics(self):
        from .economics.capture_model import CaptureModel
        with self.assertRaises(ValueError): CaptureModel().predict(SurvivalModel.fit([]),0,.1,1,0,crowding=1)
