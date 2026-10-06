#!/usr/bin/env python3
from __future__ import annotations
import json, math, sqlite3, sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE=Path('/mnt/data/APEX_backtesting_v06')
sys.path.insert(0,str(BASE))
import trading_backtest_v06 as v6
import trading_backtest_v08 as v8

ANNUAL=365
EPS=1e-12


def roll_max(x,n):
    x=np.asarray(x,float); o=np.full(len(x),np.nan)
    for i in range(n-1,len(x)): o[i]=np.max(x[i-n+1:i+1])
    return o


def momentum(c,n):
    o=np.full(len(c),np.nan); o[n:]=c[n:]/c[:-n]-1; return o


def classify_states(data):
    c=np.asarray(data['close'],float)
    m50=v6.sma(c,50); m200=v6.sma(c,200)
    mom30=momentum(c,30); mom90=momentum(c,90)
    vol30=v6.rolling_std_returns(c,30,ANNUAL)
    chop=v6.choppiness(data['high'],data['low'],c,14)
    mx30=roll_max(c,30); dd30=c/np.maximum(mx30,EPS)-1
    state=np.array(['neutral']*len(c),dtype=object)
    # frozen priority order
    panic=np.isfinite(m200)&np.isfinite(vol30)&np.isfinite(dd30)&(c<m200)&(dd30<-.20)&(vol30>=1.00)
    bull_core=np.isfinite(m200)&np.isfinite(m50)&np.isfinite(mom90)&np.isfinite(vol30)&(c>m200)&(m50>m200)&(mom90>0)&(vol30<1.20)
    bull_vol=np.isfinite(m200)&np.isfinite(m50)&np.isfinite(mom90)&np.isfinite(vol30)&(c>m200)&(m50>m200)&(mom90>0)&(vol30>=1.20)
    bear=np.isfinite(m200)&np.isfinite(m50)&np.isfinite(mom90)&(c<m200)&(m50<m200)&(mom90<0)
    recovery=np.isfinite(m200)&np.isfinite(m50)&np.isfinite(mom30)&(c<m200)&(c>m50)&(mom30>0)
    trend=np.isfinite(m200)&np.isfinite(mom90)&np.isfinite(chop)&(c>m200)&(mom90>0)&(chop<55)
    rang=np.isfinite(chop)&np.isfinite(mom30)&(chop>=55)&(np.abs(mom30)<.15)
    assigned=np.zeros(len(c),bool)
    for name,mask in [('panic',panic),('bull_core',bull_core),('bull_volatile',bull_vol),('bear_trend',bear),('recovery',recovery),('trend_up',trend),('range_chop',rang)]:
        take=mask & ~assigned
        state[take]=name; assigned|=take
    features={'sma50':m50,'sma200':m200,'mom30':mom30,'mom90':mom90,'vol30':vol30,'chop14':chop,'dd30':dd30}
    return state,features


def mean_reversion_signal(data):
    c=np.asarray(data['close'],float); ma=v6.sma(c,20)
    dev=c/np.maximum(ma,EPS)-1
    sd=np.full(len(c),np.nan)
    for i in range(19,len(c)): sd[i]=np.nanstd(dev[i-19:i+1],ddof=1)
    z=dev/np.maximum(sd,EPS)
    return np.isfinite(z)&(z<-1.5),z


def mixture_returns(data,cost_bps=25.0,directional=False):
    state,feat=classify_states(data)
    mr,_=mean_reversion_signal(data)
    bull_core=state=='bull_core'; bull_vol=state=='bull_volatile'
    pyr_core=v8.t20_intrabar_pyramid(data,bull_core,stages=(1,2.5,4),trail_atrs=(3.2,1.8,1.0),cost_bps=cost_bps)
    if directional:
        pyr_bv=v8.t20_intrabar_pyramid(data,bull_vol,stages=(1,2,3),trail_atrs=(3.2,2.0,1.2),cost_bps=cost_bps)
        bull_stream=pyr_core['returns']+pyr_bv['returns']
    else:
        bull_stream=pyr_core['returns']
    exp=np.zeros(len(state),float)
    if not directional:
        exp[bull_vol]=1.0
    exp[state=='trend_up']=1.0
    exp[state=='recovery']=0.5
    exp[(state=='range_chop')&mr]=1.0
    if directional:
        exp[state=='bear_trend']=-1.0
        exp[state=='panic']=-0.5
    vec,turn,w=v6.run_vector(data,exp,cost_bps)
    # vec is n-1; bull stream is n. Align day 1..n-1
    r=bull_stream[1:]+vec
    return {'returns':r,'vector_returns':vec,'bull_returns':bull_stream[1:],'exposure':exp,'state':state,'turn':turn,
            'stats':v6.stats(r), 'state_counts':{k:int(np.sum(state==k)) for k in np.unique(state)}}


