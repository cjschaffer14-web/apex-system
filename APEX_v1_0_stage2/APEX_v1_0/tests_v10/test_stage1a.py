from __future__ import annotations
import csv, gzip, hashlib, json, sqlite3, unittest, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class Stage1A(unittest.TestCase):
    def test_parent_stage1_immutable(self):
        self.assertEqual(hashlib.sha256((ROOT/'stage1/STAGE1_MANIFEST.json').read_bytes()).hexdigest(),
                         'a4591d7e7e501232c50658b0019061b7029d74b56bd40a5fec614f616749f8ee')
        self.assertEqual(hashlib.sha256((ROOT/'ledger/trial_ledger.jsonl').read_bytes()).hexdigest(),
                         '70661932c844e427c69ca7afb46fdc0a135920987129e77cea1f0ef02b529d3e')
        self.assertEqual(hashlib.sha256((ROOT/'data_v10/market_2026-10-03_v10.sqlite').read_bytes()).hexdigest(),
                         '2b5f420cebe5823f1e11653ffdcfaf548364d8c2ee4de923d2183d9721ac7e8e')

    def test_stage1a_database_and_h41(self):
        man=json.loads((ROOT/'data_v10/DB_MANIFEST_1A.json').read_text())
        db=ROOT/man['file']
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), man['file_sha256'])
        con=sqlite3.connect(db)
        try:
            self.assertEqual(con.execute('pragma integrity_check').fetchone()[0],'ok')
            self.assertEqual(con.execute('select count(*) from pragma_foreign_key_check').fetchone()[0],0)
            self.assertEqual(con.execute("select count(*) from macro_observations where source='fed_h41_first_release'").fetchone()[0],666)
            self.assertEqual(con.execute("select count(*) from macro_observations where source='fed_h41_first_release' and value_vintage_quality='first_release' and availability_quality='exact_release'").fetchone()[0],666)
            self.assertEqual(con.execute('select count(*) from macro_revisions where first_release_value!=latest_value').fetchone()[0],0)
            self.assertEqual(con.execute('select count(*) from macro_revisions where second_release_value is not null and first_release_value!=second_release_value').fetchone()[0],0)
            self.assertEqual(con.execute("select value_vintage_quality from vintage_policy where family='macro:treasury_fiscaldata:tga_closing_balance'").fetchone()[0],'unverified')
            self.assertEqual(con.execute("select value_vintage_quality from vintage_policy where family='macro:treasury_yields:par_yield_10y'").fetchone()[0],'market_record')
            self.assertEqual(con.execute("select value_vintage_quality from vintage_policy where family='macro:cboe:vix_close'").fetchone()[0],'market_record')
            self.assertTrue(all(r[0]=='market_record' for r in con.execute('select distinct value_vintage_quality from funding_events')))
        finally: con.close()

    def test_h41_all_archived_pages_parse(self):
        from apex_v10.data.sources.h41_releases import parse_release
        audit=json.loads((ROOT/'data_v10/raw_1a/H41_FETCH_AUDIT_1A.json').read_text())
        self.assertEqual(len(audit),666)
        self.assertFalse([a for a in audit if a.get('status')!='ok'])
        man=[json.loads(x) for x in (ROOT/'data_v10/raw_1a/MANIFEST.jsonl').read_text().splitlines()]
        bysha={r['sha256']:r for r in man}
        for a in audit:
            r=bysha[a['sha256']]
            body=gzip.decompress((ROOT/'data_v10/raw_1a'/r['path']).read_bytes())
            x=parse_release(body)
            self.assertEqual(x.wednesday.isoformat(), a['wednesday'])

    def test_evidence_gate_fail_closed(self):
        gate=json.loads((ROOT/'reports/coverage_gate_evidence_v10_1a.json').read_text())['families']
        self.assertTrue(all(x['status']=='PASS' for x in gate['macro:fed_h41_first_release:RESPPMA_N.WW']['windows'].values()))
        self.assertTrue(all(x['status']=='FAIL' for x in gate['macro:fed_h41:RESPPMA_N.WW']['windows'].values()))
        self.assertTrue(all(x['status']=='FAIL' for x in gate['macro:treasury_fiscaldata:tga_closing_balance']['windows'].values()))
        self.assertEqual(gate['macro:treasury_yields:par_yield_10y']['windows']['v09_btc_full']['status'],'PASS')
        self.assertEqual(gate['macro:cboe:vix_close']['windows']['v09_btc_full']['status'],'PASS')
        self.assertEqual(gate['macro:nyfed:rrp_total_accepted']['windows']['pre_2022']['status'],'PARTIAL')
        self.assertEqual(gate['macro:nyfed:rrp_total_accepted']['windows']['post_2022']['status'],'PASS')

    def test_forensic_outcomes_complete(self):
        files=['forensic_adhoc_outcomes.json','forensic_owner_outcomes.json','forensic_v05_outcomes.json','forensic_v051_outcomes.json']
        rows=[]
        for f in files: rows.extend(json.loads((ROOT/'stage1a'/f).read_text()))
        self.assertEqual(len(rows),148)
        from collections import Counter
        c=Counter(r['status'] for r in rows)
        self.assertEqual(c, {'reproduced_series':59,'reproduced_statistic_only':86,'mismatch':3})
        bad={r['trial_id'] for r in rows if r['status']=='mismatch'}
        self.assertEqual(bad,{
            'adhoc-2026-10-02|ETH-USD|walk_forward|hourly|fee80',
            'adhoc-2026-10-02|ETH-USD|walk_forward|hourly|fee40',
            'adhoc-2026-10-02|ETH-USD|walk_forward|hourly|fee5'})

    def test_ledger_1a(self):
        summary=json.loads((ROOT/'ledger/LEDGER_SUMMARY_1A.json').read_text())
        self.assertEqual(summary['records'],1483)
        self.assertEqual(summary['global_conservative_n'],1483)
        self.assertEqual(summary['forensic_paths_recovered'],59)
        self.assertEqual(summary['forensic_statistic_only'],86)
        self.assertEqual(summary['forensic_unavailable'],3)
        self.assertGreater(summary['comparable_sets'],0)
        lines=[json.loads(x) for x in (ROOT/'ledger/trial_ledger_1a.jsonl').read_text().splitlines() if x.strip()]
        self.assertEqual(len(lines),1483)
        self.assertEqual(len({r['trial_id'] for r in lines}),1483)
        # Every Stage 1 identity-defining field is unchanged in 1A.
        base={r['trial_id']:r for r in (json.loads(x) for x in (ROOT/'ledger/trial_ledger.jsonl').read_text().splitlines() if x.strip())}
        fields=('source_version','family','name','parameters','asset','venue','product','code_sha256','spec_sha256','data_sha256','window','cost_model_id')
        for r in lines:
            self.assertEqual({k:r[k] for k in fields},{k:base[r['trial_id']][k] for k in fields})

    def test_cscv_matrices_and_dsr_inputs(self):
        sets=json.loads((ROOT/'reports/comparable_sets_1a.json').read_text())
        self.assertGreaterEqual(len(sets),1)
        for s in sets:
            raw=(ROOT/s['matrix_ref']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),s['matrix_sha256'])
            rows=gzip.decompress(raw).decode().splitlines()
            self.assertEqual(len(rows)-1,s['rows'])
            self.assertEqual(len(rows[0].split(','))-1,s['distinct_columns'])
            self.assertGreaterEqual(s['distinct_columns'],2)
        import io
        rows=list(csv.DictReader(io.StringIO((ROOT/'reports/dsr_inputs_1a.csv').read_text())))
        self.assertEqual(len(rows),277)
        self.assertTrue(all(int(r['global_n'])==1483 for r in rows))
        self.assertTrue(all(int(r['family_n'])>=1 for r in rows))
        self.assertTrue(all(r['objective_metric']=='annualized_sharpe' for r in rows))
        self.assertTrue(all(float(r['kurtosis_pearson'])>=0 for r in rows))

if __name__=='__main__': unittest.main()
