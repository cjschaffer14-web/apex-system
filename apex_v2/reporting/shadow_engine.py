"""Callable shadow-only integration boundary; deliberately no new runner.
Existing collectors call observe() and later feedback() with measured outcomes.
"""
from dataclasses import asdict
from .episode_packet import SCHEMA_VERSION,validate_packet
from ..economics.formulas import FORMULAS,capital_time_efficiency
from ..optimizer.allocator import allocate
class ShadowEngine:
    def __init__(self,store,code_commit,model_versions):
        self.store=store; self.code_commit=code_commit; self.model_versions=model_versions
    def observe(self,episode_id,ts_ns,market,mechanism,venues,observations,opportunity,state,candidates,source_ids,risk_penalty=0):
        if any(c.episode_id!=episode_id for c in candidates): raise ValueError('episode mismatch')
        a=allocate(candidates,state,risk_penalty)
        capital=sum(c.capital_usd for c in a.selected)
        capital_seconds=sum(c.capital_usd*c.seconds_at_risk for c in a.selected)
        expected=sum(c.nev for c in a.selected)
        packet={'schema_version':SCHEMA_VERSION,'episode_id':episode_id,'timestamp_ns':ts_ns,'market':market,'mechanism':mechanism,'economic_venues':venues,'observations':observations,'opportunity':opportunity,'agent_state':{**asdict(state),'available_venues':sorted(state.available_venues)},'prediction':{'capture_probability_by_candidate':{c.candidate_id:c.capture_probability for c in candidates},'expected_net_value_usd':expected,'expected_capital_time_efficiency':expected/capital_seconds if capital_seconds else None},'decision':{'mode':state.mode,'orders_authorized':False,'selected_candidate_ids':[c.candidate_id for c in a.selected],'rejected':a.rejected,'constraints':a.diagnostics},'realized_shadow_outcome':{'status':'pending','net_usd':None},'attribution':{},'provenance':{'formula_ids':list(FORMULAS),'formulas':FORMULAS,'model_versions':self.model_versions,'source_ids':source_ids,'code_commit':self.code_commit},'censoring':{'right_censored':True,'reason':'outcome_pending'},'selection':{'candidate_count':len(candidates),'selected_count':len(a.selected)}}
        previous=next((p for p in self.store.packets() if p['episode_id']==episode_id),None)
        if previous:
            # Freeze the original prediction/decision and never erase measured feedback.
            for k in ('timestamp_ns','prediction','decision','realized_shadow_outcome','attribution','censoring','provenance','agent_state','selection'): packet[k]=previous[k]
            packet['last_observation_ns']=ts_ns
        self.store.save(packet); return packet
    def feedback(self,episode_id,outcome,attribution,censored=False):
        packets={p['episode_id']:p for p in self.store.packets()}
        p=packets[episode_id]
        if outcome.get('mode') not in ('shadow','paper'): raise ValueError('shadow/paper outcome required')
        p['realized_shadow_outcome']=outcome; p['attribution']=attribution
        p['censoring']={'right_censored':bool(censored),'reason':'unresolved' if censored else None}
        self.store.save(p); return p
