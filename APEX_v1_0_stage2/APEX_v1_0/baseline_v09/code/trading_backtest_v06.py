#!/usr/bin/env python3
"""APEX v0.6 research-only backtest batch.

Implements first falsifiable versions of:
  T11 Elliott soft-state / pivot grammar
  T12 Fibonacci conditional feature + randomized ratio placebo
  T13 Bill Williams exact-ish mechanical family
  T14 multitimeframe/choppiness trend filter
  T20 evidence-gated pyramiding
  T21 fractional Kelly allocator

No live orders. Signals are shifted one bar: information available at close t earns return t->t+1.
Transaction costs are charged on absolute change in exposure.

Input: APEX MarketStore SQLite schema with candles(source, pair, interval, ts, open, high, low, close, volume).
Example:
  python trading_backtest_v06.py --db state/market.sqlite --pair BTC-USD --interval 1440 --out results_btc.json
  python trading_backtest_v06.py --synthetic --out synthetic_smoke.json
"""
from __future__ import annotations
import argparse, json, math, sqlite3
from dataclasses import dataclass
from pathlib import Path
import numpy as np

DAY=86400
EPS=1e-12


def load_sqlite(db, pair, interval):
    con=sqlite3.connect(db)
    q=("SELECT ts, open, high, low, close, volume FROM candles "
       "WHERE source='coinbase' AND pair=? AND interval=? ORDER BY ts")
    rows=con.execute(q,(pair,interval)).fetchall()
    if not rows:
        raise SystemExit(f"no Coinbase candles for {pair} interval={interval} in {db}")
    a=np.asarray(rows,float)
    return dict(ts=a[:,0].astype(np.int64), open=a[:,1], high=a[:,2], low=a[:,3], close=a[:,4], volume=a[:,5])


def synthetic(n=4200, seed=20261003):
    """Regime-changing OHLC fixture. Only for code validation, never evidence."""
    rng=np.random.default_rng(seed)
    # persistent and mean-reverting regimes mixed, with jumps
    state=np.zeros(n,int)
    for t in range(1,n):
        if rng.random()<0.015: state[t]=rng.integers(0,3)
        else: state[t]=state[t-1]
    r=np.zeros(n)
    x=math.log(300.)
    for t in range(1,n):
        if state[t]==0: mu,phi,sig=0.0015,0.20,0.035
        elif state[t]==1: mu,phi,sig=-0.0008,0.05,0.045
        else: mu,phi,sig=0.0001,-0.35,0.025
        r[t]=mu+phi*r[t-1]+sig*rng.normal()
        if rng.random()<0.004: r[t]+=rng.normal(0,0.12)
    c=300*np.exp(np.cumsum(r))
    op=np.r_[c[0],c[:-1]]
    spread=np.abs(rng.normal(.018,.01,n))+0.002
    h=np.maximum(op,c)*(1+spread*rng.uniform(.3,1,n))
    l=np.minimum(op,c)*(1-spread*rng.uniform(.3,1,n))
    v=np.exp(rng.normal(18,1,n))
    ts=np.arange(n,dtype=np.int64)*DAY + 1451606400
    return dict(ts=ts,open=op,high=h,low=l,close=c,volume=v)


def sma(x,n):
    x=np.asarray(x,float); out=np.full(len(x),np.nan)
    if n<=0 or len(x)<n: return out
    cs=np.r_[0.,np.cumsum(x)]
    out[n-1:]=(cs[n:]-cs[:-n])/n
    return out


def smma(x,n):
    x=np.asarray(x,float); out=np.full(len(x),np.nan)
    if len(x)<n: return out
    out[n-1]=np.mean(x[:n])
    for i in range(n,len(x)): out[i]=(out[i-1]*(n-1)+x[i])/n
    return out


def tr(high,low,close):
    pc=np.r_[close[0],close[:-1]]
    return np.maximum(high-low,np.maximum(np.abs(high-pc),np.abs(low-pc)))


def atr(high,low,close,n=14): return smma(tr(high,low,close),n)


def rolling_std_returns(close,n=30,annual=365):
    lr=np.r_[np.nan,np.diff(np.log(close))]
    o=np.full(len(close),np.nan)
    for i in range(n,len(close)):
        w=lr[i-n+1:i+1]; o[i]=np.nanstd(w)*math.sqrt(annual)
    return o


