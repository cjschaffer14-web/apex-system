import concurrent.futures,hashlib,json,time,uuid,urllib.request
from pathlib import Path
from cloud_store import Store
ROOT=Path(__file__).parent
MANIFEST=json.loads((ROOT/'manifest.json').read_text())
REVISION=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def fetch(item):
 label,url=item;start=time.time_ns()
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'APEX-cloud-microcap/1.0'})
  with urllib.request.urlopen(req,timeout=3) as r:
   body=r.read(400001)
   if len(body)>400000:raise ValueError('response too large')
   data=json.loads(body)
  if isinstance(data,dict) and data.get('error'):raise ValueError(str(data['error']))
  return {'label':label,'sent_ns':start,'received_ns':time.time_ns(),'url':url,'payload':data}
 except Exception as e:return {'label':label,'sent_ns':start,'received_ns':time.time_ns(),'url':url,'error_type':type(e).__name__,'error':str(e)}
def jobs():
 items=[]
 for a in MANIFEST['assets']:
  items.extend([(a+'_kraken_depth','https://api.kraken.com/0/public/Depth?pair='+a+'USD&count=20'),
   (a+'_binance_us_depth','https://api.binance.us/api/v3/depth?symbol='+a+'USDT&limit=20'),
   (a+'_binance_us_bars','https://api.binance.us/api/v3/klines?symbol='+a+'USDT&interval=1m&limit=180'),
   (a+'_binance_us_trades','https://api.binance.us/api/v3/aggTrades?symbol='+a+'USDT&limit=100')])
 items.extend([('USD_USDT_conversion','https://api.binance.us/api/v3/depth?symbol=USDTUSD&limit=20'),
  ('kraken_pairs','https://api.kraken.com/0/public/AssetPairs?pair='+','.join(a+'USD' for a in MANIFEST['assets'])+'&country_code=US%3APA')])
 return items
def validate_book(data,venue):
 book=next(iter(data['result'].values())) if venue=='kraken' else data
 bids=book['bids'];asks=book['asks']
 if not bids or not asks:raise ValueError('one-sided book')
 import math
 for levels in (bids,asks):
  for r in levels:
   if not all(math.isfinite(float(v)) and float(v)>0 for v in r[:2]):raise ValueError('invalid book')
 if max(float(r[0]) for r in bids)>min(float(r[0]) for r in asks):raise ValueError('crossed book')
def main():
 start=time.time();store=Store()
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:receipts=list(pool.map(fetch,jobs()))
 for r in receipts:
  if r.get('payload') and ('depth' in r['label'] or r['label']=='USD_USDT_conversion'):
   try:validate_book(r['payload'],'kraken' if 'kraken' in r['label'] else 'binance')
   except (ValueError,KeyError,StopIteration,TypeError) as e:r['validation_error']=str(e)
 good=sum('error' not in r and 'validation_error' not in r for r in receipts)
 doc={'kind':'APEX microcap public collection','mode':MANIFEST['mode'],'state':'collected' if good==len(receipts) else 'collection_with_errors','revision':REVISION,'started_ts':start,'finished_ts':time.time(),'assets':MANIFEST['assets'],'coverage':MANIFEST['coverage'],'account_eligibility':'unverified','fees':'unverified account-level costs','shorting':MANIFEST['shorting'],'successful_requests':good,'total_requests':len(receipts),'receipts':receipts}
 name='microcap/receipts/'+REVISION[:12]+'/'+str(int(start))+'-'+uuid.uuid4().hex[:8]+'.json'
 store.put(name,doc,0)
 print(json.dumps({'state':doc['state'],'receipt':name,'successful_requests':good,'total_requests':len(receipts),'elapsed_seconds':doc['finished_ts']-start,'revision':REVISION,'orders_submitted':0}),flush=True)
 if good<len(receipts):raise SystemExit(1)
if __name__=='__main__':main()