def expert_streams(data,cost_bps=25.0):
    state,_=classify_states(data); mr,_=mean_reversion_signal(data)
    n=len(state)
    streams={}
    # Event-driven bull experts
    for nm,mask,st,tr in [
      ('pyramid_core_1_2.5_4',state=='bull_core',(1,2.5,4),(3.2,1.8,1.0)),
      ('pyramid_bullvol_1_2_3',state=='bull_volatile',(1,2,3),(3.2,2.0,1.2))]:
        x=v8.t20_intrabar_pyramid(data,mask,st,tr,cost_bps=cost_bps)
        streams[nm]=x['returns'][1:]
    defs={
      'trend_long':np.where(state=='trend_up',1.,0.),
      'recovery_half_long':np.where(state=='recovery',.5,0.),
      'range_mr_long':np.where((state=='range_chop')&mr,1.,0.),
      'bear_short':np.where(state=='bear_trend',-1.,0.),
      'panic_half_short':np.where(state=='panic',-.5,0.),
      'hold_long':np.ones(n),
      'sma200_long':v6.signal_sma200(data),
    }
    for nm,e in defs.items(): streams[nm]=v6.run_vector(data,e,cost_bps)[0]
    return state,streams


def conditional_stats(data,state,streams):
    # returns streams align with day 1..n-1, causal state at prior close aligns state[:-1]
    s_prev=state[:-1]
    out=[]
    for ename,r in streams.items():
        r=np.asarray(r,float)
        for st in sorted(set(state)):
            mask=s_prev==st
            if mask.sum()<20: continue
            rr=r[mask]
            sd=np.std(rr,ddof=1)
            out.append({'expert':ename,'state':st,'n':int(mask.sum()),'mean_daily':float(np.mean(rr)),
                        'ann_arith':float(np.mean(rr)*ANNUAL),'sharpe':float(np.mean(rr)/sd*math.sqrt(ANNUAL)) if sd>0 else 0.0,
                        'win_rate':float(np.mean(rr>0))})
    return out


def empirical_projection(data,state,horizons=(5,20,60)):
    c=np.asarray(data['close'],float); cur=state[-1]; out={'current_state':cur,'horizons':{}}
    for h in horizons:
        vals=[]
        for t in range(len(c)-h):
            if state[t]==cur and np.isfinite(c[t]) and c[t]>0: vals.append(c[t+h]/c[t]-1)
        a=np.asarray(vals,float)
        if len(a):
            out['horizons'][str(h)]={'n':int(len(a)),'median':float(np.median(a)),'mean':float(np.mean(a)),
                                     'p25':float(np.quantile(a,.25)),'p75':float(np.quantile(a,.75)),
                                     'p10':float(np.quantile(a,.10)),'p90':float(np.quantile(a,.90)),
                                     'prob_positive':float(np.mean(a>0))}
    return out


def alternating_candidate(q):
    if len(q)<5: return None
    q=list(q[-5:]); kinds=[p.kind for p in q]
    p=[x.price for x in q]
    if kinds==[-1,1,-1,1,-1] and p[2]>p[0] and p[3]>p[1] and p[4]>p[2]: return +1,q
    if kinds==[1,-1,1,-1,1] and p[2]<p[0] and p[3]<p[1] and p[4]<p[2]: return -1,q
    return None