def choppiness(high,low,close,n=14):
    T=tr(high,low,close); o=np.full(len(close),np.nan)
    for i in range(n-1,len(close)):
        hi=np.max(high[i-n+1:i+1]); lo=np.min(low[i-n+1:i+1])
        den=max(hi-lo,EPS)
        o[i]=100*math.log10(max(np.sum(T[i-n+1:i+1])/den,EPS))/math.log10(n)
    return o


@dataclass
class Pivot:
    pivot_i:int
    known_i:int
    price:float
    kind:int   # +1 high, -1 low


def causal_zigzag(close, high, low, atrv, atr_mult=2.5, min_pct=0.05):
    """Pivot becomes known only after a reversal. No future bars used in decisions.
    Threshold = max(min_pct*extreme_price, atr_mult*ATR[current bar]).
    """
    piv=[]
    mode=0 # 0 unset, +1 seeking high after low, -1 seeking low after high
    ext_i=0; ext_p=close[0]
    # seed direction after enough movement
    for i in range(1,len(close)):
        A=atrv[i] if np.isfinite(atrv[i]) else 0.0
        if mode==0:
            up=high[i]/max(ext_p,EPS)-1; dn=1-low[i]/max(ext_p,EPS)
            if up>=min_pct:
                piv.append(Pivot(ext_i,i,ext_p,-1)); mode=1; ext_i=i; ext_p=high[i]
            elif dn>=min_pct:
                piv.append(Pivot(ext_i,i,ext_p,+1)); mode=-1; ext_i=i; ext_p=low[i]
            else:
                # track neither aggressively; use close anchor
                if abs(close[i]/max(ext_p,EPS)-1)<min_pct/2: ext_i=i; ext_p=close[i]
            continue
        if mode==1:
            if high[i]>=ext_p: ext_i=i; ext_p=high[i]
            thresh=max(min_pct*ext_p, atr_mult*A)
            if ext_p-low[i]>=thresh:
                piv.append(Pivot(ext_i,i,ext_p,+1)); mode=-1; ext_i=i; ext_p=low[i]
        else:
            if low[i]<=ext_p: ext_i=i; ext_p=low[i]
            thresh=max(min_pct*ext_p, atr_mult*A)
            if high[i]-ext_p>=thresh:
                piv.append(Pivot(ext_i,i,ext_p,-1)); mode=1; ext_i=i; ext_p=high[i]
    return piv


def pivot_state_series(n,pivots):
    known=[[] for _ in range(n)]
    for p in pivots:
        if 0<=p.known_i<n: known[p.known_i].append(p)
    hist=[]; states=[]
    for i in range(n):
        hist.extend(known[i]); states.append(tuple(hist[-8:]))
    return states


def fib_proximity(x, anchors=(0.382,0.5,0.618), scale=.08):
    return math.exp(-min(abs(x-a) for a in anchors)/scale)


def elliott_wave4_score(state, fib_anchors=(0.382,0.5,0.618)):
    """Soft bullish L-H-L-H-L structure: completed wave 4, candidate wave 5 ahead.
    Returns score in [0,1], and component diagnostics. This is a research proxy, not canonical Elliott truth.
    """
    if len(state)<5: return 0.0,{}
    q=list(state[-5:])
    if [p.kind for p in q] != [-1,1,-1,1,-1]: return 0.0,{}
    p0,p1,p2,p3,p4=[p.price for p in q]
    if not (p2>p0 and p3>p1 and p4>p2): return 0.0,{}
    w1=p1-p0; w2=p1-p2; w3=p3-p2; w4=p3-p4
    if min(w1,w2,w3,w4)<=0: return 0.0,{}
    r2=w2/w1; r4=w4/w3; ext3=w3/w1
    # invalidation-ish: wave2 shouldn't fully retrace wave1; wave4 shouldn't overlap wave1 heavily
    structure=(0.15<r2<0.95) and (0.10<r4<0.80) and (p4>=p1*0.97)
    if not structure: return 0.0,{"r2":r2,"r4":r4,"ext3":ext3}
    f2=fib_proximity(r2,fib_anchors); f4=fib_proximity(r4,fib_anchors)
    f3=math.exp(-min(abs(ext3-a) for a in (1.0,1.272,1.618,2.0))/.22)
    # wave3 not shortest among w1/w3 and tentative w5 unknown -> only soft reward
    score=min(1.0, .30+.25*f2+.20*f4+.25*f3)
    return score,{"r2":r2,"r4":r4,"ext3":ext3}


