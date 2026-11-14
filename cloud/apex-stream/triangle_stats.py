"""Descriptive rates on one sample per observed second, never fill probabilities."""
import collections,time,math
from decimal import Decimal
from triangles import screen,edge
BINANCE_CYCLES=[('USD','BTC','ETH','USD'),('USD','ETH','BTC','USD'),('USDT','BTC','ETH','USDT'),('USDT','ETH','BTC','USDT'),('USD','USDT','LTC','USD'),('USD','LTC','USDT','USD')]
PROFILES={'strict_50ms':(2,.05),'strict_250ms':(2,.25),'skew_1000ms':(2,1),'continuous_book_research':(None,None)}
class TriangleStats:
 def __init__(self,cycles,fee):
  self.cycles=cycles;self.fee=fee;self.start=None;self.end=None;self.last_second=None
  self.rows={};self.processing=collections.deque(maxlen=1000);self.events=0
 def timing(self,started):
  self.processing.append((time.perf_counter()-started)*1000);self.events+=1
 def sample(self,books,now=None,last_feed=None):
  now=time.time() if now is None else now
  if self.last_second==int(now):return False
  self.last_second=int(now);self.start=now if self.start is None else self.start;self.end=now
  for profile,(age,skew) in PROFILES.items():
   for cycle in self.cycles:
    for size in [10,25,100]:
     key=profile+'|'+'>'.join(cycle)+'|'+str(size)
     row=self.rows.setdefault(key,{'profile':profile,'cycle':list(cycle),'starting_currency':cycle[0],'size':size,'samples':0,'eligible':0,'gross_positive':0,'fee_positive':0,'rejections':collections.Counter(),'best_net_bps':None,'positive_minutes':set(),'sample_minutes':set()})
     row['samples']+=1;row['sample_minutes'].add(int(now)//60)
     try:
      if last_feed is None or not 0<=now-last_feed<=2:raise ValueError('feed_not_live')
      result=screen(books,cycle,size,now=now,fee=self.fee,max_age=age,max_skew=skew)
      row['eligible']+=1
      gross=Decimal(result['gross_final_usd'])>size;positive=Decimal(result['conditional_pnl_usd'])>0
      row['gross_positive']+=gross;row['fee_positive']+=positive
      bps=float(Decimal(result['conditional_pnl_usd'])/size*10000)
      row['best_net_bps']=bps if row['best_net_bps'] is None else max(row['best_net_bps'],bps)
      if positive:row['positive_minutes'].add(int(now)//60)
     except ValueError as error:row['rejections'][str(error)]+=1
  return True
 def report(self):
  rows=[]
  for row in self.rows.values():
   r={k:v for k,v in row.items() if k not in ['positive_minutes','sample_minutes']}
   r['rejections']=dict(r['rejections']);r['sample_minutes']=len(row['sample_minutes']);r['positive_minutes']=len(row['positive_minutes'])
   r['eligibility_rate']=row['eligible']/row['samples']
   r['fee_positive_rate_of_eligible']=row['fee_positive']/row['eligible'] if row['eligible'] else None
   r['fee_positive_rate_of_all_samples']=row['fee_positive']/row['samples']
   rows.append(r)
  lat=sorted(self.processing)
  pct=lambda q:lat[min(len(lat)-1,math.ceil(q*len(lat))-1)] if lat else None
  return {'start_ts':self.start,'end_ts':self.end,'sample_method':'first received message in each observed wall-clock second; missing seconds not imputed','interpretation':'descriptive correlated quote-state frequencies; not independent trials, future probabilities or executable fills; continuous_book_research removes book age/skew only while socket is live and books validated/bridged','assumed_fee_per_leg':{k:str(v) for k,v in self.fee.items()} if isinstance(self.fee,dict) else str(self.fee),'rows':rows,'events_screened':self.events,'local_processing_ms_last1000':{'p50':pct(.5),'p95':pct(.95),'p99':pct(.99)},'execution_enabled':False}
 def affected(self,books,symbols,now=None):
  results=[];rejects=collections.Counter();now=time.time() if now is None else now
  for cycle in self.cycles:
   try:
    if not any(edge(books,a,b)[0].symbol in symbols for a,b in zip(cycle,cycle[1:])):continue
   except ValueError:continue
   for size in [10,25,100]:
    try:results.append(screen(books,cycle,size,now=now,fee=self.fee))
    except ValueError as error:rejects[str(error)]+=1
  return results,dict(rejects)
