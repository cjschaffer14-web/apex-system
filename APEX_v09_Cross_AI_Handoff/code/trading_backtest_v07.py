#!/usr/bin/env python3
"""APEX v0.7 research sweep.

Adds:
- higher-leverage anti-martingale pyramids
- stage-tightening ATR stop logic
- higher fractional-Kelly sweeps
- walk-forward MLP controls using generic vs fractal vs Fibonacci+fractal features

Synthetic fixture is for implementation validation only. No live trading.
"""
from __future__ import annotations
import json, math, argparse
from pathlib import Path
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.exceptions import ConvergenceWarning
import warnings
warnings.filterwarnings('ignore', category=ConvergenceWarning)

import trading_backtest_v06 as v6

EPS=1e-12


def pyramid_exposure_tightening(data, base_signal, atr_mult_step=1.0,
                                 stages=(1.0,2.0,3.0),
                                 trail_atrs=(3.0,2.0,1.25)):
    """Close-to-close research approximation.

    Adds only after favorable ATR movement. The trailing distance tightens as stage rises.
    A stop breach at close t removes exposure for t->t+1; it does NOT claim an intrabar stop fill.
    """
    if len(stages)!=len(trail_atrs):
        raise ValueError('stages and trail_atrs must have same length')
    c,h,l=data['close'],data['high'],data['low']
    A=v6.atr(h,l,c,14)
    out=np.zeros(len(c)); stage=0; add_ref=np.nan; peak=-np.inf
    stop=np.full(len(c),np.nan)
    for i in range(len(c)):
        if (not base_signal[i]) or (not np.isfinite(A[i])):
            stage=0; add_ref=np.nan; peak=-np.inf; out[i]=0.0; continue
        if stage==0:
            stage=1; add_ref=c[i]; peak=c[i]
        else:
            peak=max(peak,c[i])
            trail=trail_atrs[stage-1]
            stop_i=peak-trail*A[i]
            stop[i]=stop_i
            if c[i] < stop_i:
                stage=0; add_ref=np.nan; peak=-np.inf; out[i]=0.0; continue
            if stage<len(stages) and c[i] >= add_ref+atr_mult_step*A[i]:
                stage += 1
                add_ref=c[i]
                # recompute same-close stop using tighter new-stage distance
                stop[i]=peak-trail_atrs[stage-1]*A[i]
        out[i]=stages[stage-1] if stage else 0.0
    return out,stop


def leveraged_stats(data, exposure, cost_bps=85.0):
    net,turn,w=v6.run_vector(data,exposure,cost_bps)
    # simple close-to-close ruin diagnostic: leveraged daily net return <= -100%
    ruin=int(np.sum(net<=-1.0))
    s=v6.stats(net,turn)
    s['ruin_days']=ruin
    s['mean_exposure']=float(np.mean(w))
    s['max_exposure']=float(np.max(w))
    return s


def rolling_std(x,n):
    x=np.asarray(x,float); out=np.full(len(x),np.nan)
    for i in range(n-1,len(x)):
        out[i]=np.nanstd(x[i-n+1:i+1],ddof=1)
    return out


def causal_pivot_features(data, fib_anchors=(0.382,0.5,0.618)):
    c,h,l=data['close'],data['high'],data['low']
    A=v6.atr(h,l,c,14)
    piv=v6.causal_zigzag(c,h,l,A,atr_mult=2.5,min_pct=.05)
    states=v6.pivot_state_series(len(c),piv)
    # 9 features: fib proximity to last swing retracement; last 4 swing price/time ratios; direction/age
    out=np.full((len(c),9),np.nan)
    for i,st in enumerate(states):
        if len(st)<3: continue
        ps=list(st[-6:])
        pA,pB=ps[-2],ps[-1]
        swing=abs(pB.price-pA.price)
        if swing<=EPS: continue
        # Current retracement/extension from last confirmed swing, direction-aware
        if pB.kind==1: # last pivot high; downward retracement from preceding low->high
            x=(pB.price-c[i])/swing
        else: # last pivot low; upward retracement from preceding high->low
            x=(c[i]-pB.price)/swing
        fibprox=v6.fib_proximity(x,fib_anchors,scale=.08)
        dist_named=min(abs(x-a) for a in fib_anchors)
        age=(i-pB.known_i)/max(1, pB.known_i-pA.known_i)
        vals=[fibprox,dist_named,x,float(pB.kind),age]
        # last up to 4 swing magnitude ratios and one time ratio aggregate
        mags=[]; durs=[]
        for a,b in zip(ps[:-1],ps[1:]):
            mags.append(abs(b.price-a.price)/max(abs(a.price),EPS))
            durs.append(max(1,b.known_i-a.known_i))
        magrat=(mags[-1]/max(mags[-2],EPS)) if len(mags)>=2 else np.nan
        timerat=(durs[-1]/max(durs[-2],1)) if len(durs)>=2 else np.nan
        lastmag=mags[-1] if mags else np.nan
        lastdur=durs[-1] if durs else np.nan
        out[i]=vals+[magrat,timerat,lastmag,lastdur]
    return out