def signal_elliott(data, fib_anchors=(0.382,0.5,0.618), threshold=.62, atr_mult=2.5, min_pct=.05):
    c,h,l=data['close'],data['high'],data['low']; A=atr(h,l,c,14)
    ps=causal_zigzag(c,h,l,A,atr_mult,min_pct); states=pivot_state_series(len(c),ps)
    s=np.zeros(len(c)); raw=np.zeros(len(c))
    for i,st in enumerate(states):
        sc,diag=elliott_wave4_score(st,fib_anchors); raw[i]=sc
        if sc>=threshold:
            # only while still above latest wave4 low and before price collapses back into wave1 origin area
            p4=st[-1].price; p1=st[-4].price
            if c[i]>=p4 and c[i]>=p1*.97: s[i]=1.0
    return s,raw,ps


def signal_williams(data):
    h,l,c=data['high'],data['low'],data['close']; med=(h+l)/2
    jaw,teeth,lips=smma(med,13),smma(med,8),smma(med,5)
    # Williams visual shifts translated causally: at t compare values computed 8/5/3 bars ago.
    J=np.r_[np.full(8,np.nan),jaw[:-8]]; T=np.r_[np.full(5,np.nan),teeth[:-5]]; L=np.r_[np.full(3,np.nan),lips[:-3]]
    ao=sma(med,5)-sma(med,34); ac=ao-sma(np.nan_to_num(ao,nan=0.0),5)
    # 5-bar fractal high at i-2 only known at i.
    last_frac=np.full(len(c),np.nan); lf=np.nan
    for i in range(4,len(c)):
        k=i-2
        if h[k]>h[k-1] and h[k]>h[k-2] and h[k]>=h[k+1] and h[k]>=h[k+2]: lf=h[k]
        last_frac[i]=lf
    sig=((L>T)&(T>J)&(ao>0)&(ac>0)&(c>last_frac)&np.isfinite(last_frac)).astype(float)
    return sig,{"jaw":J,"teeth":T,"lips":L,"ao":ao,"ac":ac,"fractal_high":last_frac}


def signal_chop_trend(data):
    h,l,c=data['high'],data['low'],data['close']; ma=sma(c,200); ch=choppiness(h,l,c,14)
    # use 38.2 as a prespecified Williams-style threshold, but compare controls later
    sig=((c>ma)&(ch<38.2)).astype(float)
    return sig,ch


def signal_sma200(data):
    c=data['close']; m=sma(c,200); return ((c>m)&np.isfinite(m)).astype(float)


def run_vector(data, exposure, cost_bps=85.0):
    c=data['close']; ret=np.r_[0.,c[1:]/c[:-1]-1]
    w=np.nan_to_num(np.asarray(exposure,float),nan=0.0,posinf=0.0,neginf=0.0)
    # exposure at close t earns t+1. Align output return at day t+1.
    gross=w[:-1]*ret[1:]
    turn=np.abs(np.diff(np.r_[0.,w]))[:-1]
    net=gross-turn*cost_bps/1e4
    return net,turn,w[:-1]


def pyramid_exposure(data, base_signal, atr_mult_step=1.0, stages=(0.5,1.0,1.5), trail_atr=2.5):
    """Anti-martingale: add only after favorable ATR movement; reset on base off or trailing stop.
    Daily-close approximation; no intra-bar liquidation modeling here.
    """
    c,h,l=data['close'],data['high'],data['low']; A=atr(h,l,c,14)
    out=np.zeros(len(c)); stage=0; add_ref=np.nan; peak=-np.inf
    for i in range(len(c)):
        if not base_signal[i] or not np.isfinite(A[i]):
            stage=0; add_ref=np.nan; peak=-np.inf; out[i]=0; continue
        if stage==0:
            stage=1; add_ref=c[i]; peak=c[i]
        else:
            peak=max(peak,c[i])
            if c[i] < peak-trail_atr*A[i]:
                stage=0; add_ref=np.nan; peak=-np.inf; out[i]=0; continue
            if stage<len(stages) and c[i] >= add_ref+atr_mult_step*A[i]:
                stage+=1; add_ref=c[i]
        out[i]=stages[stage-1] if stage else 0
    return out


