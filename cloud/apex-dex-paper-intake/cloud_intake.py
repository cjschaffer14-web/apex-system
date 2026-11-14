"""Private scheduled HTTP intake, generation-guarded cloud state and immutable observations.
No trade/sign/build endpoint, financial credentials, or local computer dependency.
"""
import copy, datetime as dt, hashlib, json, os, ssl, tempfile, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from paper_live import App, Fetch, FetchError, Rpc, RPCS, ACTIVE, stamp, atomic_write

CONTROL='control/checkpoint.json'
class Conflict(Exception):pass
class Missing(Exception):pass
class Store:
    def __init__(self,bucket):
        self.bucket=bucket;self.token=None;self.expiry=0;self.tls=ssl.create_default_context()
    def auth(self):
        if time.time()+90>=self.expiry:
            req=Request('http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',headers={'Metadata-Flavor':'Google'})
            with urlopen(req,timeout=4) as r:d=json.load(r)
            self.token=d['access_token'];self.expiry=time.time()+d['expires_in']
        return self.token
    def request(self,url,body=None):
        req=Request(url,data=body,headers={'Authorization':'Bearer '+self.auth(),'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=10,context=self.tls) as r:return json.load(r)
        except HTTPError as e:
            if e.code==412:raise Conflict('generation_conflict') from e
            if e.code==404:raise Missing('object_missing') from e
            raise RuntimeError('storage_HTTP_'+str(e.code)) from e
    def get(self,key):
        url='https://storage.googleapis.com/storage/v1/b/'+self.bucket+'/o/'+quote(key,safe='')
        for _ in range(3):
            meta=self.request(url);gen=int(meta['generation'])
            try:return self.request(url+'?alt=media&ifGenerationMatch='+str(gen)),gen
            except Conflict:continue
        raise Conflict('read_changed_repeatedly')
    def put(self,key,value,generation):
        url='https://storage.googleapis.com/upload/storage/v1/b/'+self.bucket+'/o?'+urlencode(dict(uploadType='media',name=key,ifGenerationMatch=generation))
        data=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
        result=self.request(url,data);return int(result['generation'])

class BudgetFetch(Fetch):
    def __init__(self,path,deadline):super().__init__(path);self.deadline=deadline;self.calls={}
    def json(self,url,data=None,headers=None,bucket='rpc'):
        if time.monotonic()+9>self.deadline:raise FetchError('cloud_cycle_deadline')
        from urllib.parse import urlsplit
        key='rpc:'+urlsplit(url).netloc if bucket=='rpc' else bucket
        limit=128 if key.startswith('rpc:') else 2
        if self.calls.get(key,0)>=limit:raise FetchError('cycle_request_budget_reached')
        self.calls[key]=self.calls.get(key,0)+1
        return super().json(url,data,headers,bucket)

class Engine:
    def __init__(self,store):self.store=store;self.lock=threading.Lock();self.pool_cache={}
    def collect(self,now=None):
        now=time.time() if now is None else now
        slot=int(now//60)
        if not self.lock.acquire(blocking=False):return {'result':'busy'},200
        try:
            c,gen=self.store.get(CONTROL)
            if c['mode'] not in ('active','probe'):return {'result':'paused','mode':c['mode']},200
            if c.get('last_slot',-1)>=slot:return {'result':'already_committed','slot':slot},200
            if c.get('lease',{}).get('expires',0)>now:return {'result':'lease_busy'},200
            owner=uuid.uuid4().hex
            claimed=copy.deepcopy(c);claimed['lease']={'owner':owner,'expires':now+100,'slot':slot}
            day=dt.datetime.fromtimestamp(now,dt.timezone.utc).date().isoformat()
            # Reserve worst-case request budgets durably before any provider call. Failed
            # cycles keep their reservation; successful cycles refund unused requests.
            baseline=copy.deepcopy(c.get('quotas',{}));reserved=copy.deepcopy(baseline)
            for bucket,amount,cap in [('velora',2,4500),('kyberswap',2,4500)]+[('rpc:'+x.split('/')[2],128,50000) for x in RPCS]:
                key=bucket+'|'+day
                if reserved.get(key,0)+amount>cap:return {'result':'daily_quota_paused','bucket':bucket},200
                reserved[key]=reserved.get(key,0)+amount
            claimed['quotas']=reserved
            try:claim_gen=self.store.put(CONTROL,claimed,gen)
            except Conflict:return {'result':'claim_conflict'},200
            records={};started=time.time()
            with tempfile.TemporaryDirectory() as work:
                root=Path(work)
                atomic_write(root/'paper-state.json',c['paper'])
                atomic_write(root/'status.json',c['status'])
                atomic_write(root/'request-quotas.json',baseline)
                app=App(root,root/'unused-registry.json')
                app.fetch=BudgetFetch(root/'request-quotas.json',time.monotonic()+45);app.rpc=Rpc(app.fetch)
                app.fetch.next=copy.deepcopy(c.get('backoffs',{}))
                app.rpc.pool_cache=copy.deepcopy(self.pool_cache)
                if c['mode']=='probe':
                    for p in app.paper.values():p['pending']=None
                app.tick();self.pool_cache=copy.deepcopy(app.rpc.pool_cache)
                for prefix in ['quotes','paper-fills','events']:
                    records[prefix]=[json.loads(line) for p in root.glob(prefix+'-*.jsonl') for line in p.read_text().splitlines()]
                if c['mode']=='probe':
                    app.paper=c['paper'];records['paper-fills']=[]
                    for sid in ACTIVE:
                        if sid in app.status['services']:app.status['services'][sid]['paper']=app.paper[sid]
                app.status.update(location='Google Cloud / us-central1',intake_mode=c['mode'],
                    status_revision='cloud live paper intake r1',cloud_service=os.environ.get('K_SERVICE','test'),
                    cloud_revision=os.environ.get('K_REVISION','test'),cloud_instance=os.environ.get('HOSTNAME','unknown'),
                    data_directory='gs://'+self.store.bucket+'/',files={'checkpoint':CONTROL,'observations':'cycles/YYYY-MM-DD/*.json'},
                    collector_started=stamp(started),collector_duration_seconds=round(time.time()-started,3),
                    local_computer_required=False)
                app.status.pop('process_id',None)
                if c.get('cloud_activated'):app.status['cloud_activated']=c['cloud_activated']
                next_state=copy.deepcopy(claimed)
                next_state.update(paper=app.paper,status=app.status,quotas=app.fetch.count,backoffs=app.fetch.next,
                    lease={},last_slot=slot,last_commit='cycles/'+day+'/'+str(slot)+'-'+owner+'.json')
                archive=dict(schema=1,phase=c['mode'],slot=slot,owner=owner,created=stamp(),
                    previous_commit=c.get('last_commit'),quotes=records['quotes'],paper_fills=records['paper-fills'],
                    events=records['events'],checkpoint_after=next_state)
                # The observation object is immutable. Only checkpoint CAS makes it canonical.
                self.store.put(next_state['last_commit'],archive,0)
                try:self.store.put(CONTROL,next_state,claim_gen)
                except Conflict:return {'result':'uncommitted_lease_lost','slot':slot},409
                result={'result':'committed','phase':c['mode'],'slot':slot,
                        'quotes':len(records['quotes']),'simulated_fills':len(records['paper-fills']),
                        'live_sources':[sid for sid in ACTIVE if app.status['services'][sid]['state']=='LIVE_QUOTES_PAPER_ONLY'],
                        'commit':next_state['last_commit']}
                print(json.dumps(result),flush=True);return result,200
        except Missing:return {'result':'not_seeded'},503
        finally:self.lock.release()

HTML=(Path(__file__).parent/'paper_dashboard.html').read_bytes()
def serve():
    store=Store(os.environ['INTAKE_BUCKET']);engine=Engine(store)
    class Handler(BaseHTTPRequestHandler):
        def send(self,value,code=200,ctype='application/json'):
            raw=value if isinstance(value,bytes) else json.dumps(value).encode()
            self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=='/':return self.send(HTML,ctype='text/html; charset=utf-8')
            if self.path=='/health':return self.send({'service':'apex-dex-paper-intake','paper_only':True})
            if self.path=='/api/status':
                try:c,_=store.get(CONTROL);return self.send(c['status'])
                except Missing:return self.send({'error':'not_seeded'},503)
                except Exception as e:print(type(e).__name__,flush=True);return self.send({'error':'storage_unavailable'},503)
            return self.send({'error':'not_found'},404)
        def do_POST(self):
            if self.path!='/collect':return self.send({'error':'not_found'},404)
            if int(self.headers.get('Content-Length','0'))>1024:return self.send({'error':'body_too_large'},413)
            try:result,code=engine.collect();return self.send(result,code)
            except Exception as e:print(json.dumps({'type':'collection_error','error':type(e).__name__}),flush=True);return self.send({'error':'collection_failed'},503)
        def log_message(self,*args):pass
    # Google Cloud Run IAM authenticates all inbound routes; no public invoker binding.
    ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
if __name__=='__main__':serve()
