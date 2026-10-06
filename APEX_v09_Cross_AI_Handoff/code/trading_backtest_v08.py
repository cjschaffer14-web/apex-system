#!/usr/bin/env python3
"""APEX v0.8 research backtester.

Focus:
- Event-driven (daily OHLC) pyramiding with causal, stage-tightening stops.
- Fixed-fractional, rolling continuous Kelly, and regularized Matrix Kelly.
- Multiple causal fractal/Elliott interpretations as competing analysis features.
- Walk-forward multi-output neural analysis model (return / excursion / volatility targets).
- Strategy-as-state portfolio layer: bull pyramid / trend / defensive / mean-reversion complements.

Research only. No live execution.
"""
from __future__ import annotations
import argparse, json, math, warnings
from pathlib import Path
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.exceptions import ConvergenceWarning
warnings.filterwarnings("ignore", category=ConvergenceWarning)

import trading_backtest_v06 as v6
import trading_backtest_v07 as v7

EPS=1e-12
ANNUAL=365


def rolling_mean(x,n): return v6.sma(np.asarray(x,float),n)

def rolling_std(x,n):
    x=np.asarray(x,float); o=np.full(len(x),np.nan)
    for i in range(n-1,len(x)):
        o[i]=np.nanstd(x[i-n+1:i+1],ddof=1)
    return o


def strict_bull_regime(data):
    """Price-only bull proxy, intentionally not called a macro regime.
    Conditions are all known at the close: close>SMA200, SMA50>SMA200,
    positive 90d momentum, and 30d annualized vol < 120%.
    """
    c=data['close']
    m50=v6.sma(c,50); m200=v6.sma(c,200)
    mom90=np.full(len(c),np.nan); mom90[90:]=c[90:]/c[:-90]-1
    vol30=v6.rolling_std_returns(c,30,ANNUAL)
    return np.isfinite(m200)&np.isfinite(m50)&np.isfinite(mom90)&np.isfinite(vol30)&(c>m200)&(m50>m200)&(mom90>0)&(vol30<1.20)


def t20_intrabar_pyramid(data, regime=None, stages=(1.0,2.0,3.0),
                         trail_atrs=(3.0,2.0,1.25), add_atr=1.0,
                         cost_bps=25.0):
    """Daily OHLC event simulation with causal stage-tightening stops.

    Signal at close t-1 determines target stage at open t.
    Stage additions are evaluated using close t-1 and ATR t-1, so there is no
    same-bar lookahead. Stops for day t use information frozen at t-1.

    Conservative same-bar rule: today's high cannot tighten today's stop because
    high/low ordering is unknown. Today's high updates the trailing reference only
    for tomorrow. Gap through a stop exits at the opening price; otherwise a low
    touching the stop exits at the stop. After stop-out, the strategy remains cash
    until a fresh regime entry on a later open.

    This is materially more realistic than close-confirmed trailing stops, but it
    still does not model exchange liquidation tiers, funding, spread or intraday paths.
    """
    if len(stages)!=len(trail_atrs): raise ValueError('stages/trail_atrs mismatch')
    n=len(data['close']); o,h,l,c=[np.asarray(data[k],float) for k in ('open','high','low','close')]
    A=v6.atr(h,l,c,14)
    if regime is None: regime=v6.signal_sma200(data)
    regime=np.asarray(regime,bool)
    ret=np.zeros(n); exp=np.zeros(n); stop_series=np.full(n,np.nan); stage_series=np.zeros(n,int)
    stage=0; add_ref=np.nan; peak=np.nan; stop=np.nan
    fee=cost_bps/10000.0
    prev_close=c[0]
    for t in range(1,n):
        sig_prev=bool(regime[t-1]) and np.isfinite(A[t-1])
        # Exit regime at today's open.
        if not sig_prev:
            if stage>0:
                # held overnight from previous close to today's open, then exit.
                ret[t]+=stages[stage-1]*(o[t]/prev_close-1)-fee*stages[stage-1]
            stage=0; add_ref=np.nan; peak=np.nan; stop=np.nan
            prev_close=c[t]
            continue

        # Fresh entry or planned add happens at today's open based only on t-1 data.
        old_stage=stage
        if stage==0:
            stage=1; add_ref=c[t-1]; peak=h[t-1]
        else:
            # overnight PnL for carried exposure before any open adjustment
            ret[t]+=stages[stage-1]*(o[t]/prev_close-1)
            if stage<len(stages) and c[t-1] >= add_ref + add_atr*A[t-1]:
                stage+=1; add_ref=c[t-1]
        if stage!=old_stage:
            old_exp=stages[old_stage-1] if old_stage else 0.0
            new_exp=stages[stage-1]
            ret[t]-=fee*abs(new_exp-old_exp)

        # stop frozen from prior info, tightened immediately if stage rose at open
        if np.isfinite(peak):
            stop=max(stop if np.isfinite(stop) else -np.inf, peak-trail_atrs[stage-1]*A[t-1])
        stop_series[t]=stop; stage_series[t]=stage; exp[t]=stages[stage-1]

        # Intraday stop. If open gaps through stop, fill at open.
        if np.isfinite(stop) and o[t] <= stop:
            # exposure started/carry at open; no intraday directional PnL after open
            ret[t]-=fee*stages[stage-1]
            stage=0; exp[t]=0; stage_series[t]=0; add_ref=np.nan; peak=np.nan; stop=np.nan
            prev_close=c[t]
            continue
        if np.isfinite(stop) and l[t] <= stop:
            ret[t]+=stages[stage-1]*(stop/o[t]-1)
            ret[t]-=fee*stages[stage-1]
            stage=0; exp[t]=0; stage_series[t]=0; add_ref=np.nan; peak=np.nan; stop=np.nan
            prev_close=c[t]
            continue

        # Survived day: open->close pnl, update peak for TOMORROW only.
        ret[t]+=stages[stage-1]*(c[t]/o[t]-1)
        peak=max(peak,h[t]) if np.isfinite(peak) else h[t]
        prev_close=c[t]
    return {'returns':ret,'exposure':exp,'stages':stage_series,'stop':stop_series}


