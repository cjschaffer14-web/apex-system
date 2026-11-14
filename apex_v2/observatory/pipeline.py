"""Collector integration: persist measurements and complete pending episode packets.
Quote-only pairing is observational; executable candidate generation must use
book/curve adapters with explicit fees, settlement and agent feasibility.
"""
import json
from pathlib import Path
from dataclasses import asdict
from .observations import ShadowPriceEngine,measurement_from_pair
from ..episodes.detector import PersistentDetector
from ..episodes.tracker import EpisodeStore
from ..reporting.shadow_engine import ShadowEngine

def observe_snapshot(observations,state,directory,now_ns,code_commit,candidates_by_episode=None):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    detector=PersistentDetector(str(directory/'episode_learning.sqlite'))
    store=EpisodeStore(str(directory/'episode_packets.sqlite'))
    engine=ShadowEngine(store,code_commit,{'observatory':'executable-only-v1','capture':'unfitted-prior-v1','allocator':'bounded-discrete-v1'})
    packets=[]; candidates_by_episode=candidates_by_episode or {}
    try:
        with (directory/'observations.jsonl').open('a') as f:
            for o in observations:
                row=asdict(o); row['lane']=o.lane.value
                # Persist public measurements only, no arbitrary adapter metadata.
                row['metadata']={k:v for k,v in o.metadata.items() if k in ('fees_known','finality','latency_seconds','volatility','depth','settlement')}
                f.write(json.dumps(row,allow_nan=False)+'\n')
        for asset in sorted({o.asset for o in observations}):
            rows=[o for o in observations if o.asset==asset]
            try: shadow=ShadowPriceEngine(max_age_s=2).build(asset,rows,now_ns)
            except ValueError: continue
            rows=[o for o in rows if o.source_id not in shadow.rejected_sources]
            # Redundant sources cannot generate distinct episodes or inflate depth.
            venues={}
            for o in rows:
                venues.setdefault(o.economic_venue,[]).append(o)
            from dataclasses import replace
            conservative=[]
            for venue,group in venues.items():
                first=min(group,key=lambda x:x.ts_ns)
                conservative.append(replace(first,bid=min(x.bid for x in group),ask=max(x.ask for x in group),bid_depth_usd=min(x.bid_depth_usd for x in group),ask_depth_usd=min(x.ask_depth_usd for x in group)))
            for buy in conservative:
                for sell in conservative:
                    if buy.economic_venue==sell.economic_venue: continue
                    m=measurement_from_pair(buy,sell,shadow,notional_cap_usd=state.capital_usd)
                    ep=detector.ingest(m)
                    if ep is None: continue
                    fees_known=bool(buy.metadata.get('fees_known')) and bool(sell.metadata.get('fees_known'))
                    packet=engine.observe(ep.episode_id,now_ns,asset,m.lane.value,[buy.economic_venue,sell.economic_venue],{'freshness_seconds':{o.source_id:(now_ns-o.ts_ns)/1e9 for o in (buy,sell)},'uncertainty':1-shadow.confidence,'volatility':None,'settlement_finality':{o.source_id:o.metadata.get('finality','unknown') for o in (buy,sell)},'fees_known':fees_known,'executable_depth_usd':min(buy.ask_depth_usd,sell.bid_depth_usd),'venue_reliability':min(buy.reliability,sell.reliability)}, {'gross_usd':m.executable_value_usd*m.gross_edge_bps/1e4,'cost_usd':m.costs.total_usd if fees_known else None,'net_usd':m.estimated_net_edge_usd if fees_known else None,'F1_usd':None,'optimal_size_usd':None,'half_life_seconds':ep.half_life_ns/1e9 if ep.half_life_ns is not None else None,'accounting':'descriptive_quote_pair; executable books/curves required','measurement':ep.to_dict()},state,candidates_by_episode.get(ep.episode_id,[]) if fees_known else [],[buy.source_id,sell.source_id])
                    packets.append(packet)
        detector.close_stale(now_ns)
        return packets
    finally: detector.close(); store.close()