def kelly_exposure(data, base_signal, fraction=.10, lookback=252, cap=1.0, shrink=.5):
    c=data['close']; ret=np.r_[0.,c[1:]/c[:-1]-1]
    # realized signal return uses yesterday's signal. At t estimate using only history <=t.
    strat=np.r_[0.,base_signal[:-1]*ret[1:]]
    out=np.zeros(len(c))
    for t in range(lookback,len(c)):
        x=strat[t-lookback+1:t+1]
        mu=np.mean(x); var=np.var(x,ddof=1)
        # conservative mean shrink + long-only Kelly cap
        f=max(0.0,min(cap, fraction*(shrink*mu/max(var,EPS))))
        out[t]=base_signal[t]*f
    return out


def vol_target_exposure(data, base_signal,target=.50,cap=1.0):
    rv=rolling_std_returns(data['close'],30); return base_signal*np.nan_to_num(np.minimum(cap,target/rv),nan=0.0)


def stats(net,turn=None,annual=365):
    r=np.asarray(net,float); r=r[np.isfinite(r)]
    if len(r)<2: return {}
    eq=np.cumprod(np.maximum(1+r,1e-9)); years=len(r)/annual
    peak=np.maximum.accumulate(eq); dd=1-eq/peak
    sd=np.std(r,ddof=1); neg=np.std(np.minimum(r,0),ddof=1)
    return {
      'days':int(len(r)), 'cagr':float(eq[-1]**(1/max(years,EPS))-1),
      'sharpe':float(np.mean(r)/sd*math.sqrt(annual)) if sd>0 else 0.0,
      'sortino':float(np.mean(r)/neg*math.sqrt(annual)) if neg>0 else 0.0,
      'max_drawdown':float(np.max(dd)), 'total_x':float(eq[-1]),
      'turnover_per_year':float(np.sum(turn)/(len(r)/annual)) if turn is not None else None,
      'win_day_rate':float(np.mean(r>0)), 'ann_vol':float(sd*math.sqrt(annual)),
    }


def period_stats(data, net, turn):
    ts=data['ts'][1:]
    cut=int(np.datetime64('2022-01-01').astype('datetime64[s]').astype(np.int64))
    res={'full':stats(net,turn)}
    for name,mask in [('pre_2022',ts<cut),('post_2022',ts>=cut)]:
        if mask.sum()>=100: res[name]=stats(net[mask],turn[mask])
    return res


def one(data,name,exposure,cost):
    net,turn,w=run_vector(data,exposure,cost)
    return {'name':name,'cost_bps':cost,'stats':period_stats(data,net,turn),
            'mean_exposure':float(np.mean(w)),'max_exposure':float(np.max(w)),
            'changes':int(np.sum(turn>1e-9))}


