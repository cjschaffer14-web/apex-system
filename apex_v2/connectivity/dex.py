"""V2 reserve quote adapter: exact raw-token arithmetic; never signs/sends.
Pool identity includes chain and contract, independently of RPC/source identity.
Only constant-product V2 pools with declared fee are supported.
TODO: v3 ticks, L1 data fees, token-transfer tax, reorg-aware multi-block archive.
"""
from dataclasses import dataclass
import re
import time
from ..dexdata.rpc import Rpc
from ..dexdata.univ2 import get_amount_out
from ..dexdata.collect import word, dec_addr
from ..economics.formulas import finite

@dataclass(frozen=True)
class CurveSnapshot:
    chain_id: int
    pool: str
    token0: str
    token1: str
    reserve0: int
    reserve1: int
    fee_numerator: int
    fee_denominator: int
    block_number: int
    block_hash: str
    source_ns: int
    received_ns: int
    endpoint_id: str
    synthetic: bool = False
    @property
    def economic_venue_id(self): return f'dex:{self.chain_id}:{self.pool.lower()}'
    @property
    def source_id(self): return self.endpoint_id+':'+self.economic_venue_id
    def fresh(self, now_ns, max_age_s=10):
        finite(max_age_s)
        if max_age_s <= 0: raise ValueError('invalid age limit')
        if self.chain_id <= 0 or self.block_number < 0 or not self.block_hash:
            raise ValueError('invalid block identity')
        if self.token0 == self.token1 or min(self.reserve0,self.reserve1) <= 0:
            raise ValueError('invalid reserve curve')
        if not all(type(x) is int for x in (self.reserve0,self.reserve1,self.fee_numerator,self.fee_denominator)):
            raise ValueError('curve arithmetic requires integers')
        if not 0 < self.fee_numerator <= self.fee_denominator: raise ValueError('invalid pool fee')
        if self.source_ns <= 0 or self.received_ns < self.source_ns or self.received_ns > now_ns or now_ns-self.source_ns > max_age_s*1e9:
            raise ValueError('stale/future curve')
        return self
    def quote(self, token_in, amount_in):
        if type(amount_in) is not int or amount_in <= 0: raise ValueError('raw-token amount must be positive integer')
        if token_in == self.token0: rin,rout = self.reserve0,self.reserve1
        elif token_in == self.token1: rin,rout = self.reserve1,self.reserve0
        else: raise ValueError('token not in pool')
        return get_amount_out(amount_in,rin,rout,self.fee_numerator,self.fee_denominator)

class DexQuoteAdapter:
    def __init__(self, rpc_url, chain_id, pool, token0, token1, fee_numerator=997, fee_denominator=1000, endpoint_id='public_rpc', rpc=None):
        if not all(re.fullmatch(r'0x[0-9a-fA-F]{40}', a) for a in (pool,token0,token1)):
            raise ValueError('invalid contract address')
        self.rpc = rpc or Rpc([rpc_url], retries=1)
        self.chain_id,self.pool,self.token0,self.token1 = chain_id,pool.lower(),token0.lower(),token1.lower()
        self.fn,self.fd,self.endpoint_id = fee_numerator,fee_denominator,endpoint_id
    def snapshot(self, pair=None, block=None):
        rpc = self.rpc
        if int(rpc.call('eth_chainId',[]),16) != self.chain_id: raise ValueError('wrong RPC chain')
        header = block or rpc.call('eth_getBlockByNumber',['latest',False])
        tag = hex(int(header['number'],16))
        t0,t1,reserves = rpc.batch([('eth_call',[{'to':self.pool,'data':selector},tag]) for selector in ('0x0dfe1681','0xd21220a7','0x0902f1ac')])
        if any(isinstance(x,Exception) for x in (t0,t1,reserves)): raise ValueError('pool calls failed')
        if (dec_addr(t0).lower(),dec_addr(t1).lower()) != (self.token0,self.token1): raise ValueError('pool token mismatch')
        if len(reserves) != 194: raise ValueError('invalid reserve ABI')
        check = rpc.call('eth_getBlockByNumber',[tag,False])
        if check['hash'] != header['hash']: raise ValueError('reorg during reserve observation')
        result = CurveSnapshot(self.chain_id,self.pool,self.token0,self.token1,word(reserves,0),word(reserves,1),
                               self.fn,self.fd,int(tag,16),header['hash'],int(header['timestamp'],16)*10**9,time.time_ns(),self.endpoint_id)
        return result.fresh(time.time_ns())
