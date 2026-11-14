"""Live public spot quotes + virtual calibration orders. NO transaction methods.

The owner authorized live paper data on 2026-10-25. This separate program never
uses an account, wallet, signing key, approval, swap-build or broadcast endpoint.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
from decimal import Decimal, localcontext, ROUND_CEILING
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import ssl
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')
WETH='0x4200000000000000000000000000000000000006'
USDC='0x833589fcd6edb6e08f4c7c32d4f71b54bda02913'
RPCS=['https://mainnet.base.org','https://base-rpc.publicnode.com','https://base.drpc.org']
DEX={
 'uniswap':dict(factory='0x33128a8fc17869897dce68ed026d694621f6fdfd',quoter='0x3d4e44eb1374240ce5f1b871ab261cd16335b76a',fees=[100,500,3000]),
 'pancakeswap':dict(factory='0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865',quoter='0xb048bbc1ee6b733fffcfb9e9cef7375518e25997',fees=[100,500,2500]),
}
ACTIVE=('uniswap','pancakeswap','velora','kyberswap')
MODEL=dict(name='live_quote_calibration_v1',starting_cash_usdc='1000',order_size_usdc='25',
 slippage_haircut_bps=10,extra_execution_gas_units=80000,l1_fee_usdc_per_leg='0.01',
 minimum_order_delay_seconds=60,lp_fees='embedded in provider quote',
 gas='modeled from quoted gas units + assumed overhead, live gas price and quoted WETH/USDC conversion',
 accounting='USDC units; no USD peg assumption',purpose='execution/data calibration; no predictive trading edge claimed',
 actual_trading_fees_verified=False,real_money=False)
BLOCKED={
 'zerox':'Account email verified; normal login HTTP403. API key unavailable. Owner/provider action required.',
 'oneinch':'Commercial onboarding accepted; KYC initialization stalled. Commercial API agreement/key required.',
 'jupiter':'US exclusion in incorporated terms; API not queried.',
 'bisq':'Public market endpoint DNS resolution failed; no local market-data node configured. P2P settlement differs from AMM fills.',
 'dydx':'US account/interface restriction. No feed activated.',
 'gmx':'US account/interface restriction. No feed activated.',
 'hyperliquid':'US account/interface restriction. No feed activated.',
 'edgex':'US account/interface restriction. No feed activated.',
}

def stamp(t=None):
    x=dt.datetime.fromtimestamp(time.time() if t is None else t,dt.timezone.utc)
    return {'utc':x.isoformat(),'america_new_york':x.astimezone(NY).isoformat()}

def word(v):
    if isinstance(v,str): return v.removeprefix('0x').rjust(64,'0')
    if type(v) is not int or not 0<=v<2**256: raise ValueError('invalid_uint')
    return f'{v:064x}'

def uint(v):
    if isinstance(v,bool) or not str(v).isdigit(): raise ValueError('invalid_atomic_integer')
    n=int(v)
    if not 0<n<2**256: raise ValueError('nonpositive_or_overflow_amount')
    return n

def dec(v):
    x=Decimal(str(v))
    if not x.is_finite() or x<0: raise ValueError('invalid_nonnegative_decimal')
    return x

def atomic_write(path,obj):
    path=Path(path);tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,indent=2,allow_nan=False));os.replace(tmp,path)

class FetchError(Exception): pass

class Fetch:
    def __init__(self, quota_path=None):
        self.next={};self.lock=threading.Lock();self.quota_path=Path(quota_path) if quota_path else None
        self.count=json.loads(self.quota_path.read_text()) if self.quota_path and self.quota_path.exists() else {}
        # Use the installed OS trust bundle; certificate and hostname checks stay on.
        self.tls=ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').exists() else None)

    def json(self,url,data=None,headers=None,bucket='rpc'):
        host=urlsplit(url).netloc
        allowed={'mainnet.base.org','base-rpc.publicnode.com','base.drpc.org','api.velora.xyz','aggregator-api.kyberswap.com'}
        if urlsplit(url).scheme!='https' or host not in allowed: raise FetchError('endpoint_not_allowlisted')
        if bucket=='rpc': bucket='rpc:'+host
        if data is None and not ((host=='api.velora.xyz' and urlsplit(url).path=='/prices') or
                                 (host=='aggregator-api.kyberswap.com' and urlsplit(url).path=='/base/api/v1/routes')):
            raise FetchError('GET_path_not_allowlisted')
        if data is not None:
            if host not in {urlsplit(x).netloc for x in RPCS}: raise FetchError('POST_not_allowed')
            if data.get('method') not in {'eth_chainId','eth_getBlockByNumber','eth_getCode','eth_call','eth_gasPrice'}:
                raise FetchError('RPC_method_not_allowed')
        with self.lock:
            now=time.time();day=dt.datetime.now(dt.timezone.utc).date().isoformat()
            k=bucket+'|'+day;cap=4500 if bucket in ('velora','kyberswap') else 50000
            if self.count.get(k,0)>=cap: raise FetchError('daily_public_request_cap_reached')
            delay=self.next.get(bucket,0)-now
            if delay>15: raise FetchError('provider_in_backoff')
            if delay>0: time.sleep(delay)
            self.count[k]=self.count.get(k,0)+1
            if self.quota_path: atomic_write(self.quota_path,self.count)
            self.next[bucket]=time.time()+(.05 if bucket.startswith('rpc:') else 1.1)
        body=json.dumps(data).encode() if data is not None else None
        req=Request(url,data=body,headers={'User-Agent':'APEX-PaperData/1','Accept':'application/json',
                    'Cache-Control':'no-cache',**({'Content-Type':'application/json'} if body else {}),**(headers or {})})
        try:
            with urlopen(req,timeout=8,context=self.tls) as response:
                if urlsplit(response.geturl()).netloc!=host: raise FetchError('redirect_refused')
                raw=response.read(3_000_001)
                if len(raw)>3_000_000: raise FetchError('response_too_large')
                if float(response.headers.get('Age','0'))>30: raise FetchError('stale_HTTP_cache')
                result=json.loads(raw)
                return result
        except HTTPError as e:
            if e.code in (403,429):
                try: wait=float(e.headers.get('Retry-After','60'))
                except ValueError: wait=60
                self.next[bucket]=time.time()+max(60,min(wait,900))
            raise FetchError('HTTP_'+str(e.code)) from e

class Rpc:
    def __init__(self,fetch): self.fetch=fetch;self.url=None;self.pool_cache={}

    def call(self,method,params):
        if self.url is None:
            errors=[]
            for endpoint in RPCS:
                try:
                    d=self.fetch.json(endpoint,{'jsonrpc':'2.0','id':1,'method':'eth_chainId','params':[]})
                    if int(d['result'],16)!=8453: raise FetchError('wrong_chain')
                    self.url=endpoint;break
                except Exception as e:errors.append(type(e).__name__+':'+str(e)[:80])
            if self.url is None: raise FetchError('public_RPC_unavailable '+str(errors))
        try:
            d=self.fetch.json(self.url,{'jsonrpc':'2.0','id':1,'method':method,'params':params})
        except Exception:
            self.url=None
            raise
        if 'error' in d: raise FetchError('RPC_error '+str(d['error'])[:180])
        return d['result']

    def ethcall(self,address,data,tag): return self.call('eth_call',[{'to':address,'data':data},tag])

    def header(self,tag='latest'):
        h=self.call('eth_getBlockByNumber',[tag,False])
        if not h: raise FetchError('missing_block')
        age=time.time()-int(h['timestamp'],16)
        if tag=='latest' and not -5<=age<=30: raise FetchError('stale_or_future_RPC_head')
        return h

    def verify(self,sid,tag):
        if sid in self.pool_cache:return self.pool_cache[sid]
        c=DEX[sid]
        for address in [c['factory'],c['quoter'],USDC,WETH]:
            if self.call('eth_getCode',[address,tag]) in ('0x','0x0'):raise FetchError('missing_contract_code')
        if int(self.ethcall(USDC,'0x313ce567',tag),16)!=6 or int(self.ethcall(WETH,'0x313ce567',tag),16)!=18:
            raise FetchError('token_decimals_mismatch')
        actual='0x'+self.ethcall(c['quoter'],'0xc45a0155',tag)[-40:]
        if actual.lower()!=c['factory']:raise FetchError('quoter_factory_mismatch')
        pools=[]
        for fee in c['fees']:
            res=self.ethcall(c['factory'],'0x1698ee82'+word(USDC)+word(WETH)+word(fee),tag)
            address='0x'+res[-40:]
            if int(res,16)==0:continue
            tokens={'0x'+self.ethcall(address,s,tag)[-40:] for s in ['0x0dfe1681','0xd21220a7']}
            if {x.lower() for x in tokens}!={USDC,WETH}:raise FetchError('pool_token_mismatch')
            if int(self.ethcall(address,'0xddca3f43',tag),16)!=fee:raise FetchError('pool_fee_mismatch')
            pools.append((fee,address.lower()))
        if not pools:raise FetchError('no_verified_pools')
        self.pool_cache[sid]=pools;return pools

    def quote(self,sid,token_in,token_out,amount):
        h=self.header();tag=h['number'];outcomes=[];errors=[]
        for fee,pool in self.verify(sid,tag):
            try:
                data='0xc6a5026a'+word(token_in)+word(token_out)+word(amount)+word(fee)+word(0)
                res=self.ethcall(DEX[sid]['quoter'],data,tag).removeprefix('0x')
                if len(res)!=256:raise FetchError('unexpected_quoter_response')
                values=[int(res[i:i+64],16) for i in range(0,256,64)]
                if values[0]<=0 or values[3]<=0:raise FetchError('empty_quote')
                outcomes.append(dict(amount_out=str(values[0]),gas_units=values[3],pool=pool,pool_fee=fee))
            except Exception as e:errors.append(str(e)[:180])
        if not outcomes:raise FetchError('all_pool_quotes_failed '+str(errors))
        end=self.header(tag)
        if end['hash']!=h['hash']:raise FetchError('reorg_during_quote')
        q=max(outcomes,key=lambda x:int(x['amount_out']))
        q.update(source='direct_onchain_QuoterV2_eth_call',source_timestamp=int(h['timestamp'],16),
                 block_number=int(tag,16),block_hash=h['hash'],chain_id=8453,
                 pools=[q['pool']],scope='best_of_configured_single_pool_fee_tiers',pool_errors=errors)
        return q

def aggregator_quote(fetch,rpc,sid,token_in,token_out,amount):
    if sid=='velora':
        p=dict(srcToken=token_in,destToken=token_out,srcDecimals=6 if token_in==USDC else 18,
               destDecimals=6 if token_out==USDC else 18,amount=str(amount),network=8453,side='SELL',version='6.2',partner='apex-paper')
        raw=fetch.json('https://api.velora.xyz/prices?'+urlencode(p),bucket=sid)
        r=raw['priceRoute']
        if int(r['network'])!=8453 or r['srcToken'].lower()!=token_in or r['destToken'].lower()!=token_out or uint(r['srcAmount'])!=amount or r['side']!='SELL':
            raise FetchError('quote_intent_mismatch')
        h=rpc.header(hex(uint(r['blockNumber'])))
        pools=[]
        for branch in r.get('bestRoute',[]):
            for swap in branch.get('swaps',[]):
                for exchange in swap.get('swapExchanges',[]):pools.extend(exchange.get('poolAddresses',[]))
        return dict(source='Velora_public_prices_API',amount_out=str(uint(r['destAmount'])),
          gas_units=uint(r['gasCost']),source_timestamp=int(h['timestamp'],16),block_number=uint(r['blockNumber']),
          block_hash=h['hash'],chain_id=8453,pools=pools,raw_response=raw,
          reported_gas_usd=r.get('gasCostUSD'),additional_fee_attribution='unverified')
    p=dict(tokenIn=token_in,tokenOut=token_out,amountIn=str(amount),excludeRFQSources='true')
    raw=fetch.json('https://aggregator-api.kyberswap.com/base/api/v1/routes?'+urlencode(p),headers={'x-client-id':'apex-paper'},bucket=sid)
    if raw.get('code')!=0:raise FetchError('provider_error_'+str(raw.get('code')))
    r=raw['data']['routeSummary']
    if r['tokenIn'].lower()!=token_in or r['tokenOut'].lower()!=token_out or uint(r['amountIn'])!=amount:raise FetchError('quote_intent_mismatch')
    return dict(source='KyberSwap_public_routes_API',amount_out=str(uint(r['amountOut'])),gas_units=uint(r['gas']),
      source_timestamp=uint(r['timestamp']),block_number=None,block_hash=None,chain_id=8453,
      pools=[hop.get('pool') for branch in r.get('route',[]) for hop in branch if hop.get('pool')],raw_response=raw,
      reported_gas_usd=r.get('gasUsd'),reported_l1_fee_usd=r.get('l1FeeUsd'),additional_fee_attribution='unverified')

def validate_quote(q,now):
    uint(q['amount_in']);uint(q['amount_out'])
    if q['chain_id']!=8453:raise FetchError('wrong_quote_chain')
    if not -5<=now-q['source_timestamp']<=30:raise FetchError('stale_or_future_quote')
    if not 0<=now-q['requested_at']<=30:raise FetchError('slow_quote_request')
    if {q['token_in'],q['token_out']}!={USDC,WETH}:raise FetchError('wrong_quote_tokens')

def initial_paper():
    return dict(cash_atomic=1000*10**6,weth_atomic=0,pending=None,fills=0,closed_roundtrips=0,
                modeled_realized_pnl_atomic=0,entry_cash_atomic=None,model=MODEL)

def paper_step(p,q,now,gas_price):
    """A scheduled order needs a later fresh observation; never fill from a fixture."""
    validate_quote(q,now);p=copy.deepcopy(p);event=None
    if not p['pending']:
        p['pending']=dict(side='buy',created_at=now,earliest_fill_at=now+60,
                          decision_quote_id=q['quote_id'],notional_atomic=25*10**6)
        return p,None
    order=p['pending']
    if now<order['earliest_fill_at']:return p,None
    if q['source_timestamp']<=order['created_at']:raise FetchError('quote_precedes_paper_order')
    buy=order['side']=='buy'
    if q['token_in']!=(USDC if buy else WETH):raise FetchError('paper_direction_mismatch')
    amount=25*10**6 if buy else p['weth_atomic']
    if int(q['amount_in'])!=amount:raise FetchError('paper_amount_mismatch')
    output=int(q['amount_out'])*9990//10000
    with localcontext() as ctx:
        ctx.prec=100
        # Convert estimated native gas into USDC through this actual size quote.
        px=(Decimal(amount)/10**6)/(Decimal(q['amount_out'])/10**18) if buy else (Decimal(q['amount_out'])/10**6)/(Decimal(amount)/10**18)
        cost=(Decimal(q['gas_units']+80000)*Decimal(gas_price)/10**18*px+Decimal('0.01'))*10**6
        gas_atomic=int(cost.to_integral_value(rounding=ROUND_CEILING))
    before=p['cash_atomic']
    if buy:
        if before<amount+gas_atomic:raise FetchError('paper_cash_insufficient')
        p['entry_cash_atomic']=before;p['cash_atomic']-=amount+gas_atomic;p['weth_atomic']=output
        p['pending']=dict(side='sell',created_at=now,earliest_fill_at=now+60,decision_quote_id=q['quote_id'])
    else:
        if amount<=0:raise FetchError('paper_inventory_missing')
        p['cash_atomic']+=output-gas_atomic;p['weth_atomic']=0;p['closed_roundtrips']+=1
        p['modeled_realized_pnl_atomic']+=p['cash_atomic']-p['entry_cash_atomic']
        p['pending']=None;p['entry_cash_atomic']=None
    p['fills']+=1
    event=dict(type='SIMULATED_PAPER_FILL_FROM_LIVE_QUOTE',time=stamp(now),side='buy' if buy else 'sell',
      quote_id=q['quote_id'],decision_quote_id=order['decision_quote_id'],decision_time=stamp(order['created_at']),
      minimum_delay_seconds=60,source_timestamp=q['source_timestamp'],source=q['source'],block_number=q.get('block_number'),
      block_hash=q.get('block_hash'),input_atomic=str(amount),quoted_output_atomic=q['amount_out'],
      simulated_output_atomic=str(output),modeled_gas_cost_usdc=str(Decimal(gas_atomic)/10**6),
      cash_usdc_after=str(Decimal(p['cash_atomic'])/10**6),weth_atomic_after=str(p['weth_atomic']),
      model=MODEL,actual_execution=False,actual_pnl_verified=False)
    return p,event

class App:
    def __init__(self,out,registry,interval=60):
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
        self.registry=Path(registry);self.interval=max(60,interval);self.fetch=Fetch(self.out/'request-quotas.json');self.rpc=Rpc(self.fetch)
        self.guard=threading.Lock();self.stop=threading.Event();self.cycle=0
        path=self.out/'paper-state.json'
        self.paper=json.loads(path.read_text()) if path.exists() else {sid:initial_paper() for sid in ACTIVE}
        # Durable fill journal repairs a restart between recording a fill and saving balances.
        for journal in sorted(self.out.glob('paper-fills-*.jsonl')):
            for line in journal.read_text().splitlines():
                event=json.loads(line);sid=event.get('provider');after=event.get('paper_state_after')
                if sid in self.paper and after and after['fills']>self.paper[sid]['fills']:self.paper[sid]=after
        self.status=dict(title='APEX live paper data',created=stamp(),updated=stamp(),paper_only=True,
          prepared_by='Codex',status_revision='live paper calibration r1',interval_seconds=self.interval,
          cycle=0,services={},instructions='Complete only the setup steps in the right-hand panel.',model=MODEL)
        if (self.out/'status.json').exists():
            previous=json.loads((self.out/'status.json').read_text())
            self.status['created']=previous['created'];self.status['services']=previous['services']
            self.cycle=previous.get('cycle',0)
        self.files=dict(quotes='quotes-YYYY-MM-DD.jsonl',fills='paper-fills-YYYY-MM-DD.jsonl',state='paper-state.json')

    def append(self,prefix,row):
        date=dt.datetime.now(dt.timezone.utc).date().isoformat()
        with (self.out/f'{prefix}-{date}.jsonl').open('a') as f:
            f.write(json.dumps(row,allow_nan=False)+'\n');f.flush()
            if prefix=='paper-fills':os.fsync(f.fileno())

    def quote(self,sid,token_in,token_out,amount):
        started=time.time()
        q=self.rpc.quote(sid,token_in,token_out,amount) if sid in DEX else aggregator_quote(self.fetch,self.rpc,sid,token_in,token_out,amount)
        q.update(provider=sid,type='ACTUAL_PUBLIC_MARKET_QUOTE',requested_at=started,received_at=time.time(),
                 observed=stamp(),amount_in=str(amount),token_in=token_in,token_out=token_out,
                 token_in_decimals=6 if token_in==USDC else 18,token_out_decimals=6 if token_out==USDC else 18,
                 actual_execution=False)
        q['quote_id']=hashlib.sha256(json.dumps(q,sort_keys=True).encode()).hexdigest()
        self.append('quotes',q)  # Preserve actual responses even when rejected for age.
        validate_quote(q,time.time())
        return q

    def tick(self):
        self.cycle+=1;services={}
        try: gas=uint(int(self.rpc.call('eth_gasPrice',[]),16))
        except Exception as e:
            gas=None;self.append('events',dict(time=stamp(),error='gas_unavailable:'+str(e)[:180]))
        for sid in ACTIVE:
            old=self.status.get('services',{}).get(sid,{})
            try:
                p=self.paper[sid]
                buy=self.quote(sid,USDC,WETH,25*10**6)
                sell=self.quote(sid,WETH,USDC,p['weth_atomic'] if p['weth_atomic'] else int(buy['amount_out']))
                current=sell if p['weth_atomic'] else buy
                if gas is None:raise FetchError('gas_unavailable_paper_fill_paused')
                updated,event=paper_step(p,current,time.time(),gas)
                self.paper[sid]=updated
                if event:
                    event['provider']=sid;event['paper_state_after']=updated
                    event['fill_id']=hashlib.sha256((sid+event['decision_quote_id']+event['side']).encode()).hexdigest()
                    self.append('paper-fills',event)
                services[sid]=dict(state='LIVE_QUOTES_PAPER_ONLY',last_success=stamp(),source_cutoff=stamp(min(buy['source_timestamp'],sell['source_timestamp'])),
                  quote_count=old.get('quote_count',0)+2,last_buy={k:v for k,v in buy.items() if k!='raw_response'},
                  last_sell={k:v for k,v in sell.items() if k!='raw_response'},paper=updated,
                  quoted_roundtrip_usdc=str(Decimal(sell['amount_out'])/10**6) if not p['weth_atomic'] else None,
                  actual_fees_verified=False,actual_profitability='UNKNOWN',
                  paper_warning='Calibration round trips, not a validated profitable strategy; costs are modeled.')
            except Exception as e:
                services[sid]=dict(state='DATA_ERROR_PAPER_PAUSED',error=type(e).__name__+':'+str(e)[:250],
                                  last_success=old.get('last_success'),quote_count=old.get('quote_count',0),paper=self.paper[sid])
                self.append('events',dict(provider=sid,time=stamp(),error=services[sid]['error']))
        for sid,reason in BLOCKED.items():services[sid]=dict(state='BLOCKED_NO_LIVE_DATA',reason=reason)
        state=dict(self.status,updated=stamp(),cycle=self.cycle,services=services,files=self.files,
                   data_directory=str(self.out),process_id=os.getpid(),network_requests_today={str(k):v for k,v in self.fetch.count.items()})
        with self.guard:self.status=state
        atomic_write(self.out/'status.json',state);atomic_write(self.out/'paper-state.json',self.paper)

    def run(self):
        while not self.stop.is_set():
            started=time.monotonic()
            try:self.tick()
            except Exception as e:self.append('events',dict(time=stamp(),error='cycle_failure:'+str(e)[:300]))
            self.stop.wait(max(1,self.interval-(time.monotonic()-started)))

def serve(app,port):
    html=(Path(__file__).parent/'paper_dashboard.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/':data,ctype=html,'text/html; charset=utf-8'
            elif self.path=='/api/status':
                with app.guard:data=json.dumps(app.status,allow_nan=False).encode()
                ctype='application/json'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    threading.Thread(target=app.run,daemon=True).start()
    def end(*_):app.stop.set();threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
    server.serve_forever();app.stop.set();server.server_close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True);p.add_argument('--registry',required=True)
    p.add_argument('--port',type=int,default=8766);p.add_argument('--once',action='store_true')
    args=p.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    lock=(out/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    app=App(out,args.registry)
    if args.once:app.tick();print(json.dumps(app.status,indent=2));return
    serve(app,args.port)

if __name__=='__main__':main()