def batch(data,cost=85.0,seed=20261003):
    out={'meta':{'bars':len(data['close']),'from_ts':int(data['ts'][0]),'to_ts':int(data['ts'][-1]),
                 'cost_bps':cost,'seed':seed,'causal_signal_shift':'close t -> return t+1'},'runs':[],'controls':{}}
    hold=np.ones(len(data['close'])); sma200=signal_sma200(data)
    out['runs'] += [one(data,'hold',hold,cost),one(data,'sma200',sma200,cost)]

    ew,ewraw,pivs=signal_elliott(data)
    out['runs'].append(one(data,'T11_elliott_soft_wave4',ew,cost))
    out['meta']['elliott_confirmed_pivots']=len(pivs)

    # T12 named Fibonacci versus randomized anchors. Keep Elliott grammar otherwise identical.
    named=one(data,'T12_named_fibonacci',ew,cost); out['runs'].append(named)
    rng=np.random.default_rng(seed); plac=[]
    for j in range(50):
        anchors=tuple(sorted(rng.uniform(.20,.80,3)))
        sig,_,_=signal_elliott(data,fib_anchors=anchors)
        rr=one(data,f'T12_placebo_{j:02d}',sig,cost)
        plac.append({'anchors':anchors,'sharpe':rr['stats']['full'].get('sharpe',0.0),'cagr':rr['stats']['full'].get('cagr',0.0)})
    nsh=named['stats']['full']['sharpe']; pc=np.array([x['sharpe'] for x in plac])
    out['controls']['T12_fibonacci_placebo']={'n':len(plac),'named_sharpe':nsh,'placebo_mean_sharpe':float(pc.mean()),
      'placebo_sd_sharpe':float(pc.std(ddof=1)),'z':float((nsh-pc.mean())/max(pc.std(ddof=1),EPS)),
      'percentile':float(np.mean(pc<=nsh)),'placebos':plac}

    will,_=signal_williams(data); out['runs'].append(one(data,'T13_bill_williams',will,cost))
    chop,ch=signal_chop_trend(data); out['runs'].append(one(data,'T14_sma200_plus_choppiness38_2',chop,cost))
    # threshold controls (declared as controls, not parameter selection)
    for th in (30.,45.,55.):
        c=data['close']; sig=((c>sma(c,200))&(ch<th)).astype(float)
        out['runs'].append(one(data,f'T14_control_chop_{th:g}',sig,cost))

    pyr=pyramid_exposure(data,sma200); out['runs'].append(one(data,'T20_pyramid_sma200_0_5_1_1_5x',pyr,cost))
    vt=vol_target_exposure(data,sma200); out['runs'].append(one(data,'T21_control_voltarget50',vt,cost))
    for f in (.05,.10,.25):
        k=kelly_exposure(data,sma200,fraction=f,cap=1.0,shrink=.5)
        out['runs'].append(one(data,f'T21_fractional_kelly_{int(f*100):02d}pct',k,cost))

    # trial count includes every run + 50 Fibonacci placebos. Controls count because the research program saw them.
    out['meta']['trial_count_this_batch']=len(out['runs'])+50
    return out


def md_report(res):
    m=res['meta']; lines=["# APEX v0.6 backtest batch",'',f"Bars: {m['bars']} | cost: {m['cost_bps']} bps/turnover | trials counted: {m['trial_count_this_batch']}",
      '',"| Strategy | CAGR | Sharpe | Max DD | Turnover/yr | Mean exp | Max exp |","|---|---:|---:|---:|---:|---:|---:|"]
    for r in res['runs']:
        s=r['stats']['full']; lines.append(f"| {r['name']} | {s.get('cagr',0):.1%} | {s.get('sharpe',0):.2f} | {s.get('max_drawdown',0):.1%} | {s.get('turnover_per_year',0):.1f} | {r['mean_exposure']:.2f} | {r['max_exposure']:.2f} |")
    p=res['controls']['T12_fibonacci_placebo']; lines += ['', '## T12 Fibonacci placebo',
      f"Named-anchor Sharpe {p['named_sharpe']:.2f}; placebo mean {p['placebo_mean_sharpe']:.2f}; z {p['z']:+.2f}; percentile {p['percentile']:.1%}.",
      '', '> Synthetic mode validates code paths only. It is not market evidence.' if res.get('synthetic') else '']
    return '\n'.join(lines)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--db'); ap.add_argument('--pair',default='BTC-USD'); ap.add_argument('--interval',type=int,default=1440)
    ap.add_argument('--cost-bps',type=float,default=85.0); ap.add_argument('--out',default='backtest_v06.json'); ap.add_argument('--synthetic',action='store_true')
    a=ap.parse_args(); data=synthetic() if a.synthetic else load_sqlite(a.db,a.pair,a.interval)
    res=batch(data,a.cost_bps); res['synthetic']=bool(a.synthetic); res['meta']['pair']=a.pair; res['meta']['interval']=a.interval
    Path(a.out).write_text(json.dumps(res,indent=2))
    Path(a.out).with_suffix('.md').write_text(md_report(res))
    print(md_report(res))

if __name__=='__main__': main()
