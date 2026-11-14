"""Continuous public event archive with explicit reconnection boundaries and durable spool."""
import os,json,time,uuid,gzip,queue,threading,datetime,hashlib,urllib.request,urllib.error,signal,collections,resource
from pathlib import Path
from decimal import Decimal
import websocket
from book import Book
from triangles import EXTRA_PAIRS,CYCLES,screen,KRAKEN_FEES
from binance_feed import feed as binance_feed
from triangle_stats import TriangleStats
SPOOL_DONE=threading.Event()
from microstructure import TradeBars,l1_ofi,INTERVALS,event_ns
from store import Store
import candles
STOP=threading.Event();CAPTURE_DONE=threading.Event();Q=queue.Queue(maxsize=10000);SESSION=uuid.uuid4().hex
ROOT=Path(os.environ.get('SPOOL_DIR','/spool'));ROOT.mkdir(parents=True,exist_ok=True)
PAIRS=sorted({p for p,i in candles.MANIFEST['markets']} | set(EXTRA_PAIRS));FEATURES={};STATES={};LOCK=threading.Lock()
DEPTHS={p.replace('-','/'):(100 if p in ['BTC-USD','ETH-USD'] else 25) for p in PAIRS}
COLLECTOR_VERSION='realtime-triangles-v6'
REVISION=hashlib.sha256(Path(__file__).read_bytes()+(Path(__file__).parent/'book.py').read_bytes()+(Path(__file__).parent/'microstructure.py').read_bytes()+(Path(__file__).parent/'triangles.py').read_bytes()+(Path(__file__).parent/'binance_feed.py').read_bytes()+(Path(__file__).parent/'triangle_stats.py').read_bytes()).hexdigest()
def emit(venue,kind,payload,session,ordinal):
 r={'venue':venue,'event_type':kind,'session_id':session,'ordinal':ordinal,'received_ns':time.time_ns(),'received_monotonic_ns':time.monotonic_ns(),'payload':payload,'schema_version':1,'collector_version':COLLECTOR_VERSION}
 Q.put(r,timeout=5)
def state(state_key,**values):
 with LOCK:STATES.setdefault(state_key,{}).update(values,updated_ts=time.time())
def archive():
 buffer=[];size=0;part=0;last=time.monotonic()
 while not STOP.is_set() or not CAPTURE_DONE.is_set() or not Q.empty() or buffer:
  try:
   r=Q.get(timeout=1);line=json.dumps(r,separators=(',',':'),default=str).encode()+b'\n';buffer.append(line);size+=len(line)
  except queue.Empty:pass
  if buffer and ((STOP.is_set() and CAPTURE_DONE.is_set() and Q.empty()) or time.monotonic()-last>=30 or size>=4*1024*1024):
   first=json.loads(buffer[0])['received_ns'];day=datetime.datetime.fromtimestamp(first/1e9,datetime.timezone.utc).strftime('%Y%m%d')
   name=f'raw__{day}__{first}-{SESSION}-{part:08}.jsonl.gz';part+=1
   tmp=ROOT/(name+'.tmp');tmp.write_bytes(gzip.compress(b''.join(buffer),compresslevel=3));tmp.rename(ROOT/name)
   buffer=[];size=0;last=time.monotonic()
 SPOOL_DONE.set()
