"""Binance.US public depth stream with snapshot bridges and gap invalidation."""
import json,time,uuid,urllib.request,collections,concurrent.futures
import websocket
from book import Book
from triangle_stats import TriangleStats,BINANCE_CYCLES
from decimal import Decimal
MARKETS={'BTCUSDT':('BTC','USDT'),'ETHUSDT':('ETH','USDT'),'ETHBTC':('ETH','BTC'),'BTCUSD':('BTC','USD'),'ETHUSD':('ETH','USD'),'USDTUSD':('USDT','USD'),'LTCUSD':('LTC','USD'),'LTCUSDT':('LTC','USDT'),**{a+'USDT':(a,'USDT') for a in ['NOBODY','FORTH','ADX','GTC']}}
def apply_event(book,event,last):
 if event['u']<=last:return last
 if not event['U']<=last+1<=event['u']:book.valid=False;raise ValueError('sequence_gap')
 book.update('bids',event['b']);book.update('asks',event['a']);book.last_received=time.time();return event['u']
def feed(stop,emit,state):
 key='binance_us_book'
 while not stop.is_set():
  session=uuid.uuid4().hex;ordinal=0;ws=None;counts=collections.Counter();books={};ids={};last_state=0;last_screen=0
  stats=TriangleStats(BINANCE_CYCLES,Decimal('.0002'));last_stats_publish=0
  try:
   url='wss://stream.binance.us:9443/stream?streams='+'/'.join(s.lower()+'@depth@100ms' for s in MARKETS)
   ws=websocket.create_connection(url,timeout=10)
   emit('binance_us','session_start',{'symbols':list(MARKETS),'snapshot_depth':1000,'coverage':'diff-depth and bounded REST snapshots; deep-book tail may be unknown'},session,ordinal);ordinal+=1
   def snapshot(symbol):
    req=urllib.request.Request('https://api.binance.us/api/v3/depth?symbol='+symbol+'&limit=1000',headers={'User-Agent':'APEX-realtime-triangles/1.0'})
    with urllib.request.urlopen(req,timeout=4) as r:return symbol,json.load(r)
   with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    snapshots=list(pool.map(snapshot,MARKETS))
   for symbol,d in snapshots:
    base,quote=MARKETS[symbol]
    book=Book('binance_us',base+'/'+quote);book.reset(d['bids'],d['asks']);book.last_received=None;books[symbol]=book;ids[symbol]=d['lastUpdateId']
    emit('binance_us','book_snapshot',{'symbol':symbol,**d},session,ordinal);ordinal+=1
   bridge_started=time.monotonic()
   state(key,state='bridging_snapshots',book_count=len(books),bridged_books=0)
   while not stop.is_set():
    raw=ws.recv();received=time.time()
    if not raw:raise ValueError('empty socket response')
    wrapper=json.loads(raw);d=wrapper.get('data',{});symbol=d.get('s')
    emit('binance_us','depth_update',wrapper,session,ordinal);ordinal+=1
    if symbol not in books:continue
    source_lag=received-d['E']/1000
    state(key,exchange_to_receipt_lag_seconds=source_lag)
    old=ids[symbol];ids[symbol]=apply_event(books[symbol],d,old)
    if ids[symbol]==old:continue
    if source_lag<-.5:raise ValueError('exchange_timestamp_not_fresh')
    if source_lag>2:
     if time.monotonic()-bridge_started<10:continue
     raise ValueError('exchange_timestamp_not_fresh')
    if ids[symbol]!=old:counts[symbol]+=1
    current={b.symbol:b for b in books.values()}
    if ids[symbol]!=old:
     started=time.perf_counter();accepted,rejects=stats.affected(current,{books[symbol].symbol});stats.timing(started)
     for r in accepted:r['starting_currency']=r['cycle'][0];r['units_note']='USD-labelled numeric fields use cycle starting currency'
     state('binance_us_triangles',state='screening',cycles_requested=len(BINANCE_CYCLES),evaluated=len(accepted),rejections=rejects,positive_conditional=sum(Decimal(r['conditional_pnl_usd'])>0 for r in accepted),execution_enabled=False,screen_schedule='each book event, affected cycles only')
     if accepted:emit('binance_us','triangle_screen',{'results':accepted,'rejections':rejects},session,ordinal);ordinal+=1
    stats.sample(current,last_feed=received)
    if time.monotonic()-last_stats_publish>=30:
     report=stats.report();report['session_id']=session;state('binance_us_triangle_statistics',**report)
     emit('binance_us','triangle_statistics',report,session,ordinal);ordinal+=1;last_stats_publish=time.monotonic()
    if time.monotonic()-last_state>=1:
     state(key,state='receiving',error=None,book_count=len(books),bridged_books=sum(b.last_received is not None for b in books.values()),updates_by_symbol=dict(counts),last_received_ts=time.time(),session_id=session,execution_enabled=False);last_state=time.monotonic()
  except Exception as e:
   for b in books.values():b.valid=False
   state(key,state='disconnected',error=type(e).__name__+': '+str(e)[:160],book_state_invalidated=True)
   try:emit('binance_us','gap',{'error':str(e)[:160],'all_books_invalidated':True},session,ordinal)
   except Exception:pass
   stop.wait(5)
  finally:
   if ws:ws.close()
