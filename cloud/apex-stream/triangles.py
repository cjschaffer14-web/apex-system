"""Depth-sized research screening; no trading interface or assumed account fees."""
from decimal import Decimal
import time
CYCLES=[('USD','EUR',a,'USD') for a in ['NOBODY','FORTH','ADX','GTC']]+[('USD','BTC','ETH','USD')]
CYCLES += [(c[0],c[2],c[1],c[0]) for c in list(CYCLES)]
EXTRA_PAIRS=['EUR-USD','ETH-BTC']+[a+'-'+q for a in ['NOBODY','FORTH','ADX','GTC'] for q in ['USD','EUR']]
KRAKEN_FEES={'default':Decimal('.008'),'EUR/USD':Decimal('.002')}
def edge(books,source,target):
 if target+'/'+source in books:return books[target+'/'+source],True
 if source+'/'+target in books:return books[source+'/'+target],False
 raise ValueError('missing_edge')
def convert(book,amount,buy):
 if not book.valid or not book.bids or not book.asks:raise ValueError('invalid_book')
 if book.bids.peekitem(-1)[0]>=book.asks.peekitem(0)[0]:raise ValueError('crossed_book')
 rem=Decimal(str(amount));out=Decimal(0)
 for p,q in (book.asks.items() if buy else reversed(book.bids.items())):
  take=min(rem,p*q if buy else q);out+=take/p if buy else take*p;rem-=take
  if rem<=Decimal('1e-20'):return out
 raise ValueError('insufficient_depth')
def screen(books,cycle,usd,now=None,fee=Decimal('.004'),max_age=2,max_skew=.25):
 now=time.time() if now is None else now;edges=[edge(books,a,b) for a,b in zip(cycle,cycle[1:])]
 times=[b.last_received for b,_ in edges]
 if any(t is None or now<t or (max_age is not None and now-t>max_age) for t in times):raise ValueError('stale_receipt')
 if max_skew is not None and max(times)-min(times)>max_skew:raise ValueError('receipt_skew')
 gross=net=Decimal(str(usd))
 for book,buy in edges:
  rate=fee.get(book.symbol,fee['default']) if isinstance(fee,dict) else fee
  gross=convert(book,gross,buy);net=convert(book,net,buy)*(1-rate)
 return {'cycle':list(cycle),'starting_usd':usd,'gross_final_usd':str(gross),'conditional_final_usd':str(net),'conditional_pnl_usd':str(net-Decimal(str(usd))),'assumed_fee_per_leg':{k:str(v) for k,v in fee.items()} if isinstance(fee,dict) else str(fee),'receipt_skew_seconds':max(times)-min(times),'state':'research_only: account fees, fee currency, minima, precision and fill timing unverified','executable_profit':False}
