"""Paired chronological held-out episode evaluation, offline and order-free.
Input row: episode_id, birth_ns, outcome_ns, predictions by stage (asof_ns,
select, capture_probability, compute_seconds), per-stage realized outcome
(net_usd, turnover_usd, movement_cost_usd, capital_seconds, capture, failed,
risk_proxy, censored). Missing lanes stay unmeasured, never become zero alpha.
"""
import argparse,json,math
from pathlib import Path
from .baselines import STAGES
from .calibration import calibration

def evaluate(rows,train_end_ns,oos_start_ns):
    if train_end_ns>=oos_start_ns: raise ValueError('train/OOS overlap')
    rows=sorted(rows,key=lambda x:(x['birth_ns'],x['episode_id']))
    if len({r['episode_id'] for r in rows})!=len(rows): raise ValueError('duplicate episode IDs')
    training=[r for r in rows if r['outcome_ns'] is not None and r['outcome_ns']<=train_end_ns]
    held=[r for r in rows if r['birth_ns']>=oos_start_ns]
    result={'mode':'shadow','orders_authorized':False,'train_episodes':len(training),'oos_episodes':len(held),'train_end_ns':train_end_ns,'oos_start_ns':oos_start_ns,'stages':{}}
    for stage in STAGES:
        pnl=[]; probs=[]; labels=[]; ids=[]; censored=missing=0
        turnover=movement=capital=failed=risk=compute=0.
        observed_selected=0
        for r in held:
            p=r['predictions'].get(stage); o=r.get('outcomes',{}).get(stage)
            if p is None or o is None: missing+=1; continue
            if p['asof_ns']>r['birth_ns'] or p.get('training_end_ns',train_end_ns)>train_end_ns: raise ValueError('prediction leakage')
            if not math.isfinite(p['capture_probability']) or not 0<=p['capture_probability']<=1: raise ValueError('invalid capture probability')
            compute+=p['compute_seconds']
            if r['outcome_ns'] is None or o.get('censored',False): censored+=1; continue
            if r['outcome_ns']<r['birth_ns']: raise ValueError('outcome before birth')
            ids.append(r['episode_id'])
            if o.get('capture') is not None:
                probs.append(p['capture_probability']); labels.append(o['capture'])
            if p['select']:
                observed_selected+=1
                for k in ('net_usd','turnover_usd','movement_cost_usd','capital_seconds','failed','risk_proxy'):
                    if not math.isfinite(o[k]): raise ValueError('nonfinite outcome')
                pnl.append(o['net_usd']); turnover+=o['turnover_usd']; movement+=o['movement_cost_usd']; capital+=o['capital_seconds']; failed+=o['failed']; risk+=o['risk_proxy']
            else: pnl.append(0.)
        equity=peak=dd=0.
        for x in pnl: equity+=x; peak=max(peak,equity); dd=max(dd,peak-equity)
        cal=calibration(probs,labels)
        result['stages'][stage]={'episode_ids':ids,'held_out':True,'net_usd':sum(pnl) if ids else None,'turnover_usd':turnover,'movement_cost_usd':movement,'capital_seconds':capital,'capital_time_efficiency':sum(pnl)/capital if capital else None,'drawdown_usd':dd,'failure_rate':failed/observed_selected if observed_selected else None,'risk_proxy':risk,'compute_seconds':compute,'brier':cal['brier'],'calibration':cal,'censored':censored,'missing':missing,'status':'measured' if ids else 'insufficient_evidence'}
    return result

def main():
    p=argparse.ArgumentParser(); p.add_argument('episodes',type=Path); p.add_argument('--train-end-ns',type=int,required=True); p.add_argument('--oos-start-ns',type=int,required=True); p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(); rows=[json.loads(x) for x in a.episodes.read_text().splitlines() if x.strip()]
    a.out.write_text(json.dumps(evaluate(rows,a.train_end_ns,a.oos_start_ns),indent=2,allow_nan=False))
if __name__=='__main__': main()