def kelly_fixed_fractional(signal, fraction=.5, cap=1.0):
    return np.clip(np.asarray(signal,float)*fraction,0,cap)


def kelly_continuous(data, signal=None, fraction=.5, lookback=252,
                     shrink_mu=.35, variance_floor=1e-5, cap=2.0):
    """Rolling f*=mu/sigma^2 with conservative mean shrinkage and cap."""
    c=np.asarray(data['close'],float); lr=np.r_[np.nan,np.diff(np.log(c))]
    if signal is None: signal=np.ones(len(c),bool)
    out=np.zeros(len(c)); raw=np.full(len(c),np.nan)
    for t in range(lookback,len(c)):
        w=lr[t-lookback+1:t+1]; w=w[np.isfinite(w)]
        if len(w)<lookback*.8 or not signal[t]: continue
        mu=np.mean(w)*shrink_mu
        var=max(np.var(w,ddof=1),variance_floor/ANNUAL)
        f=max(0.0,mu/var)
        raw[t]=f
        out[t]=min(cap,fraction*f)
    return out,raw


def matrix_kelly(returns, signal=None, fraction=.5, lookback=252,
                 ridge=0.20, shrink_mu=.35, gross_cap=2.0, per_asset_cap=1.5):
    """Regularized multi-asset Kelly: f = Sigma^-1 mu.

    Sigma is shrunk toward its diagonal: (1-ridge)S + ridge*diag(S).
    Pseudoinverse is used, then long-only clipping and a gross exposure cap.
    This is deliberately conservative; negative weights belong in a separately
    tested long/short strategy family rather than leaking into a sizing module.
    """
    R=np.asarray(returns,float); n,m=R.shape
    if signal is None: signal=np.ones((n,m),bool)
    W=np.zeros((n,m)); raw=np.full((n,m),np.nan)
    for t in range(lookback,n):
        x=R[t-lookback+1:t+1]
        ok=np.all(np.isfinite(x),axis=1); x=x[ok]
        if len(x)<lookback*.8: continue
        mu=np.mean(x,axis=0)*shrink_mu
        S=np.cov(x,rowvar=False)
        D=np.diag(np.diag(S))
        Sreg=(1-ridge)*S+ridge*D + np.eye(m)*1e-8
        f=np.linalg.pinv(Sreg)@mu
        raw[t]=f
        f=np.where(signal[t],np.maximum(f,0),0)
        w=np.minimum(per_asset_cap,fraction*f)
        gross=np.sum(np.abs(w))
        if gross>gross_cap: w*=gross_cap/gross
        W[t]=w
    return W,raw


