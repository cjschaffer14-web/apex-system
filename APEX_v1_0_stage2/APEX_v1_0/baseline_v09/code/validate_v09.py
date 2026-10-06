#!/usr/bin/env python3
import json, sys, hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,'/mnt/data/APEX_v09_cross_ai')
sys.path.insert(0,'/mnt/data/APEX_backtesting_v06')
import trading_backtest_v09 as v9
import trading_backtest_v06 as v6
import trading_backtest_v08 as v8

DB='/mnt/data/market_2026-10-03.sqlite'

def clone(d):
    out={}
    for k,v in d.items():
        try: out[k]=np.array(v, copy=True)
        except Exception: out[k]=v
    return out

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

results={'research_only':True,'tests':[]}
for pair in ['BTC-USD','ETH-USD']:
    d=v6.load_sqlite(DB,pair,1440)
    n=len(d['close']); cutoff=n-400
    base_state,_=v9.classify_states(d)
    dm=clone(d)
    # Alter only future OHLCV after cutoff with a large deterministic transform.
    idx=np.arange(n-cutoff)
    fac=np.exp(0.004*np.sin(idx/7.0)+0.0005*idx)
    for k in ['open','high','low','close']:
        dm[k][cutoff:]=dm[k][cutoff:]*fac
    dm['volume'][cutoff:]=dm['volume'][cutoff:]*(1.0+0.5*np.sin(idx/5.0)**2)
    mod_state,_=v9.classify_states(dm)
    state_ok=bool(np.array_equal(base_state[:cutoff],mod_state[:cutoff]))
    results['tests'].append({'pair':pair,'test':'future_mutation_does_not_change_past_market_states','cutoff_index':cutoff,'pass':state_ok})

    # Causal geometric pivot state prefix invariance at each frozen scale.
    for nm,am,mp in [('fast',1.5,.03),('medium',2.5,.05),('slow',4.0,.08)]:
        def sig(x):
            c=np.asarray(x['close'],float); h=np.asarray(x['high'],float); l=np.asarray(x['low'],float)
            A=v6.atr(h,l,c,14); piv=v6.causal_zigzag(c,h,l,A,am,mp); states=v6.pivot_state_series(len(c),piv)
            out=[]
            for t in range(cutoff):
                out.append(tuple((p.pivot_i,p.known_i,p.kind,round(float(p.price),8)) for p in states[t]))
            return out
        geom_ok=(sig(d)==sig(dm))
        results['tests'].append({'pair':pair,'test':f'future_mutation_does_not_change_past_{nm}_geometry_state','pass':bool(geom_ok)})

    # State-conditioned mixture prefix invariance; compare returns safely before cutoff-2.
    b=v9.mixture_returns(d,25.0,False)['returns']
    m=v9.mixture_returns(dm,25.0,False)['returns']
    upto=max(0,cutoff-2)
    mix_ok=bool(np.allclose(b[:upto],m[:upto],equal_nan=True,atol=1e-12,rtol=1e-12))
    results['tests'].append({'pair':pair,'test':'future_mutation_does_not_change_past_strategy_mixture_returns','pass':mix_ok,'compared_returns':upto})

# Matrix Kelly singular/near-singular numerical stability (existing implementation stress check).
rng=np.random.default_rng(20261003)
x=rng.normal(0,0.01,700)
R=np.column_stack([x, x*1.00000001, x+1e-10*rng.normal(size=len(x))])
S=np.ones_like(R,dtype=bool)
W,_=v8.matrix_kelly(R,S,fraction=1.0,gross_cap=3.0,per_asset_cap=2.0)
kelly_ok=bool(np.isfinite(W).all() and np.max(np.sum(np.abs(W),axis=1)) <= 3.0000001)
results['tests'].append({'test':'matrix_kelly_near_singular_covariance_is_finite_and_gross_capped','pass':kelly_ok,'max_gross':float(np.max(np.sum(np.abs(W),axis=1)))})

results['all_pass']=all(x['pass'] for x in results['tests'])
results['database_sha256']=sha(DB)
Path('/mnt/data/APEX_v09_cross_ai/validation_v09.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