def archive_upload():
 store=Store();uploaded=0;last_health=0
 while not SPOOL_DONE.is_set() or list(ROOT.glob('*.jsonl.gz')):
  files=sorted(ROOT.glob('*.jsonl.gz'))
  if sum(p.stat().st_size for p in files)>512*1024*1024:
   state('archive',state='spool_capacity_reached');STOP.set();raise RuntimeError('durable spool capacity reached; capture stopped')
  for p in files[:4]:
   try:
    try:store.put_bytes(p.name.replace('__','/'),p.read_bytes(),'application/gzip')
    except urllib.error.HTTPError as e:
     if e.code!=412:raise
    p.unlink();uploaded+=1;state('archive',state='writing',uploaded_chunks=uploaded,last_committed_ts=time.time(),pending_chunks=len(files)-1)
   except Exception as e:state('archive',state='upload_retry',error=type(e).__name__);break
  if time.monotonic()-last_health>=30:
   with LOCK:doc={'updated_ts':time.time(),'revision':REVISION,'session_id':SESSION,'requested_products':PAIRS,'feeds':dict(STATES),'features':dict(FEATURES),'model_role':'advisory only; no order authority','private_account_data':'not available to public collector','collector_version':COLLECTOR_VERSION,'requested_depths':DEPTHS,'requested_channels':['book','trade','ticker','ohlc','instrument'],'trade_bar_intervals_seconds':list(INTERVALS),'trade_bar_lateness_seconds':10,'host_resource_snapshot':{'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'cpu_seconds':resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,'queue_records':Q.qsize()}}
   try:store.put('health/latest.json',doc,None);last_health=time.monotonic()
   except Exception as e:print(json.dumps({'state':'health_upload_failed','error':type(e).__name__}),flush=True)
  STOP.wait(.1) if not STOP.is_set() else time.sleep(.1)
def subscription_plan(role):
 symbols=list(DEPTHS)
 requests=[]
 for depth in [25,100]:
  group=[s for s in symbols if DEPTHS[s]==depth]
  if group:requests.append({'method':'subscribe','params':{'channel':'book','symbol':group,'depth':depth,'snapshot':True}})
 if role=='book':return requests
 if role!='aux':raise ValueError('unknown stream role')
 return [
  {'method':'subscribe','params':{'channel':'trade','symbol':symbols,'snapshot':False}},
  {'method':'subscribe','params':{'channel':'ticker','symbol':symbols,'event_trigger':'trades','snapshot':True}},
  {'method':'subscribe','params':{'channel':'ohlc','symbol':symbols,'interval':1,'snapshot':True}},
  {'method':'subscribe','params':{'channel':'instrument','snapshot':True}},
 ]

def feed(venue,role):
 if venue!='kraken':raise ValueError('venue not enabled for this private research worker')
 state_key=venue+'_'+role
 while not STOP.is_set():
  session=uuid.uuid4().hex;ordinal=0;books={};last_triangles=0;last_features={};last_l1={};ofi={};ws=None;counts=collections.Counter();acks=collections.Counter();errors=[]
  try:
   ws=websocket.create_connection('wss://ws.kraken.com/v2',timeout=10)
   stats=TriangleStats(CYCLES,KRAKEN_FEES);last_stats_publish=0;last_book_source=None
   requests=subscription_plan(role);bars=TradeBars(time.time_ns(),lateness_ns=10_000_000_000);last_state=0;trade_lags=collections.deque(maxlen=500)
   emit(venue,'session_start',{'requests':requests,'requested_depths':DEPTHS if role=='book' else {},'stream_role':role,'trade_bar_intervals_seconds':list(INTERVALS) if role=='aux' else [],'coverage_start_ns':bars.coverage_start_ns,'trade_bar_lateness_seconds':10},session,ordinal);ordinal+=1
   for request in requests:ws.send(json.dumps(request))
   state(state_key,state='subscribing',session_id=session,book_count=0,channel_counts={},subscription_errors=[])
   while not STOP.is_set():
    raw=ws.recv();received=time.time_ns()
    if not raw:raise ValueError('empty socket response')
    if len(raw)>8*1024*1024:raise ValueError('message exceeds bound')
    d=json.loads(raw,parse_float=Decimal);kind=d.get('type',d.get('channel',d.get('method','other')))
    emit(venue,kind,d,session,ordinal);ordinal+=1
    if d.get('success') is True and d.get('method')=='subscribe':acks[d.get('result',{}).get('channel','unknown')]+=1
    if d.get('type')=='error' or d.get('success') is False:
     errors.append(str(d.get('message',d.get('error')))[:160]);errors=errors[-20:]
     state(state_key,state='subscription_error',subscription_errors=errors,last_received_ts=time.time());continue
    channel=d.get('channel');counts[channel or 'control']+=1
    symbols=[]
    if channel=='book':
     source_times=[event_ns(b['timestamp'])/1e9 for b in d['data'] if b.get('timestamp')]
     if not source_times:raise ValueError('missing exchange book timestamp')
     last_book_source=min(source_times);source_lag=received/1e9-last_book_source
     if d.get('type')=='update':
      state(state_key,exchange_to_receipt_lag_seconds=source_lag)
      if source_lag>2 or source_lag<-.5:raise ValueError('exchange_timestamp_not_fresh')
     else:state(state_key,snapshot_source_age_seconds=source_lag)
     symbols=list(dict.fromkeys(b['symbol'] for b in d['data']))
     for sym in symbols:
      book=books.setdefault(sym,Book(venue,sym,DEPTHS[sym]));book.apply(d)
      if book.valid and book.bids and book.asks:
       bid,bq=book.bids.peekitem(-1);ask,aq=book.asks.peekitem(0);current=(bid,bq,ask,aq)
       if sym in last_l1:ofi[sym]=ofi.get(sym,Decimal(0))+l1_ofi(last_l1[sym],current)
       last_l1[sym]=current
    if channel=='book':
     started=time.perf_counter()
     accepted,rejects=stats.affected(books,set(symbols))
     stats.timing(started)
     state('triangles',state='screening',cycles_requested=len(CYCLES),evaluated=len(accepted),rejections=rejects,positive_conditional=sum(Decimal(r['conditional_pnl_usd'])>0 for r in accepted),execution_enabled=False,screen_schedule='each book event, affected cycles only')
     if accepted:emit(venue,'triangle_screen',{'results':accepted,'rejections':rejects},session,ordinal);ordinal+=1
    if role=='book':
     stats.sample(books,last_feed=received/1e9 if last_book_source is not None else None)
     if time.monotonic()-last_stats_publish>=30:
      report=stats.report();report['session_id']=session;state('triangle_statistics',**report)
      emit(venue,'triangle_statistics',report,session,ordinal);ordinal+=1;last_stats_publish=time.monotonic()
    if channel=='trade' and d.get('type')=='update':
     for trade in d.get('data',[]):
      try:
       trade_lags.append((received-event_ns(trade['timestamp']))/1e9);quality=bars.add(trade,received)
      except ValueError as e:quality={'state':'invalid_trade_excluded_from_bars','error':str(e)[:160],'symbol':trade.get('symbol')}
      if quality['state'] not in ['included','duplicate']:
       emit(venue,'trade_quality',quality,session,ordinal);ordinal+=1
    for b in (bars.advance(received) if role=='aux' else []):
     emit(venue,'trade_bar',b,session,ordinal);ordinal+=1;counts['trade_bar_'+str(b['interval_seconds'])+'s']+=1
    for sym in symbols:
     if time.time()-last_features.get(sym,0)>=1:
      f=books[sym].feature(received)
      if f:
       source_time=next((b.get('timestamp') for b in d.get('data',[]) if b.get('symbol')==sym),None)
       f.update(exchange_event_timestamp=source_time,exchange_to_processing_lag_seconds=(received-event_ns(source_time))/1e9 if source_time else None)
       f.update(l1_ofi_since_previous_feature=str(ofi.pop(sym,Decimal(0))),l1_ofi_window_start_received_ns=last_features.get(sym)*1_000_000_000 if sym in last_features else None,feature_frequency='book_event_triggered_at_most_1Hz')
       with LOCK:FEATURES[venue+':'+sym]=f
       emit(venue,'feature_1s',f,session,ordinal);ordinal+=1;last_features[sym]=received/1e9
    if time.monotonic()-last_state>=.5:
     state(state_key,state='receiving' if not errors else 'receiving_with_subscription_errors',error=None,stream_role=role,messages=ordinal,book_count=len(books),book_depths={s:b.depth for s,b in books.items()},channel_counts=dict(counts),subscription_acks=dict(acks),subscription_errors=errors,late_trades_excluded=bars.rejections,duplicate_trades=bars.duplicates,trade_receive_lag_max_last500_seconds=max(trade_lags) if trade_lags else None,last_received_ts=time.time(),session_id=session);last_state=time.monotonic()
  except Exception as e:
   with LOCK:
    for key in list(FEATURES):
     if role=='book' and key.startswith(venue+':'):FEATURES.pop(key,None)
   state(state_key,state='disconnected',error=type(e).__name__+': '+str(e)[:160])
   try:emit(venue,'gap',{'error':type(e).__name__,'stream_role':role,'book_state_invalidated':role=='book','partial_trade_bars_discarded':role=='aux'},session,ordinal)
   except queue.Full:state(state_key,state='queue_overflow')
   if ws:ws.close()
   STOP.wait(5)
  finally:
   if ws:ws.close()
def reader_main(role):feed('kraken',role)
def terminate(signum,frame):STOP.set()
if __name__=='__main__':
 signal.signal(signal.SIGTERM,terminate);signal.signal(signal.SIGINT,terminate)
 writer=threading.Thread(target=archive,daemon=True);writer.start()
 uploader=threading.Thread(target=archive_upload,daemon=True);uploader.start()
 readers=[threading.Thread(target=reader_main,args=(role,),daemon=True) for role in ['book','aux']]
 readers.append(threading.Thread(target=binance_feed,args=(STOP,emit,state),daemon=True))
 for reader in readers:reader.start()
 while not STOP.wait(30):
  if not writer.is_alive() or not uploader.is_alive() or any(not reader.is_alive() for reader in readers):STOP.set();break
  with LOCK:print(json.dumps({'state':'running','feeds':STATES,'queue_size':Q.qsize()},default=str),flush=True)
 for reader in readers:reader.join(timeout=12)
 CAPTURE_DONE.set();writer.join(timeout=45);uploader.join(timeout=45)
 raise SystemExit('capture stopped')