def wave_features_multi(data):
    """Competing causal wave/fractal interpretations, no single Elliott ontology.

    Families:
      A: fast zigzag (1.5 ATR, 3%) -- micro swing grammar
      B: medium zigzag (2.5 ATR, 5%) -- v0.6 canonical proxy
      C: slow zigzag (4 ATR, 8%) -- macro swing grammar
    Each family emits geometry rather than a hindsight wave number.
    """
    c,h,l=[np.asarray(data[k],float) for k in ('close','high','low')]
    A=v6.atr(h,l,c,14); n=len(c)
    specs=[('fast',1.5,.03),('medium',2.5,.05),('slow',4.0,.08)]
    feats=[]; names=[]
    for nm,am,mp in specs:
        piv=v6.causal_zigzag(c,h,l,A,atr_mult=am,min_pct=mp)
        states=v6.pivot_state_series(n,piv)
        F=np.full((n,10),np.nan)
        for t,s in enumerate(states):
            if len(s)<3: continue
            q=list(s[-7:]); last=q[-1]; prev=q[-2]
            swing=abs(last.price-prev.price)
            if swing<=EPS: continue
            x=(last.price-c[t])/swing if last.kind==1 else (c[t]-last.price)/swing
            mags=[]; durs=[]
            for a,b in zip(q[:-1],q[1:]):
                mags.append(abs(b.price-a.price)/max(abs(a.price),EPS)); durs.append(max(1,b.known_i-a.known_i))
            mag_ratio=mags[-1]/max(mags[-2],EPS) if len(mags)>=2 else np.nan
            time_ratio=durs[-1]/max(durs[-2],1) if len(durs)>=2 else np.nan
            # alternating impulse score from last 5 or 6 causal confirmed pivots
            impulse=0.; correction=0.; symmetry=0.
            if len(q)>=5:
                kinds=[p.kind for p in q[-5:]]
                prices=[p.price for p in q[-5:]]
                if kinds==[-1,1,-1,1,-1] and prices[2]>prices[0] and prices[3]>prices[1]: impulse=1.
                if kinds==[1,-1,1,-1,1] and prices[2]<prices[0] and prices[3]<prices[1]: impulse=-1.
            if len(q)>=4:
                m1=abs(q[-3].price-q[-4].price); m2=abs(q[-2].price-q[-3].price); m3=abs(q[-1].price-q[-2].price)
                symmetry=math.exp(-abs(math.log(max(m3,EPS)/max(m1,EPS))))
                correction=min(2.0,m2/max(m1,EPS))
            fib_dist=min(abs(x-a) for a in (.236,.382,.5,.618,.786,1.,1.272,1.618))
            fib_ext=min(abs(x-a) for a in (1.0,1.272,1.618,2.0,2.618))
            age=(t-last.known_i)/max(1,last.known_i-prev.known_i)
            F[t]=[x,fib_dist,fib_ext,float(last.kind),age,mag_ratio,time_ratio,impulse,correction,symmetry]
        feats.append(F)
        names += [f'{nm}_{x}' for x in ['swing_x','fib_dist','fib_ext','pivot_kind','pivot_age','mag_ratio','time_ratio','impulse','correction','symmetry']]
    return np.column_stack(feats),names


def analysis_feature_matrix(data, placebo=False):
    X0,n0=v7.feature_matrix(data,use_fractal=True,use_fib=False)
    W,nw=wave_features_multi(data)
    c=np.asarray(data['close'],float)
    # explicit named vs randomized ratio channels; randomized ratios are controls, not labels.
    fib=np.full((len(c),4),np.nan)
    A=v6.atr(data['high'],data['low'],c,14)
    piv=v6.causal_zigzag(c,data['high'],data['low'],A,2.5,.05)
    st=v6.pivot_state_series(len(c),piv)
    anchors=(.271,.447,.733,1.391,1.811) if placebo else (.382,.5,.618,1.272,1.618)
    for t,s in enumerate(st):
        if len(s)<2: continue
        a,b=s[-2],s[-1]; sw=abs(b.price-a.price)
        if sw<=EPS: continue
        x=(b.price-c[t])/sw if b.kind==1 else (c[t]-b.price)/sw
        ds=np.array([abs(x-z) for z in anchors])
        fib[t]=[np.min(ds),x,float(np.argmin(ds)),math.exp(-np.min(ds)/.08)]
    return np.column_stack([X0,W,fib]), n0+nw+['ratio_min_dist','ratio_x','ratio_nearest_idx','ratio_proximity']