def geometry_events(data,scale_name,atr_mult,min_pct,horizon,ratios):
    c,h,l=[np.asarray(data[k],float) for k in ('close','high','low')]; A=v6.atr(h,l,c,14)
    piv=v6.causal_zigzag(c,h,l,A,atr_mult,min_pct); states=v6.pivot_state_series(len(c),piv)
    events=[]; seen=set()
    for t,st in enumerate(states):
        if not st: continue
        # only when a new pivot becomes known today, so the same pattern is not repeated every day
        if st[-1].known_i!=t: continue
        cand=alternating_candidate(st)
        if not cand or not np.isfinite(A[t]): continue
        d,q=cand; key=tuple((p.pivot_i,p.known_i,p.kind) for p in q)
        if key in seen: continue
        seen.add(key)
        p0,p1,p2,p3,p4=q
        w1=abs(p1.price-p0.price); w3=abs(p3.price-p2.price); net03=abs(p3.price-p0.price)
        refs={'wave1':w1,'wave3':w3,'net_0_to_3':net03}
        invalid=(p4.price-.5*A[t]) if d>0 else (p4.price+.5*A[t])
        for ref_name,ref in refs.items():
            if ref<=EPS: continue
            for ratio in ratios:
                target=p4.price+d*ratio*ref
                # target must still be prospective after pivot confirmation
                if d>0 and target<=c[t]: continue
                if d<0 and target>=c[t]: continue
                exit_px=c[min(t+horizon,len(c)-1)]; outcome='timeout'; exit_i=min(t+horizon,len(c)-1)
                for j in range(t+1,min(len(c),t+horizon+1)):
                    target_hit=(h[j]>=target) if d>0 else (l[j]<=target)
                    inv_hit=(l[j]<=invalid) if d>0 else (h[j]>=invalid)
                    # ambiguous same bar: conservatively count invalidation first
                    if inv_hit:
                        exit_px=invalid; outcome='invalid'; exit_i=j; break
                    if target_hit:
                        exit_px=target; outcome='target'; exit_i=j; break
                signed_ret=d*(exit_px/c[t]-1)
                events.append({'scale':scale_name,'t':t,'direction':int(d),'ref':ref_name,'ratio':float(ratio),
                               'entry':float(c[t]),'target':float(target),'invalid':float(invalid),'outcome':outcome,
                               'signed_return':float(signed_ret),'bars':int(exit_i-t)})
    return events


def geometry_summary(data):
    ratios=[.4,.5,.6,.618,.7,.8,.9,1.0,1.1,1.2,1.3,1.4,1.5,1.6,1.618,1.7,1.8]
    scales=[('fast',1.5,.03),('medium',2.5,.05),('slow',4.0,.08)]
    all_events=[]
    for hz in (20,60):
      for nm,am,mp in scales:
        ev=geometry_events(data,nm,am,mp,hz,ratios)
        for x in ev: x['horizon']=hz
        all_events+=ev
    df=pd.DataFrame(all_events)
    if df.empty: return {'events':[],'summary':[],'named_comparison':[]}
    g=df.groupby(['horizon','scale','ref','ratio']).agg(n=('signed_return','size'),target_rate=('outcome',lambda x: float(np.mean(np.asarray(x)=='target'))),
        invalid_rate=('outcome',lambda x: float(np.mean(np.asarray(x)=='invalid'))),mean_signed_return=('signed_return','mean'),median_signed_return=('signed_return','median')).reset_index()
    named=[]
    for keys,sub in g.groupby(['horizon','scale','ref']):
        vals=sub['mean_signed_return'].to_numpy(); ratiosv=sub['ratio'].to_numpy()
        for r in (.618,1.0,1.618):
            z=sub[np.isclose(sub['ratio'],r)]
            if z.empty: continue
            val=float(z.iloc[0]['mean_signed_return']); pct=float(np.mean(vals<=val))
            named.append({'horizon':int(keys[0]),'scale':keys[1],'ref':keys[2],'ratio':r,'n':int(z.iloc[0]['n']),
                          'target_rate':float(z.iloc[0]['target_rate']),'mean_signed_return':val,'grid_percentile':pct,
                          'best_grid_ratio':float(ratiosv[np.argmax(vals)]),'best_grid_mean_signed_return':float(np.max(vals))})
    return {'events':all_events,'summary':g.to_dict('records'),'named_comparison':named}


def matrix_kelly_pair(btc,eth,cost_bps=25.0):
    # align on timestamps
    a=pd.DataFrame({'ts':btc['ts'],'btc':btc['close']}); b=pd.DataFrame({'ts':eth['ts'],'eth':eth['close']}); d=a.merge(b,on='ts',how='inner').sort_values('ts')
    lr=np.column_stack([np.r_[np.nan,np.diff(np.log(d.btc))],np.r_[np.nan,np.diff(np.log(d.eth))]])
    # build aligned signals from the original arrays by timestamp map
    sb=dict(zip(btc['ts'],v6.signal_sma200(btc))); se=dict(zip(eth['ts'],v6.signal_sma200(eth)))
    S=np.column_stack([[sb[int(t)] for t in d.ts],[se[int(t)] for t in d.ts]]).astype(bool)
    rows=[]
    for frac in (.25,.5,1.0):
        W,_=v8.matrix_kelly(lr,S,fraction=frac,gross_cap=3.0,per_asset_cap=2.0)
        r=np.zeros(len(d))
        for t in range(1,len(d)):
            gross=np.nansum(W[t-1]*lr[t]); tc=(cost_bps/10000.0)*np.sum(np.abs(W[t]-W[t-1])); r[t]=gross-tc
        rows.append({'fraction':frac,**v6.stats(r[1:]),'mean_gross_exposure':float(np.mean(np.sum(np.abs(W),axis=1))),
                     'max_gross_exposure':float(np.max(np.sum(np.abs(W),axis=1)))})
    return {'from_ts':int(d.ts.iloc[0]),'to_ts':int(d.ts.iloc[-1]),'n':int(len(d)),'rows':rows}


