import unittest
import tempfile
from dataclasses import replace
from decimal import Decimal as D
from unittest.mock import patch
from .connectivity.markets import SpotMarket, coinbase_markets, kraken_markets, pair_name
from .connectivity.public import CoinbaseConnector, KrakenConnector
from .connectivity.runner import run
from .execution.routing import SpotIntent, SpotRouter
from .core import Book, Level
from .test_connectivity import books, T


class MultiMarketTests(unittest.TestCase):
    def market(self, venue):
        return SpotMarket(venue, 'BTC/USD', 'BTCUSD', D('.001'), D('.01'), D('.001'), D('1'), True, T)

    def route(self, rows=None, balances=None, intent=None):
        rows = books(10) if rows is None else rows
        markets = {(s.economic_venue_id,'BTC/USD'):self.market(s.economic_venue_id) for s in rows}
        if balances is None:
            balances={(s.economic_venue_id,a):D(10000) for s in rows for a in ('BTC','USD')}
        return SpotRouter().route(intent or SpotIntent('strategy-1','BTC/USD','buy',D(1),D(200),D(20)),
                                  rows,markets,balances,T+2)

    def test_discovery_filters_and_aliases(self):
        row={'base_currency':'SOL','quote_currency':'USDC','id':'SOL-USDC','status':'online',
             'base_increment':'.01','quote_increment':'.001','min_market_funds':'1'}
        parsed=coinbase_markets([row,{**row,'id':'x','cancel_only':True}],T)
        self.assertEqual(list(parsed),['SOL/USDC'])
        self.assertEqual(parsed['SOL/USDC'].base_increment,D('.01'))
        self.assertNotEqual(pair_name('BTC/USDC'),pair_name('BTC/USD'))
        self.assertEqual(pair_name('XBT/EUR'),'BTC/EUR')

    def test_kraken_discovered_symbol_used(self):
        calls=[]
        def transport(url):
            calls.append(url)
            if url.endswith('AssetPairs'):
                return {'error':[],'result':{'XSOLZUSD':{'status':'online','wsname':'SOL/USD','altname':'SOLUSD',
                    'lot_decimals':3,'pair_decimals':2,'ordermin':'.01','costmin':'1'}}},T,T+1
            return {'error':[],'result':{'SOLUSD':{'bids':[['100','2','0']],'asks':[['101','2','0']]}}},T,T+1
        s=KrakenConnector(10,transport).snapshot('SOL/USD')
        self.assertEqual(s.book.pair,'SOL/USD')
        self.assertIn('pair=SOLUSD',calls[-1])
        self.assertEqual(len(calls),2)

    def test_order_route_uses_net_cost_and_local_balance(self):
        r=self.route()
        self.assertEqual(r['selected']['venue'],'coinbase_spot')
        self.assertEqual(D(r['selected']['base_quantity']),1)
        self.assertEqual(D(r['selected']['effective_quote']),D('100.100'))
        self.assertFalse(r['submitted'])
        r=self.route(balances={('coinbase_spot','USD'):D(0),('kraken_spot','USD'):D(1000)})
        self.assertEqual(r['selected']['venue'],'kraken_spot')
        self.assertTrue(any(x['reason']=='insufficient venue-local balance' for x in r['rejected']))

    def test_fee_can_reverse_best_venue(self):
        a,b=books(10)
        b=replace(b,book=replace(b.book,asks=[Level(D('99.9'),D(5))]),fee_bps=100)
        self.assertEqual(self.route([a,b])['selected']['venue'],'coinbase_spot')

    def test_sell_routes_max_net_proceeds(self):
        r=self.route(intent=SpotIntent('sell','BTC/USD','sell',D(1),D(200),D(20)))
        self.assertEqual(r['selected']['venue'],'kraken_spot')
        self.assertEqual(r['selected']['reserve_asset'],'BTC')

    def test_invalid_and_missing_inputs_do_not_route(self):
        self.assertIsNone(self.route(books(None))['selected'])
        rows=[replace(x,request_ns=1,received_ns=2) for x in books()]
        self.assertIsNone(self.route(rows)['selected'])
        self.assertIsNone(self.route(intent=SpotIntent('small','BTC/USD','buy',D('.0001'),D(200),D(20)))['selected'])
        self.assertIsNone(self.route(intent=SpotIntent('cap','BTC/USD','buy',D(1),D(100),D(20)))['selected'])
        self.assertIsNone(self.route(balances={})['selected'])

    def test_duplicate_book_not_independent_route(self):
        a=books()[0]
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.route([a,a])

    def test_multimarket_runner_keeps_all_pairs_and_censors_separately(self):
        def poll(_, pair):
            return [replace(s,book=replace(s.book,pair=pair)) for s in books()],{}
        with tempfile.TemporaryDirectory() as out, patch('apex_v2.connectivity.runner.PublicSnapshotStream.poll',poll), patch('apex_v2.connectivity.runner.time.time_ns',return_value=T+2):
            result=run(1,1,out,pairs=('BTC/USD','ETH/USD','SOL/USD'))
        self.assertEqual(len(result['samples']),3)
        self.assertEqual(result['candidate_records'],3)
        self.assertEqual(result['outcome_records'],3)
        self.assertFalse(result['orders_authorized'])


if __name__=='__main__': unittest.main()