def make_analysis_targets(data,h=20):
    c,hp,lp=[np.asarray(data[k],float) for k in ('close','high','low')]; n=len(c)
    Y=np.full((n,5),np.nan)
    for t in range(n-h):
        r5=c[min(t+5,n-1)]/c[t]-1
        r20=c[t+h]/c[t]-1
        mfe=np.max(hp[t+1:t+h+1])/c[t]-1
        mae=np.min(lp[t+1:t+h+1])/c[t]-1
        rr=np.diff(np.log(c[t:t+h+1])); rv=np.std(rr,ddof=1)*math.sqrt(ANNUAL)
        Y[t]=[r5,r20,mfe,mae,rv]
    return Y


def walkforward_analysis_net(data, placebo=False, horizon=20, train_window=1200,
                             min_train=650, retrain_every=180, seed=20261003):
    """Multi-output walk-forward neural analysis model.

    Predicts 5d return, 20d return, 20d MFE, 20d MAE and 20d realized vol.
    A training row is admitted only once the entire 20-day label window is historical.
    """
    X,names=analysis_feature_matrix(data,placebo=placebo); Y=make_analysis_targets(data,horizon)
    n=len(X); pred=np.full_like(Y,np.nan); exposure=np.zeros(n)
    valid=np.all(np.isfinite(X),axis=1)&np.all(np.isfinite(Y),axis=1)
    model=None; next_retrain=min_train
    for t in range(min_train,n):
        train_end=t-horizon
        if train_end<0: continue
        if model is None or t>=next_retrain:
            lo=max(0,train_end-train_window+1); idx=np.arange(lo,train_end+1); idx=idx[valid[idx]]
            if len(idx)<350: continue
            model=make_pipeline(StandardScaler(),MLPRegressor(hidden_layer_sizes=(20,10),activation='tanh',alpha=.01,
                batch_size=64,learning_rate_init=.001,max_iter=100,early_stopping=True,n_iter_no_change=12,
                random_state=seed,shuffle=True))
            model.fit(X[idx],Y[idx]); next_retrain=t+retrain_every
        if model is not None and np.all(np.isfinite(X[t])):
            p=model.predict(X[t:t+1])[0]; pred[t]=p
            r5,r20,mfe,mae,rv=p
            # analysis-aware action: positive short+medium expected return and acceptable predicted downside.
            score=(r5+0.35*r20)/max(rv/math.sqrt(ANNUAL/5),.01)
            exposure[t]=1.0 if (score>.20 and mae>-.12 and mfe>abs(mae)*.8) else 0.0
    return exposure,pred,names


def complementary_mean_reversion(data):
    c=np.asarray(data['close'],float); ma=v6.sma(c,20); sd=rolling_std(c/np.maximum(ma,EPS)-1,20)
    z=(c/np.maximum(ma,EPS)-1)/np.maximum(sd,EPS)
    # only when below SMA200 or choppy: complement to trend/pyramid state
    chop=v6.choppiness(data['high'],data['low'],c,14); m200=v6.sma(c,200)
    return np.isfinite(z)&np.isfinite(chop)&((c<m200)|(chop>55))&(z<-1.5)


def strategy_state_portfolio(data,cost_bps=25):
    """Discrete expert/state layer. Uses causal price-defined states only.
    Macro features can replace/augment the regime router later without changing expert contracts.
    """
    bull=strict_bull_regime(data)
    pyr=t20_intrabar_pyramid(data,bull,stages=(1,2,3.5),trail_atrs=(3.2,2.0,1.1),cost_bps=cost_bps)
    trend=v6.signal_sma200(data).astype(float)
    mr=complementary_mean_reversion(data).astype(float)
    chop=v6.choppiness(data['high'],data['low'],data['close'],14)
    c=data['close']; m200=v6.sma(c,200)
    # Router: bull->pyramid; non-bull trend->1x trend; choppy/bear oversold->MR; else cash.
    state=np.array(['cash']*len(c),dtype=object); exp=np.zeros(len(c))
    for t in range(len(c)):
        if bull[t]: state[t]='bull_pyramid'; exp[t]=pyr['exposure'][t]
        elif np.isfinite(m200[t]) and c[t]>m200[t] and (not np.isfinite(chop[t]) or chop[t]<55): state[t]='trend'; exp[t]=trend[t]
        elif mr[t]>0: state[t]='mean_reversion'; exp[t]=1.0
        else: state[t]='cash'; exp[t]=0.0
    # vector return for router (separate from pyr's event-return semantics). Kept only as router prototype.
    net,turn,w=v6.run_vector(data,exp,cost_bps)
    return {'state':state,'exposure':exp,'returns':net,'turnover':turn,'pyramid_event_returns':pyr['returns']}


