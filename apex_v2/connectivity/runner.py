"""Bounded public snapshot observer. No daemon, credentials, or order submission.
python3 -m apex_v2.connectivity.runner --samples 3 --out DIRECTORY
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import time
from .interfaces import MarketDataStream
from .public import CoinbaseConnector, KrakenConnector
from .pipeline import CandidatePipeline, Policy
from .markets import pair_name
from ..episodes.tracker import EpisodeStore

class PublicSnapshotStream(MarketDataStream):
    def __init__(self, connectors): self.connectors=tuple(connectors)
    def poll(self, pair):
        snapshots=[]; status={}
        with ThreadPoolExecutor(max_workers=len(self.connectors)) as pool:
            jobs=[(c,pool.submit(c.snapshot,pair)) for c in self.connectors]
            for c,job in jobs:
                try:
                    s=job.result(); snapshots.append(s)
                    status[c.endpoint_id]={'reachable':True,'request_ns':s.request_ns,'received_ns':s.received_ns,
                                           'source_ns':s.source_ns,'economic_venue_id':s.economic_venue_id,
                                           'bid_levels':len(s.book.bids),'ask_levels':len(s.book.asks)}
                except Exception as e:
                    # Only type, never untrusted endpoint/error text or secrets.
                    status[c.endpoint_id]={'reachable':False,'error_type':type(e).__name__}
        return snapshots,status

def run(samples, interval, out, fee_bps=None, *, pairs=('BTC/USD',),
        venues=('coinbase', 'kraken'), discover=False):
    if not 1<=samples<=60 or not 1<=interval<=60: raise ValueError('bounded samples/interval required')
    pairs = tuple(pair_name(p) for p in pairs)
    if not pairs or len(pairs)>20 or len(set(pairs)) != len(pairs):
        raise ValueError('one to twenty distinct pairs required')
    classes = {'coinbase': CoinbaseConnector, 'kraken': KrakenConnector}
    if not venues or len(set(venues)) != len(venues) or any(v not in classes for v in venues):
        raise ValueError('unknown or repeated venue')
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    connectors = [classes[v](fee_bps.get(v) if isinstance(fee_bps,dict) else fee_bps) for v in venues]
    catalog = {}; discovery_status = {}
    if discover:
        for connector in connectors:
            try:
                rows = connector.markets()
                catalog[connector.economic_venue_id] = rows
                discovery_status[connector.economic_venue_id] = {'status':'discovered', 'markets':len(rows)}
            except Exception as error:
                discovery_status[connector.economic_venue_id] = {'status':'failed', 'error_type':type(error).__name__}
        (out/'markets.json').write_text(json.dumps(catalog, default=lambda x: asdict(x) if hasattr(x,'__dataclass_fields__') else str(x), indent=2))
    stream=PublicSnapshotStream(connectors)
    pipelines={pair: CandidatePipeline() for pair in pairs}
    store=EpisodeStore(str(out/'episodes.sqlite'))
    summary={'mode':'shadow','orders_authorized':False,'continuous_runner':False,'samples':[],
             'fees':'unknown' if fee_bps is None else {'declared_assumption_bps_each':fee_bps},
             'candidate_records':0,'outcome_records':0, 'pairs':list(pairs), 'venues':list(venues),
             'discovery':discovery_status}
    try:
        for i in range(samples):
            for pair in pairs:
                snapshots,status=stream.poll(pair); now=time.time_ns()
                pipeline=pipelines[pair]
                packets=pipeline.observe(snapshots,now)
                with (out/'snapshots.jsonl').open('a') as f:
                    for s in snapshots:
                        row=asdict(s); row['book']['bids']=[[str(x.price),str(x.size)] for x in s.book.bids]
                        row['book']['asks']=[[str(x.price),str(x.size)] for x in s.book.asks]
                        f.write(json.dumps(row,allow_nan=False)+'\n')
                with (out/'episodes.jsonl').open('a') as f:
                    for packet in packets:
                        store.save(packet); f.write(json.dumps(packet,allow_nan=False)+'\n')
                        key='candidate_records' if packet['realized_shadow_outcome']['status']=='pending' else 'outcome_records'
                        summary[key]+=1
                summary['samples'].append({'timestamp_ns':now,'pair':pair,'endpoints':status,'freshness_rejections':pipeline.rejected,
                                           'state_assets':sorted(pipeline.last_states)})
            if i+1<samples: time.sleep(interval)
        # Pending observations are explicitly right-censored at finite shutdown.
        with (out/'episodes.jsonl').open('a') as f:
            for pipeline in pipelines.values():
                for packet in pipeline.finish(time.time_ns()):
                    store.save(packet); f.write(json.dumps(packet,allow_nan=False)+'\n')
                    summary['outcome_records']+=1
        (out/'status.json').write_text(json.dumps(summary,indent=2,allow_nan=False))
        return summary
    finally: store.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=3)
    parser.add_argument('--interval',type=float,default=2)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--assumed-fee-bps',type=float,default=None)
    parser.add_argument('--pairs',nargs='+',default=['BTC/USD'])
    parser.add_argument('--venues',nargs='+',choices=['coinbase','kraken'],default=['coinbase','kraken'])
    parser.add_argument('--discover',action='store_true',help='Save current active spot market catalog, including minimum sizes/increments')
    args=parser.parse_args()
    print(json.dumps(run(args.samples,args.interval,args.out,args.assumed_fee_bps,
                         pairs=args.pairs,venues=args.venues,discover=args.discover),indent=2))
if __name__=='__main__': main()
