"""Offline F1 admission audit on existing recorded books; no outcomes invented.
Per-symbol timestamps reconstructed from the original recording. Existing depth
repair retained, checksum verification absent, shadow measurement only.
"""
import argparse,json,time,hashlib,bisect
from decimal import Decimal
from pathlib import Path
from ..core import best_cycle
from ..replay import load,books_from,KCYCLES,V,SYMS

def audit(path,fee=.0026,size=1000,max_age_ms=2000):
    started=time.perf_counter(); updates={s:[] for s in SYMS}; messages=0
    with path.open() as f:
        for line in f:
            ts,_,raw=line.partition('\t'); r={'t':int(ts),'m':json.loads(raw)}; messages+=1
            if r['m'].get('channel')=='book':
                for d in r['m']['data']:
                    if d['symbol'] in updates: updates[d['symbol']].append(r['t'])
    tl=load(str(path)); decisions=stale=invalid=positive=0; maximum=None; last=-10**30
    for t,st in zip(tl.t,tl.state):
        if t-last<100000000: continue
        last=t; books=books_from(st,t); bad=False
        for sym in SYMS:
            i=bisect.bisect_right(updates[sym],t)-1
            if i<0: bad=True; break
            b=books[V,sym]; b.received_ns=updates[sym][i]
            if t-b.received_ns>max_age_ms*1e6: bad=True
        if bad: stale+=1; continue
        if any(not b.bids or not b.asks or b.bids[0].price>=b.asks[0].price for b in books.values()): invalid+=1; continue
        decisions+=1
        r,_=best_cycle(books,KCYCLES,Decimal(str(size)),{V:Decimal(str(fee))},now_ns=t,max_age_ms=max_age_ms)
        if r is not None:
            net=float(r.profit_usd); maximum=net if maximum is None else max(maximum,net); positive+=int(net>0)
    return {'mode':'shadow_offline_admission_audit','orders_authorized':False,'source':str(path),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'messages':messages,'eligible_decisions':decisions,'stale_decisions_rejected':stale,'invalid_decisions_rejected':invalid,'positive_F1_decisions':positive,'max_F1_usd':maximum,'fee_per_leg':fee,'size_usd':size,'first_ns':tl.t[0] if tl.t else None,'last_ns':tl.t[-1] if tl.t else None,'compute_seconds':time.perf_counter()-started,'checksum_verified':False,'status':'measurement_only','limitations':['single venue; global inventory-rebalancing comparison unavailable','checksum not verified; existing depth repair retained','no observed capture labels or feature qualification','no queue position, adverse move or future fill outcome inferred']}
def main():
    p=argparse.ArgumentParser(); p.add_argument('path',type=Path); p.add_argument('--out',type=Path,required=True); a=p.parse_args(); a.out.write_text(json.dumps(audit(a.path),indent=2,allow_nan=False))
if __name__=='__main__': main()