def current_geometry_levels(data):
    c,h,l=[np.asarray(data[k],float) for k in ('close','high','low')]; A=v6.atr(h,l,c,14); t=len(c)-1
    out=[]
    for nm,am,mp in [('fast',1.5,.03),('medium',2.5,.05),('slow',4.0,.08)]:
        piv=v6.causal_zigzag(c,h,l,A,am,mp); st=v6.pivot_state_series(len(c),piv)[-1]
        if len(st)<2: continue
        q=list(st[-5:]); last=q[-1]; prev=q[-2]; ref=abs(last.price-prev.price)
        d=-last.kind # last low => +1 projected direction, last high => -1
        levels={str(r):float(last.price+d*r*ref) for r in (.382,.5,.618,1.0,1.272,1.618)}
        cand=alternating_candidate(st)
        out.append({'scale':nm,'last_pivot_kind':'low' if last.kind<0 else 'high','pivot_price':float(last.price),'known_ts':int(data['ts'][last.known_i]),
                    'current_close':float(c[t]),'last_swing_size':float(ref),'candidate_elliott_pattern':bool(cand),'projected_levels':levels})
    return out


def run_asset(data,pair):
    state,features=classify_states(data)
    out={'pair':pair,'bars':len(data['close']),'from_ts':int(data['ts'][0]),'to_ts':int(data['ts'][-1]),
         'latest_close':float(data['close'][-1]),'latest_state':state[-1],
         'state_counts':{k:int(np.sum(state==k)) for k in np.unique(state)},
         'cost_runs':{},'projection':empirical_projection(data,state),'geometry':geometry_summary(data),'current_geometry':current_geometry_levels(data)}
    for cost in (6.0,25.0,85.0):
        st,streams=expert_streams(data,cost)
        longmix=mixture_returns(data,cost,False); dirmix=mixture_returns(data,cost,True)
        out['cost_runs'][str(int(cost))]={'long_only_mixture':longmix['stats'],'directional_mixture':dirmix['stats'],
            'experts':{k:v6.stats(v) for k,v in streams.items()},'conditional':conditional_stats(data,st,streams)}
    # Current causal state feature values
    out['latest_state_features']={k:(None if not np.isfinite(v[-1]) else float(v[-1])) for k,v in features.items()}
    return out


def main():
    db='/mnt/data/market_2026-10-03.sqlite'; outdir=Path('/mnt/data/APEX_v09_cross_ai')
    btc=v6.load_sqlite(db,'BTC-USD',1440); eth=v6.load_sqlite(db,'ETH-USD',1440)
    res={'meta':{'spec_sha256':'e3415de69d1ba2e56f6afeb71fd61be2feb7253b061b5cc1b61a60ffbf4b4707',
                 'db':Path(db).name,'research_only':True,'notes':['historical database is not an untouched holdout; prior APEX experiments used overlapping history','funding is not available across full history','macro Fed/equity series are not present in this sqlite']},
         'BTC-USD':run_asset(btc,'BTC-USD'),'ETH-USD':run_asset(eth,'ETH-USD')}
    res['matrix_kelly_25bps']=matrix_kelly_pair(btc,eth,25.0)
    (outdir/'historical_v09_results.json').write_text(json.dumps(res,indent=2))
    print(json.dumps({'BTC':{'state':res['BTC-USD']['latest_state'],'mix25':res['BTC-USD']['cost_runs']['25']['long_only_mixture']},
                      'ETH':{'state':res['ETH-USD']['latest_state'],'mix25':res['ETH-USD']['cost_runs']['25']['long_only_mixture']},
                      'matrix':res['matrix_kelly_25bps']['rows']},indent=2))

if __name__=='__main__': main()
