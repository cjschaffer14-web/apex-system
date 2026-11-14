"""Causal, observed-trades-only bars. No synthetic prints, orders, or fill claims."""
from decimal import Decimal
from datetime import datetime,timezone
from collections import OrderedDict
import re
INTERVALS=(1,5,15,30,60)

def event_ns(timestamp):
 # Preserve all nine RFC3339 fractional digits, not datetime's six-digit ceiling.
 m=re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z',timestamp)
 if not m:raise ValueError('unsupported exchange timestamp')
 dt=datetime.strptime(m[1],'%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
 return int(dt.timestamp())*1_000_000_000+int((m[2] or '').ljust(9,'0') or '0')

def finite(x,positive=True):
 d=Decimal(str(x))
 if not d.is_finite() or (d<=0 if positive else d<0):raise ValueError('invalid trade price/size')
 return d

class TradeBars:
 def __init__(self,coverage_start_ns,intervals=INTERVALS,lateness_ns=2_000_000_000):
  if lateness_ns<0 or any(int(s)<=0 for s in intervals):raise ValueError('invalid bar settings')
  self.coverage_start_ns=coverage_start_ns;self.intervals=intervals;self.lateness_ns=lateness_ns
  self.watermark=coverage_start_ns-lateness_ns;self.bars={};self.seen=OrderedDict();self.rejections=0;self.duplicates=0
 def add(self,t,received_ns):
  symbol=t['symbol'];ident=(symbol,str(t['trade_id']))
  if ident in self.seen:self.duplicates+=1;return {'state':'duplicate','symbol':symbol,'trade_id':str(t['trade_id'])}
  stamp=event_ns(t['timestamp']);price=finite(t['price']);qty=finite(t['qty']);side=t['side']
  if side not in ['buy','sell']:raise ValueError('unknown taker side')
  if stamp>received_ns+5_000_000_000:raise ValueError('trade event time exceeds clock-skew allowance')
  self.seen[ident]=None
  if len(self.seen)>50000:self.seen.popitem(last=False)
  if stamp<self.watermark:
   self.rejections+=1
   # Retain the raw print but do not rewrite already-finalized feature history.
   return {'state':'late_excluded_from_all_bars','symbol':symbol,'trade_id':str(t['trade_id']),'event_ns':stamp,'watermark_ns':self.watermark,'received_ns':received_ns}
  for interval in self.intervals:
   width=interval*1_000_000_000;start=stamp//width*width;key=(symbol,interval,start)
   b=self.bars.get(key)
   if b is None:
    b={'symbol':symbol,'interval_seconds':interval,'start_ns':start,'end_ns':start+width,'open':price,'high':price,'low':price,'close':price,'volume_base':Decimal(0),'volume_quote':Decimal(0),'buy_volume_base':Decimal(0),'sell_volume_base':Decimal(0),'trade_count':0,'first_event_ns':stamp,'last_event_ns':stamp,'first_trade_id':str(t['trade_id']),'last_trade_id':str(t['trade_id']),'first_received_ns':received_ns,'last_received_ns':received_ns};self.bars[key]=b
   b['high']=max(b['high'],price);b['low']=min(b['low'],price)
   # Exchange event time (then stable input arrival order on ties) determines OHLC.
   if stamp<b['first_event_ns']:b['open']=price;b['first_event_ns']=stamp;b['first_trade_id']=str(t['trade_id'])
   if stamp>=b['last_event_ns']:b['close']=price;b['last_event_ns']=stamp;b['last_trade_id']=str(t['trade_id'])
   b['volume_base']+=qty;b['volume_quote']+=price*qty;b[side+'_volume_base']+=qty;b['trade_count']+=1
   b['first_received_ns']=min(b['first_received_ns'],received_ns);b['last_received_ns']=max(b['last_received_ns'],received_ns)
  return {'state':'included','symbol':symbol}
 def advance(self,received_ns):
  self.watermark=max(self.watermark,received_ns-self.lateness_ns);out=[]
  for key,b in list(self.bars.items()):
   if b['end_ns']>self.watermark:continue
   b['vwap']=b['volume_quote']/b['volume_base'];b['signed_volume_base']=b['buy_volume_base']-b['sell_volume_base']
   b.update(venue='kraken',source='observed_public_trades',finalized_received_ns=received_ns,finalization_lateness_ns=self.lateness_ns,session_partial_start=b['start_ns']<self.coverage_start_ns,finalization='receive_clock_watermark',completeness='not_certified; late events and feed gaps remain raw evidence',empty_intervals='omitted_not_forward_filled')
   out.append({k:str(v) if isinstance(v,Decimal) else v for k,v in b.items()});del self.bars[key]
  return sorted(out,key=lambda b:(b['end_ns'],b['symbol'],b['interval_seconds']))

def l1_ofi(previous,current):
 """Cont-style L1 size-change proxy between observed book states, not trade flow."""
 pb,pq,pa,ps=map(Decimal,map(str,previous));bid,bq,ask,aq=map(Decimal,map(str,current))
 return (bq if bid>=pb else Decimal(0))-(pq if bid<=pb else Decimal(0))-(aq if ask<=pa else Decimal(0))+(ps if ask>=pa else Decimal(0))
