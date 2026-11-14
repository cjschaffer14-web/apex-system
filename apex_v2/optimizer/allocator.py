"""Exact bounded discrete F4 shadow allocation; no execution API.
Candidates must list prepositioned starting inventory. One action per episode.
For larger universes refuse rather than mislabel a greedy heuristic as global.
"""
from dataclasses import dataclass, replace
from ..agent.feasibility import violations
@dataclass(frozen=True)
class Allocation:
    selected: tuple
    objective_usd: float
    rejected: dict
    diagnostics: dict
    mode: str
    orders_authorized: bool = False

def allocate(candidates,state,risk_penalty=0,diagnostics=True):
    from ..economics.formulas import finite
    finite(risk_penalty)
    if risk_penalty<0: raise ValueError('negative risk penalty')
    if len(candidates)>20: raise ValueError('bounded exact allocator limit: 20 candidates')
    if len({c.candidate_id for c in candidates})!=len(candidates): raise ValueError('duplicate candidate ID')
    rejected={c.candidate_id:violations(c,state) for c in candidates}
    eligible=[c for c in candidates if not rejected[c.candidate_id]]
    best=(0.0,())
    def visit(i,selected,capital,margin,inventory,venue,episodes,value):
        nonlocal best
        if value>best[0]: best=(value,tuple(selected))
        if i==len(eligible): return
        c=eligible[i]
        visit(i+1,selected,capital,margin,inventory,venue,episodes,value)
        if c.episode_id in episodes or capital+c.capital_usd>state.capital_usd or margin+c.margin_usd>state.margin_usd: return
        ni={k:inventory.get(k,0)+c.inventory_required.get(k,0) for k in inventory.keys()|c.inventory_required.keys()}
        nv={k:venue.get(k,0)+c.venue_usage.get(k,0) for k in venue.keys()|c.venue_usage.keys()}
        if any(v>state.inventory.get(k,0) for k,v in ni.items()) or any(v>state.venue_limits[k] for k,v in nv.items()): return
        visit(i+1,selected+[c],capital+c.capital_usd,margin+c.margin_usd,ni,nv,episodes|{c.episode_id},value+c.nev-risk_penalty*c.risk_proxy)
    visit(0,[],0,0,{}, {},set(),0)
    diag={'scope':'exact discrete supplied candidate universe','capital_slack_usd':state.capital_usd-sum(c.capital_usd for c in best[1]),'shadow_values':{}}
    # A one-sided re-solve is a discrete marginal value, never an LP dual price.
    if diagnostics and eligible:
        bump=max(1,state.capital_usd*.01)
        extra=allocate(candidates,replace(state,capital_usd=state.capital_usd+bump),risk_penalty,False)
        diag['shadow_values']['capital_discrete_marginal_usd_per_usd']=(extra.objective_usd-best[0])/bump
        diag['shadow_values']['method']='one-sided bounded discrete re-solve; not a dual'
    return Allocation(best[1],best[0],rejected,diag,state.mode)
