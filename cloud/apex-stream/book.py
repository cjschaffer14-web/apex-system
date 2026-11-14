"""Deterministic price-level reconstruction; model features never submit orders."""
from decimal import Decimal
from sortedcontainers import SortedDict
import zlib,time
class Book:
 def __init__(self,venue,symbol,depth=None):
  self.venue,self.symbol,self.depth=venue,symbol,depth
  self.bids,self.asks=SortedDict(),SortedDict();self.valid=False;self.last_received=None
 def reset(self,bids,asks):
  self.bids.clear();self.asks.clear();self.valid=True
  try:self.update('bids',bids);self.update('asks',asks)
  except Exception:self.valid=False;raise
 def update(self,side,rows):
  if not self.valid:raise ValueError('update before snapshot')
  levels=getattr(self,side)
  for p,q in rows:
   p,q=Decimal(str(p)),Decimal(str(q))
   if not p.is_finite() or not q.is_finite() or p<=0 or q<0:raise ValueError('invalid price/size')
   if q==0:levels.pop(p,None)
   else:levels[p]=q
  if self.depth:
   while len(levels)>self.depth:levels.popitem(0 if side=='bids' else -1)
 def checksum(self):
  parts=[]
  for levels,reverse in [(self.asks,False),(self.bids,True)]:
   keys=list(levels.keys()[:10] if not reverse else levels.keys()[-10:][::-1])
   for p in keys:
    parts.extend(format(v,'f').replace('.','').lstrip('0') for v in [p,levels[p]])
  return zlib.crc32(''.join(parts).encode())&0xffffffff
 def apply(self,d):
  if self.venue=='coinbase':
   if d['type']=='snapshot':self.reset(d['bids'],d['asks'])
   elif d['type']=='l2update':
    for side,p,q in d['changes']:self.update('bids' if side=='buy' else 'asks',[(p,q)])
  elif self.venue=='kraken':
   for b in d['data']:
    if b['symbol']!=self.symbol:continue
    rows=lambda side:[(r['price'],r['qty']) for r in b.get(side,[])]
    if d['type']=='snapshot':self.reset(rows('bids'),rows('asks'))
    else:self.update('bids',rows('bids'));self.update('asks',rows('asks'))
    if self.checksum()!=b['checksum']:self.valid=False;raise ValueError('checksum mismatch')
  self.last_received=time.time()
 def feature(self,received_ns):
  if not self.valid or not self.bids or not self.asks:return None
  bid,bq=self.bids.peekitem(-1);ask,aq=self.asks.peekitem(0)
  if bid>=ask:return None
  mid=(bid+ask)/2;B=list(self.bids.items()[-25:][::-1]);A=list(self.asks.items()[:25])
  bs=sum(q for p,q in B);ass=sum(q for p,q in A)
  total_bid=sum(self.bids.values());total_ask=sum(self.asks.values())
  bands={}
  for bps in [5,10,25,50]:
   lo=mid*(1-Decimal(bps)/10000);hi=mid*(1+Decimal(bps)/10000)
   bn=sum(p*self.bids[p] for p in self.bids.irange(lo,bid));an=sum(p*self.asks[p] for p in self.asks.irange(ask,hi))
   bands[str(bps)]={'bid_notional':float(bn),'ask_notional':float(an),'truncated': bool(self.depth and (len(self.bids)>=self.depth and self.bids.peekitem(0)[0]>lo or len(self.asks)>=self.depth and self.asks.peekitem(-1)[0]<hi))}
  return {'venue':self.venue,'symbol':self.symbol,'received_ns':received_ns,'mid':float(mid),'best_bid':float(bid),'best_ask':float(ask),'bid_size':float(bq),'ask_size':float(aq),'spread_bps':float((ask-bid)/mid*10000),'top25_imbalance':float((bs-ass)/(bs+ass)),'retained_depth_imbalance':float((total_bid-total_ask)/(total_bid+total_ask)),'retained_depth':self.depth,'observed_bid_levels':len(self.bids),'observed_ask_levels':len(self.asks),'weighted_mid_proxy':float((ask*bq+bid*aq)/(bq+aq)),'depth_bands':bands,'bids':[[str(p),str(q)] for p,q in B],'asks':[[str(p),str(q)] for p,q in A]}
 def sweep(self,side,quantity):
  qty=Decimal(str(quantity));remaining=qty;cost=Decimal(0)
  levels=self.asks if side=='buy' else self.bids
  for p,q in (levels.items() if side=='buy' else reversed(levels.items())):
   take=min(q,remaining);cost+=p*take;remaining-=take
   if remaining==0:break
  return {'filled_quantity':float(qty-remaining),'unfilled_quantity':float(remaining),'vwap':float(cost/(qty-remaining)) if qty>remaining else None,'depth_scope':self.depth or 'published_full'}
def aggressor(d,venue):
 if venue=='coinbase':return 'buy' if d['side']=='sell' else 'sell'
 if venue=='kraken':return d['side']
 raise ValueError('unknown convention')
