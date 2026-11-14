"""Reuse executable CEX walks and integer DEX math; no depth*spread AMM shortcut."""
from decimal import Decimal
from dataclasses import replace
from ..core import simulate_cycle
from ..economics.formulas import gross_value
from ..economics.opportunity_value import Candidate

def cex_cycle(candidate_id,episode_id,books,legs,size,fees,now_ns,p,failure_loss,holding_cost,seconds,extra_costs=0,max_age_ms=2000,quality_verified=False,settlement_verified=False):
    if any(l.venue not in fees for l in legs): return None
    for b in books.values():
        if not b.bids or not b.asks or b.bids[0].price>=b.asks[0].price or b.received_ns>now_ns: return None
    result,error=simulate_cycle(books,legs,Decimal(str(size)),fees,now_ns=now_ns,max_age_ms=max_age_ms)
    if error: return None
    required={}; usage={}
    # Conservatively require each leg's initial inventory to be prepositioned.
    for f in result.fills:
        k=f.leg.venue+':'+f.leg.asset_in
        required[k]=required.get(k,0)+float(f.amount_in)
        usage[f.leg.venue]=usage.get(f.leg.venue,0)+size
    return Candidate(candidate_id,episode_id,gross_value(float(result.end_usd),size,extra_costs),p,failure_loss,holding_cost,size,seconds,inventory_required=required,venue_usage=usage,turnover_usd=size*len(legs),quality_ok=quality_verified,settlement_ok=settlement_verified)

def dex_closed_cycle(candidate_id,episode_id,pools,inputs,size,p,failure_loss,holding_cost,seconds,gas_start_units=0):
    # Each pool is (reserve_in,reserve_out,fee_numerator,fee_denominator).
    from ..dexdata.univ2 import get_amount_out
    if len(pools)!=len(inputs) or not pools: raise ValueError('invalid DEX path')
    if inputs[0][0]!=inputs[-1][1] or any(a[1]!=b[0] for a,b in zip(inputs,inputs[1:])): raise ValueError('not a closed cycle')
    if not isinstance(size,int) or size<=0 or gas_start_units<0: raise ValueError('invalid integer input')
    if any(min(rin,rout,fn,fd)<=0 or fn>fd for rin,rout,fn,fd in pools): raise ValueError('invalid reserves or fees')
    amount=size
    for rin,rout,fn,fd in pools: amount=get_amount_out(amount,rin,rout,fn,fd)
    # Native-token result: caller must explicitly value it before USD allocation.
    return {'candidate_id':candidate_id,'episode_id':episode_id,'accounting':'reference_free_closed_cycle','start_token':inputs[0][0],'initial_native':size,'terminal_native':amount,'F1_native':amount-size-gas_start_units,'capture_probability':p,'failure_loss_native':failure_loss,'holding_cost_native':holding_cost,'seconds_at_risk':seconds}
