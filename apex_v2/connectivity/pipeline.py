"""Snapshot -> existing state estimator -> size-aware F1/F2/F3 -> episodes.
Cross-venue pairs assume pre-positioned USD on buy venue and base on sell venue.
They are matched inventory observations, never an implied instantaneous transfer.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
from uuid import uuid4
import json
from ..core import walk_buy, walk_sell
from ..economics.formulas import gross_value, net_expected_value, finite, FORMULAS
from ..observatory.state_estimator import estimate, StateEstimate
from ..reporting.episode_packet import SCHEMA_VERSION, validate_packet

@dataclass(frozen=True)
class Policy:
    size_usd: float = 100
    capture_probability: float = .1  # deliberately uncalibrated observation prior
    failure_loss_usd: float = 1
    holding_cost_usd: float = .1
    buffer_bps: float = 10
    max_age_s: float = 2
    max_skew_s: float = 1
    def validate(self):
        finite(*asdict(self).values())
        if self.size_usd <= 0 or self.max_age_s <= 0 or self.max_skew_s < 0 or not 0 <= self.capture_probability <= 1 or min(self.failure_loss_usd,self.holding_cost_usd,self.buffer_bps) < 0:
            raise ValueError('invalid shadow policy')

class SnapshotStateEstimator:
    """Adapter into the saved observatory StateEstimate implementation."""
    def update_curves(self, curves, now_ns, max_age_s=10):
        """Use the existing StateEstimate contract without inventing a fiat mark.
        Curves retain raw-token reserve units in source_status; shadow_price is
        unknown until a declared valuation and compatible market exist.
        """
        chosen={}; rejected={}
        for curve in sorted(curves,key=lambda c:c.received_ns):
            try: curve.fresh(now_ns,max_age_s)
            except ValueError as e: rejected[curve.source_id]=str(e); continue
            chosen[curve.economic_venue_id]=curve
        rows=list(chosen.values())
        state=StateEstimate(None,1.0,{c.source_id:(now_ns-c.source_ns)/1e9 for c in rows},(),
                            {c.source_id:{'economic_venue_id':c.economic_venue_id,'endpoint_id':c.endpoint_id,
                                          'token0':c.token0,'token1':c.token1,'reserve0_raw':c.reserve0,
                                          'reserve1_raw':c.reserve1,'block_hash':c.block_hash,
                                          'fee_numerator':c.fee_numerator,'fee_denominator':c.fee_denominator,
                                          'valuation':'unknown','synthetic':c.synthetic} for c in rows})
        return rows,state,rejected

    def update(self, snapshots, now_ns, max_age_s=2):
        fresh=[]; rejected={}
        for snapshot in snapshots:
            try: fresh.append(snapshot.fresh(now_ns,max_age_s))
            except ValueError as e: rejected[snapshot.source_id]=str(e)
        # Choose newest endpoint per economic venue and pair, never sum depth.
        chosen={}
        for s in sorted(fresh,key=lambda x:x.request_ns): chosen[s.economic_venue_id,s.book.pair]=s
        states={}
        observations=[s.observation() for s in chosen.values()]
        for pair in {s.book.pair for s in chosen.values()}:
            states[pair]=estimate(pair,observations,now_ns,max_age_s)
        return list(chosen.values()), states, rejected

def pair_value(buy, sell, size_usd):
    if buy.fee_bps is None or sell.fee_bps is None: return None
    first=walk_buy(buy.book.asks,Decimal(str(size_usd)))
    if first is None: return None
    qty=first[0]*(1-Decimal(str(buy.fee_bps))/10000)
    second=walk_sell(sell.book.bids,qty)
    if second is None: return None
    terminal=second[0]*(1-Decimal(str(sell.fee_bps))/10000)
    return float(terminal), float(qty)

def packet(now_ns, market, mechanism, venues, observations, opportunity, agent_state, prediction, decision, sources):
    p={'schema_version':SCHEMA_VERSION,'episode_id':uuid4().hex,'timestamp_ns':now_ns,
       'market':market,'mechanism':mechanism,'economic_venues':venues,
       'observations':observations,'opportunity':opportunity,'agent_state':agent_state,
       'prediction':prediction,'decision':{'mode':'shadow','orders_authorized':False,**decision},
       'realized_shadow_outcome':{'mode':'shadow','status':'pending','net_usd':None,'capture_evidence':False},
       'attribution':{},'provenance':{'formula_ids':list(FORMULAS),'model_versions':{'capture':'uncalibrated-fixed-prior-v1','cost':'snapshot-walk-buffer-v1'},'source_ids':sources,'code_commit':'uncommitted'},
       'censoring':{'right_censored':True,'reason':'outcome_pending'},'selection':{'candidate_count':1}}
    return validate_packet(p)

class CandidatePipeline:
    def __init__(self, policy=Policy(), inventory=None):
        policy.validate()
        self.policy,self.inventory=policy,dict(inventory or {})
        finite(*self.inventory.values())
        if any(v<0 for v in self.inventory.values()): raise ValueError('negative inventory')
        self.estimator=SnapshotStateEstimator()
        self.pending={}
        self.last_states={}
        self.rejected={}
    def observe(self, snapshots, now_ns):
        p=self.policy
        snapshots,self.last_states,self.rejected=self.estimator.update(snapshots,now_ns,p.max_age_s)
        out=[]
        # Later snapshots measure persistence at the same size, not actual fills.
        for eid, saved in list(self.pending.items()):
            old,bid,sid=saved
            buy=next((s for s in snapshots if s.economic_venue_id==bid and s.book.pair==old['market']),None)
            sell=next((s for s in snapshots if s.economic_venue_id==sid and s.book.pair==old['market']),None)
            if now_ns<=old['timestamp_ns']: continue
            value=None
            has_followup=False
            if buy and sell and min(buy.request_ns,sell.request_ns)>old['timestamp_ns'] and abs(buy.request_ns-sell.request_ns)<=p.max_skew_s*1e9:
                has_followup=True
                value=pair_value(buy,sell,p.size_usd)
            if not has_followup and now_ns-old['timestamp_ns']<=p.max_age_s*1e9: continue
            updated=json.loads(json.dumps(old))
            net=gross_value(value[0],p.size_usd,p.size_usd*p.buffer_bps/10000) if value else None
            updated['realized_shadow_outcome']={'mode':'shadow','status':'later_snapshot_observation' if value else ('later_snapshot_unvalued' if has_followup else 'missing_fresh_followup'),
                                               'timestamp_ns':now_ns,'net_usd':net,'capture_evidence':False,
                                               'survived_net_positive':net>0 if net is not None else None}
            updated['censoring']={'right_censored':value is None,'reason':('unknown_fees_or_depth' if has_followup else 'missing_followup') if value is None else None}
            updated['attribution']={'outcome_source_ids':[s.source_id for s in (buy,sell) if s], 'execution_simulated':False}
            out.append(validate_packet(updated)); del self.pending[eid]
        for buy in snapshots:
            for sell in snapshots:
                if buy.economic_venue_id==sell.economic_venue_id or buy.book.pair!=sell.book.pair: continue
                if abs(buy.request_ns-sell.request_ns)>p.max_skew_s*1e9: continue
                # A detected candidate is a positive top-of-book discrepancy; log cost rejection too.
                if sell.book.bids[0].price<=buy.book.asks[0].price: continue
                value=pair_value(buy,sell,p.size_usd)
                reasons=[]
                if value is None:
                    reasons.append('unknown_fees' if buy.fee_bps is None or sell.fee_bps is None else 'insufficient_depth')
                base,quote=buy.book.pair.split('/')
                if quote!='USD': continue
                qty=value[1] if value else None
                if self.inventory.get(buy.economic_venue_id+':USD',0)<p.size_usd: reasons.append('buy_inventory_unverified')
                if qty is None or self.inventory.get(sell.economic_venue_id+':'+base,0)<qty: reasons.append('sell_inventory_unverified')
                costs=p.size_usd*p.buffer_bps/10000
                g=gross_value(value[0],p.size_usd,costs) if value else None
                nev=net_expected_value(p.capture_probability,g,p.failure_loss_usd,p.holding_cost_usd) if g is not None else None
                if nev is not None and nev<=0: reasons.append('nonpositive_nev')
                s=self.last_states[buy.book.pair]
                ep=packet(now_ns,buy.book.pair,'matched_cross_venue_inventory',[buy.economic_venue_id,sell.economic_venue_id],
                          {'freshness_seconds':{x.source_id:(now_ns-min(x.request_ns,x.source_ns or x.request_ns))/1e9 for x in (buy,sell)},'uncertainty':s.uncertainty,
                           'timestamp_basis':{x.source_id:'source_and_request' if x.source_ns else 'request_start' for x in (buy,sell)},
                           'endpoint_ids':[buy.endpoint_id,sell.endpoint_id],'synthetic':buy.synthetic or sell.synthetic},
                          {'size_usd':p.size_usd,'terminal_usd':value[0] if value else None,'gross_usd':g,'buffer_usd':costs,
                           'fee_bps':{buy.economic_venue_id:buy.fee_bps,sell.economic_venue_id:sell.fee_bps},
                           'fees_embedded_in_terminal':True,'impact_embedded_in_book_walk':True},
                          {'inventory':self.inventory,'assumption':'prepositioned inventory; no transfers; no balance API'},
                          {'capture_probability':p.capture_probability,'calibrated':False,'failure_loss_usd':p.failure_loss_usd,'holding_cost_usd':p.holding_cost_usd,'expected_net_value_usd':nev},
                          {'action':'observe','feasible_for_simulation':not reasons,'reason_codes':reasons},[buy.source_id,sell.source_id])
                out.append(ep); self.pending[ep['episode_id']]=(ep,buy.economic_venue_id,sell.economic_venue_id)
        return out

    def finish(self, now_ns):
        rows=[]
        for ep,_,_ in self.pending.values():
            ep=json.loads(json.dumps(ep)); ep['realized_shadow_outcome']['status']='runner_ended'
            ep['realized_shadow_outcome']['timestamp_ns']=now_ns
            ep['censoring']={'right_censored':True,'reason':'runner_ended_without_followup'}
            rows.append(validate_packet(ep))
        self.pending.clear(); return rows

def dex_cycle_packet(curves, start_token, amount_in, now_ns, *, native_unit_usd=None, gas_usd=None, policy=Policy()):
    """Fixed-size closed cycle; fee/impact included exactly, gas must be declared.
    No USD peg is inferred. Absent valuation/gas => native observation only.
    """
    policy.validate()
    if len(curves)<2 or len({c.economic_venue_id for c in curves})!=len(curves): raise ValueError('repeated pool is not independent')
    if len({(c.chain_id,c.block_hash,c.block_number) for c in curves})!=1: raise ValueError('curves need same chain/block')
    if type(amount_in) is not int or amount_in<=0: raise ValueError('invalid native input')
    x=amount_in; token=start_token
    for c in curves:
        c.fresh(now_ns)
        x=c.quote(token,x); token=c.token1 if token==c.token0 else c.token0
    if token!=start_token: raise ValueError('not a closed token cycle')
    if native_unit_usd is not None:
        finite(native_unit_usd)
        if native_unit_usd<=0: raise ValueError('invalid declared valuation')
    if gas_usd is not None:
        finite(gas_usd)
        if gas_usd<0: raise ValueError('negative gas')
    valued=native_unit_usd is not None and gas_usd is not None
    initial=amount_in*native_unit_usd if valued else None
    buffer=initial*policy.buffer_bps/10000 if valued else None
    g=gross_value(x*native_unit_usd,initial,gas_usd+buffer) if valued else None
    nev=net_expected_value(policy.capture_probability,g,policy.failure_loss_usd,policy.holding_cost_usd) if valued else None
    return packet(now_ns,start_token,'dex_closed_cycle',[c.economic_venue_id for c in curves],
                  {'block_hash':curves[0].block_hash,'block_number':curves[0].block_number,
                   'freshness_seconds':{c.endpoint_id:(now_ns-c.source_ns)/1e9 for c in curves},'synthetic':any(c.synthetic for c in curves)},
                  {'initial_native':amount_in,'terminal_native':x,'native_profit':x-amount_in,'gross_usd':g,
                   'gas_usd':gas_usd,'buffer_usd':buffer,'declared_native_unit_usd':native_unit_usd,'fees_and_impact_embedded':True},
                  {'inventory':'unverified'}, {'capture_probability':policy.capture_probability,'calibrated':False,'expected_net_value_usd':nev},
                  {'action':'observe','reason_codes':['inventory_unverified']+([] if valued else ['gas_or_valuation_unknown'])},
                  [c.endpoint_id+':'+c.economic_venue_id for c in curves])