def stats_from_returns(r): return v6.stats(np.asarray(r,float))


def paired_synthetic(n=3200,seed=20261003):
    btc=v6.synthetic(n,seed); rng=np.random.default_rng(seed+1)
    br=np.r_[0,np.diff(np.log(btc['close']))]
    er=.72*br+rng.normal(.00015,.025,n)
    ec=120*np.exp(np.cumsum(er)); eo=np.r_[ec[0],ec[:-1]]
    spr=np.abs(rng.normal(.022,.012,n))+.003
    eh=np.maximum(eo,ec)*(1+spr*rng.uniform(.3,1,n)); el=np.minimum(eo,ec)*(1-spr*rng.uniform(.3,1,n))
    ev=np.exp(rng.normal(17.5,1.1,n))
    eth=dict(ts=btc['ts'].copy(),open=eo,high=eh,low=el,close=ec,volume=ev)
    return btc,eth


def run_validation(cost_bps=25,seed=20261003):
    btc,eth=paired_synthetic(seed=seed)
    rows=[]
    def add(name,r,extra=None):
        s=stats_from_returns(r); rows.append({'name':name,**s,**(extra or {})})
    # T20 ladders: intrabar tightening + strict bull proxy
    bull=strict_bull_regime(btc)
    for st,tr in [((1,2,3),(3.2,2.0,1.2)),((1,2.5,4),(3.2,1.8,1.0)),((1,3,5),(3.2,1.6,.85)),((1,4,7),(3.2,1.4,.70))]:
        x=t20_intrabar_pyramid(btc,bull,st,tr,cost_bps=cost_bps)
        add('T20_intrabar_'+('_'.join(map(str,st))),x['returns'],{'max_exposure':max(st),'stop':'stage_tightening','bull_gate':'strict_price_proxy'})
    # Single asset Kelly
    sig=v6.signal_sma200(btc)
    for frac,cap in [(.25,1),(.5,2),(1,3),(1.5,4)]:
        w,_=kelly_continuous(btc,sig,fraction=frac,cap=cap); net,_,_=v6.run_vector(btc,w,cost_bps); add(f'T21_cont_kelly_{frac:g}',net,{'max_exposure':cap})
    for f in [.25,.5,.75,1.0]:
        w=kelly_fixed_fractional(sig,fraction=f,cap=1); net,_,_=v6.run_vector(btc,w,cost_bps); add(f'T21_fixed_fraction_{f:g}',net)
    # Matrix Kelly on BTC+ETH close returns
    R=np.column_stack([np.r_[np.nan,np.diff(np.log(btc['close']))],np.r_[np.nan,np.diff(np.log(eth['close']))]])
    S=np.column_stack([v6.signal_sma200(btc),v6.signal_sma200(eth)])
    for frac in [.25,.5,1.0]:
        W,_=matrix_kelly(R,S,fraction=frac,gross_cap=3.0,per_asset_cap=2.0)
        # next-day vector return + turnover cost
        rr=np.zeros(len(R));
        for t in range(1,len(R)):
            gross=np.nansum(W[t-1]*R[t]); tc=(cost_bps/10000)*np.sum(np.abs(W[t]-W[t-1])); rr[t]=gross-tc
        add(f'T21_matrix_kelly_{frac:g}',rr,{'mean_gross_exposure':float(np.mean(np.sum(np.abs(W),axis=1)))})
    # Neural analysis: named ratios vs placebo ratios
    for placebo in (False,True):
        e,p,nm=walkforward_analysis_net(btc,placebo=placebo,seed=seed)
        net,_,_=v6.run_vector(btc,e,cost_bps)
        valid=np.isfinite(p[:,0])
        mse=float(np.mean((p[valid,0]-make_analysis_targets(btc)[valid,0])**2)) if np.any(valid) else np.nan
        add('NN_analysis_placeboFib' if placebo else 'NN_analysis_namedFib',net,{'features':len(nm),'pred_r5_mse':mse,'signal_rate':float(np.mean(e>0))})
    # Strategy state router
    ss=strategy_state_portfolio(btc,cost_bps); add('STATE_router_vector',ss['returns'],{'states':{k:int(np.sum(ss['state']==k)) for k in np.unique(ss['state'])}})
    return {'meta':{'synthetic':True,'bars':len(btc['close']),'cost_bps':cost_bps,'seed':seed,
                    'purpose':'mechanics/leakage/stability validation only; not evidence of market alpha'},'runs':rows}