def feature_matrix(data, use_fractal=True, use_fib=True, fib_anchors=(0.382,0.5,0.618)):
    c,h,l,v=data['close'],data['high'],data['low'],data['volume']
    lr=np.r_[np.nan,np.diff(np.log(c))]
    ma200=v6.sma(c,200)
    atrp=v6.atr(h,l,c,14)/np.maximum(c,EPS)
    chop=v6.choppiness(h,l,c,14)
    vol20=rolling_std(lr,20)*math.sqrt(365)
    vol60=rolling_std(lr,60)*math.sqrt(365)
    logv=np.log1p(v)
    volz=(logv-v6.sma(logv,30))/np.maximum(rolling_std(logv,30),EPS)
    cols=[]; names=[]
    def add(a,n): cols.append(np.asarray(a,float)); names.append(n)
    for k in (1,2,5,10,20,60):
        r=np.full(len(c),np.nan); r[k:]=c[k:]/c[:-k]-1; add(r,f'ret_{k}')
    add(c/ma200-1,'sma200_dist'); add(atrp,'atr_pct'); add(chop,'chop'); add(vol20,'vol20'); add(vol60,'vol60'); add(volz,'volume_z')
    if use_fractal:
        # multiscale roughness/persistence features: signed return / path length and range / path length
        for n in (8,16,32,64):
            signed=np.full(len(c),np.nan); rough=np.full(len(c),np.nan); rangep=np.full(len(c),np.nan)
            for i in range(n,len(c)):
                rr=np.diff(np.log(c[i-n:i+1])); path=np.sum(np.abs(rr))
                signed[i]=np.sum(rr)/max(path,EPS)
                rangep[i]=(np.max(c[i-n:i+1])-np.min(c[i-n:i+1]))/max(c[i],EPS)
                rough[i]=path/max(abs(np.sum(rr)),1e-6)
            add(signed,f'fractal_eff_{n}'); add(rangep,f'range_{n}'); add(np.log1p(rough),f'rough_{n}')
    if use_fib:
        pf=causal_pivot_features(data,fib_anchors)
        for j,n in enumerate(['fib_prox','fib_dist','swing_x','pivot_kind','pivot_age','swing_mag_ratio','swing_time_ratio','last_swing_mag','last_swing_dur']):
            add(pf[:,j],n)
    X=np.column_stack(cols)
    return X,names


def walkforward_mlp_exposure(data, use_fractal=True, use_fib=True,
                             fib_anchors=(0.382,0.5,0.618), horizon=5,
                             train_window=900, min_train=550, retrain_every=180,
                             threshold=.55, seed=20261003):
    """Walk-forward MLP. Labels known only once their horizon has elapsed."""
    X,names=feature_matrix(data,use_fractal,use_fib,fib_anchors)
    c=data['close']; n=len(c)
    y=np.full(n,np.nan)
    y[:-horizon]=(c[horizon:]/c[:-horizon]-1 > 0).astype(float)
    valid=np.all(np.isfinite(X),axis=1)
    prob=np.full(n,np.nan); exposure=np.zeros(n)
    model=None; next_retrain=min_train
    for t in range(min_train,n):
        train_end=t-horizon
        if train_end<=0: continue
        if model is None or t>=next_retrain:
            lo=max(0,train_end-train_window+1)
            idx=np.arange(lo,train_end+1)
            idx=idx[valid[idx] & np.isfinite(y[idx])]
            if len(idx)<300: continue
            model=make_pipeline(StandardScaler(),MLPClassifier(hidden_layer_sizes=(12,6),activation='tanh',solver='adam',alpha=0.003,
                        batch_size=64,learning_rate_init=0.002,max_iter=90,early_stopping=True,n_iter_no_change=8,random_state=seed,shuffle=True))
            model.fit(X[idx],y[idx].astype(int))
            next_retrain=t+retrain_every
        if model is not None and valid[t]:
            prob[t]=model.predict_proba(X[t:t+1])[0,1]
            exposure[t]=1.0 if prob[t]>=threshold else 0.0
    return exposure,prob,names


