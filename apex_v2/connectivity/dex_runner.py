"""One bounded Base V2 curve probe and native closed-cycle observation.
Uses existing candidate factory/token configuration, verified at an explicit block.
No USD peg, gas cost, balance sheet or transaction capture is inferred.
"""
import argparse
from dataclasses import asdict
from itertools import permutations
import json
from pathlib import Path
import time
from .dex import DexQuoteAdapter
from .pipeline import dex_cycle_packet, SnapshotStateEstimator
from ..dexdata.rpc import Rpc
from ..dexdata.collect import CHAINS, pad, dec_addr, SEL, word

def probe(out):
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    cfg=CHAINS['base']; status={'mode':'shadow','orders_authorized':False,'endpoints':{},'curves':[], 'candidate_records':0}
    curves=[]
    for i,url in enumerate(cfg['rpcs']):
        endpoint=f'base_public_rpc_{i}'
        rpc=Rpc([url],timeout=5,retries=1)
        try:
            chain=int(rpc.call('eth_chainId',[]),16)
            if chain!=8453: raise ValueError('wrong chain')
            header=rpc.call('eth_getBlockByNumber',['latest',False]); tag=header['number']
            status['endpoints'][endpoint]={'reachable':True,'chain_id':chain,'block_number':int(tag,16)}
            local=[]
            for dex,factory in cfg['factories'].items():
                # Only pools with an explicitly supported V2 fee specification.
                if dex not in ('uniswap_v2','sushiswap_v2'): continue
                tokens=cfg['tokens']
                address=dec_addr(rpc.call('eth_call',[{'to':factory,'data':SEL['getPair']+pad(tokens['WETH'])+pad(tokens['USDC'])},tag]))
                if address=='0x'+'0'*40: continue
                t0=dec_addr(rpc.call('eth_call',[{'to':address,'data':SEL['token0']},tag])).lower()
                t1=dec_addr(rpc.call('eth_call',[{'to':address,'data':SEL['token1']},tag])).lower()
                if {t0,t1}!={v.lower() for v in tokens.values()}: raise ValueError('factory pool token mismatch')
                adapter=DexQuoteAdapter(url,chain,address,t0,t1,endpoint_id=endpoint,rpc=rpc)
                local.append(adapter.snapshot(block=header))
            curves=local
            status['endpoints'][endpoint]['verified_curves']=len(curves)
            if curves: break
        except Exception as e:
            status['endpoints'].setdefault(endpoint,{'reachable':False})
            status['endpoints'][endpoint]['curve_error_type']=type(e).__name__
    rows=[]
    now=time.time_ns(); status['timestamp_ns']=now
    curves,state,rejected=SnapshotStateEstimator().update_curves(curves,now)
    status['state_estimate']=asdict(state)
    status['freshness_rejections']=rejected
    for c in curves:
        row=asdict(c); row['economic_venue_id']=c.economic_venue_id
        status['curves'].append(row)
    token=cfg['tokens']['USDC'].lower()
    for a,b in permutations(curves,2):
        try:
            p=dex_cycle_packet([a,b],token,100*10**6,now)
            if p['opportunity']['native_profit']>0:
                p['realized_shadow_outcome']['status']='run_ended_without_followup'
                p['censoring']={'right_censored':True,'reason':'one_shot_probe'}
                rows.append(p)
        except ValueError as e: status['candidate_error_type']=type(e).__name__
    status['candidate_records']=len(rows)
    (out/'dex-status.json').write_text(json.dumps(status,indent=2,allow_nan=False))
    (out/'dex-episodes.jsonl').write_text(''.join(json.dumps(p,allow_nan=False)+'\n' for p in rows))
    return status

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--out',type=Path,required=True)
    print(json.dumps(probe(parser.parse_args().out),indent=2))
if __name__=='__main__': main()
