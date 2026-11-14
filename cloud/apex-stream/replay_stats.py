"""Replay a complete archived session; no price interpolation or future lookahead."""
import argparse,gzip,json,collections,datetime
from pathlib import Path
from decimal import Decimal
from book import Book
from binance_feed import MARKETS,apply_event
from triangles import CYCLES
from triangle_stats import TriangleStats,BINANCE_CYCLES

def run(root):
 books={'kraken':{},'binance_us':{}};ids={};sessions={};invalid=collections.Counter();records=0;counts=collections.Counter()
 lags={'kraken':[],'binance_us':[]}
 stats={'kraken':TriangleStats(CYCLES,Decimal('.004')),'binance_us':TriangleStats(BINANCE_CYCLES,Decimal('.0002'))}
 fresh={'kraken':TriangleStats(CYCLES,Decimal('.004')),'binance_us':TriangleStats(BINANCE_CYCLES,Decimal('.0002'))}
 source_ts={}
 for path in sorted(Path(root).glob('*.jsonl.gz')):
  with gzip.open(path,'rt') as f:
   for line in f:
    r=json.loads(line,parse_float=Decimal);records+=1;venue=r['venue'];kind=r['event_type'];d=r['payload'];now=r['received_ns']/1e9
    if venue not in books:continue
    role=d.get('stream_role') if isinstance(d,dict) else None
    if kind=='session_start':
     if venue=='kraken' and role!='book':continue
     sessions[venue]=r['session_id'];books[venue]={}
     if venue=='binance_us':ids={}
    if r['session_id']!=sessions.get(venue):continue
    if kind=='gap':
     books[venue]={};invalid[venue+'_gap']+=1;continue
    try:
     if venue=='kraken' and d.get('channel')=='book':
      for b in d['data']:
       sym=b['symbol'];book=books[venue].setdefault(sym,Book(venue,sym,100 if sym in ['BTC/USD','ETH/USD'] else 25));book.apply(d);book.last_received=now
      times=[datetime.datetime.fromisoformat(b['timestamp'].replace('Z','+00:00')).timestamp() for b in d['data'] if b.get('timestamp')]
      if times:source_ts[venue]=min(times);lags[venue].append(now-source_ts[venue])
      counts[venue+'_book_messages']+=1
     elif venue=='binance_us' and kind=='book_snapshot':
      base,quote=MARKETS[d['symbol']];book=Book(venue,base+'/'+quote);book.reset(d['bids'],d['asks']);book.last_received=None
      books[venue][book.symbol]=book;ids[d['symbol']]=d['lastUpdateId']
     elif venue=='binance_us' and kind=='depth_update':
      e=d.get('data',{});symbol=e.get('s')
      if symbol in ids:
       base,quote=MARKETS[symbol];book=books[venue][base+'/'+quote];old=ids[symbol];ids[symbol]=apply_event(book,e,old)
       if old!=ids[symbol]:book.last_received=now
       source_ts[venue]=e['E']/1000;lags[venue].append(now-source_ts[venue])
       counts[venue+'_book_messages']+=1
     else:continue
    except ValueError as error:
     invalid[venue+':'+str(error)]+=1;books[venue]={}
     if venue=='binance_us':ids={}
    stats[venue].sample(books[venue],now,last_feed=now)
    fresh[venue].sample(books[venue],now,last_feed=source_ts.get(venue))
 return {'source':'63 committed raw chunks from session 72664196e4e742d1a702ee0a1eec2e61','records':records,'message_counts':dict(counts),'reconstruction_errors':dict(invalid),'receipt_only_diagnostics':{v:s.report() for v,s in stats.items()},'venues':{v:s.report() for v,s in fresh.items()},'exchange_to_receipt_seconds':{v:{'p50':sorted(a)[len(a)//2] if a else None,'p95':sorted(a)[int(.95*len(a))] if a else None,'max':max(a) if a else None,'messages_over_2s':sum(t>2 for t in a),'messages':len(a)} for v,a in lags.items()},'execution_enabled':False}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('output');a=p.parse_args();result=run(a.root);Path(a.output).write_text(json.dumps(result,indent=2));print(json.dumps({'records':result['records'],'message_counts':result['message_counts'],'reconstruction_errors':result['reconstruction_errors']}))