def run_sweep(data,cost=85.0,seed=20261003):
    base=v6.signal_sma200(data)
    rows=[]
    def rec(name,exp):
        s=leveraged_stats(data,exp,cost)
        rows.append({'name':name,**s})

    # baseline pyramid from v0.6
    rec('T20_base_0.5_1_1.5_fixed2.5ATR',v6.pyramid_exposure(data,base,stages=(.5,1,1.5),trail_atr=2.5))
    # Higher-leverage fixed stop and tightening stop ladders
    for stages,trails,label in [
        ((1,2,3),(3.0,2.0,1.25),'1_2_3x_tight'),
        ((1,2.5,4),(3.0,1.85,1.05),'1_2.5_4x_tight'),
        ((1,3,5),(3.0,1.75,0.90),'1_3_5x_tight'),
        ((1,4,7),(3.0,1.50,0.75),'1_4_7x_tight_stress'),
    ]:
        rec(f'T20_{label}_fixed2.5ATR',v6.pyramid_exposure(data,base,stages=stages,trail_atr=2.5))
        e,_=pyramid_exposure_tightening(data,base,stages=stages,trail_atrs=trails)
        rec(f'T20_{label}',e)

    # Kelly: current 25% control and higher fractions. Raise cap so fractions can actually express.
    for f,cap in [(.25,1.0),(.50,2.0),(.75,2.5),(1.00,3.0),(1.50,4.0)]:
        e=v6.kelly_exposure(data,base,fraction=f,cap=cap,shrink=.5)
        rec(f'T21_kelly_fraction_{f:.2f}_cap{cap:g}',e)

    # Neural controls: generic, +fractal, +fractal+named Fib, +fractal+placebo Fib
    nnmeta={}
    variants=[
        ('NN_generic',False,False,(.382,.5,.618)),
        ('NN_fractal',True,False,(.382,.5,.618)),
        ('NN_fractal_namedFib',True,True,(.382,.5,.618)),
        ('NN_fractal_placeboFib',True,True,(.271,.447,.733)),
    ]
    for name,fr,fb,anchors in variants:
        e,p,names=walkforward_mlp_exposure(data,fr,fb,anchors,seed=seed)
        rec(name,e)
        nnmeta[name]={'n_features':len(names),'mean_probability':float(np.nanmean(p)),'signal_rate':float(np.mean(e>0)),'fib_anchors':anchors if fb else None}
    return {'meta':{'synthetic':True,'bars':len(data['close']),'cost_bps':cost,'seed':seed,
                    'warning':'Synthetic fixture validates behavior only; no market-performance inference.',
                    'stop_semantics':'tightening stop is close-confirmed and changes next-bar exposure; no claimed intrabar fill'},
            'runs':rows,'nn':nnmeta}


def report(res):
    lines=['# APEX v0.7 leverage / Kelly / neural-fractal sweep','',res['meta']['warning'],'',
           '| Strategy | CAGR | Sharpe | Max DD | Ann vol | Mean exp | Max exp | Ruin days |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in res['runs']:
        lines.append(f"| {r['name']} | {r['cagr']:.1%} | {r['sharpe']:.2f} | {r['max_drawdown']:.1%} | {r['ann_vol']:.1%} | {r['mean_exposure']:.2f} | {r['max_exposure']:.2f} | {r['ruin_days']} |")
    lines += ['', '## Stop semantics', '', res['meta']['stop_semantics'], '', '## Neural design',
              '', 'MLP target = positive 5-day forward return. Training is walk-forward; at day t, labels are included only through t-5. Retraining occurs every 90 bars using at most the prior 1,200 labeled bars. Named-Fibonacci features are compared against a fixed placebo-anchor triple.']
    return '\n'.join(lines)

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--out',default='synthetic_stress_v07.json'); ap.add_argument('--cost-bps',type=float,default=85.0); ap.add_argument('--seed',type=int,default=20261003)
    a=ap.parse_args(); data=v6.synthetic(seed=a.seed); res=run_sweep(data,a.cost_bps,a.seed)
    Path(a.out).write_text(json.dumps(res,indent=2)); Path(a.out).with_suffix('.md').write_text(report(res)); print(report(res))