def load_csv(path):
    import csv
    rows=[]
    with open(path,newline='') as f:
        rd=csv.DictReader(f)
        for r in rd:
            # tolerate Date/date and Yahoo/HF column names
            try:
                rows.append((r.get('Date') or r.get('date'), float(r['Open']), float(r['High']), float(r['Low']), float(r['Close']), float(r.get('Volume',0) or 0)))
            except Exception:
                continue
    if not rows: raise SystemExit(f'no usable OHLC rows in {path}')
    import datetime as dt
    ts=[]
    for d,*_ in rows:
        try: ts.append(int(dt.datetime.fromisoformat(d[:10]).replace(tzinfo=dt.timezone.utc).timestamp()))
        except Exception: ts.append(len(ts)*86400)
    a=np.asarray([x[1:] for x in rows],float)
    return dict(ts=np.asarray(ts,dtype=np.int64),open=a[:,0],high=a[:,1],low=a[:,2],close=a[:,3],volume=a[:,4])

def run_real_single(data,cost_bps=25,seed=20261003):
    rows=[]
    def add(name,r,extra=None): rows.append({'name':name,**stats_from_returns(r),**(extra or {})})
    bull=strict_bull_regime(data)
    for st,tr in [((1,2,3),(3.2,2.0,1.2)),((1,2.5,4),(3.2,1.8,1.0)),((1,3,5),(3.2,1.6,.85)),((1,4,7),(3.2,1.4,.70))]:
        x=t20_intrabar_pyramid(data,bull,st,tr,cost_bps=cost_bps); add('T20_intrabar_'+('_'.join(map(str,st))),x['returns'],{'max_exposure':max(st)})
    sig=v6.signal_sma200(data)
    for frac,cap in [(.25,1),(.5,2),(1,3),(1.5,4)]:
        w,_=kelly_continuous(data,sig,fraction=frac,cap=cap); net,_,_=v6.run_vector(data,w,cost_bps); add(f'T21_cont_kelly_{frac:g}',net,{'max_exposure':cap})
    # Only attempt neural analysis if enough bars for a legitimate walk-forward window.
    if len(data['close'])>=900:
        for placebo in (False,True):
            e,p,nm=walkforward_analysis_net(data,placebo=placebo,seed=seed); net,_,_=v6.run_vector(data,e,cost_bps)
            add('NN_analysis_placeboFib' if placebo else 'NN_analysis_namedFib',net,{'features':len(nm),'signal_rate':float(np.mean(e>0))})
    ss=strategy_state_portfolio(data,cost_bps); add('STATE_router_vector',ss['returns'],{'states':{k:int(np.sum(ss['state']==k)) for k in np.unique(ss['state'])}})
    return {'meta':{'synthetic':False,'bars':len(data['close']),'cost_bps':cost_bps,'from_ts':int(data['ts'][0]),'to_ts':int(data['ts'][-1])},'runs':rows}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--synthetic',action='store_true'); ap.add_argument('--db'); ap.add_argument('--csv'); ap.add_argument('--pair',default='BTC-USD'); ap.add_argument('--interval',type=int,default=1440); ap.add_argument('--out',default='v08_validation.json'); ap.add_argument('--cost-bps',type=float,default=25); args=ap.parse_args()
    if args.synthetic: out=run_validation(args.cost_bps)
    elif args.db: out=run_real_single(v6.load_sqlite(args.db,args.pair,args.interval),args.cost_bps)
    elif args.csv: out=run_real_single(load_csv(args.csv),args.cost_bps)
    else: raise SystemExit('use --synthetic, --db MARKET.sqlite, or --csv OHLC.csv')
    Path(args.out).write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
