"""DSR and CSCV/PBO calculations from frozen Stage 1A inputs.

Global N is retained but it is not a substitute for unavailable Sharpe variance
across all 1,483 research trials. Report conditional sensitivities, never promote
a strategy based on incomplete dispersion evidence or on legacy flat costs.
"""
from __future__ import annotations
import csv, gzip, hashlib, itertools, json, math
from pathlib import Path
import numpy as np
from scipy.stats import norm, rankdata

FACTORS={'daily':365.,'weekly':52.,'hourly':8760.}


def expected_max_sharpe(n, variance):
    if isinstance(n,bool) or not isinstance(n,int) or n<1:
        raise ValueError('positive integer N required')
    if not math.isfinite(variance) or variance<0: raise ValueError('invalid variance')
    if n==1: return 0.
    gamma=0.5772156649015329
    return math.sqrt(variance)*((1-gamma)*norm.ppf(1-1/n)+gamma*norm.ppf(1-1/(n*math.e)))


def dsr(sr,t,skew,kurtosis,n,variance):
    if isinstance(t,bool) or not isinstance(t,int) or t<3: raise ValueError('T >= 3 required')
    if not all(math.isfinite(x) for x in (sr,skew,kurtosis)) or kurtosis<1:
        raise ValueError('invalid moments')
    benchmark=expected_max_sharpe(n,variance)
    denominator=1-skew*sr+(kurtosis-1)*sr*sr/4
    if denominator<=0: raise ValueError('nonpositive Sharpe variance')
    probability=float(norm.cdf((sr-benchmark)*math.sqrt(t-1)/math.sqrt(denominator)))
    return {'probability':probability,'benchmark_period_sharpe':float(benchmark),
            'N':n,'variance_period_sharpe':float(variance)}


def sharpe_columns(x):
    sd=x.std(axis=0,ddof=1); mean=x.mean(axis=0)
    if np.any((sd==0)&(mean!=0)): raise ValueError('nonzero constant return has undefined Sharpe')
    return np.divide(mean,sd,out=np.zeros_like(mean),where=sd>0)


def cscv(matrix, partitions=8):
    x=np.asarray(matrix,dtype=float)
    if x.ndim!=2 or x.shape[1]<2 or not np.isfinite(x).all():
        raise ValueError('finite aligned matrix with at least two strategies required')
    if isinstance(partitions,bool) or not isinstance(partitions,int) or partitions<2 or partitions%2:
        raise ValueError('even partition count required')
    rows=len(x)//partitions*partitions
    if rows<2*partitions: raise ValueError('at least two observations per partition required')
    # Trim only in memory; never rewrite the frozen matrix. Log the exact tail loss.
    x=x[:rows]; blocks=np.split(x,partitions)
    logits=[]; overfit=[]; tie_splits=0
    for selected in itertools.combinations(range(partitions),partitions//2):
        inside=sharpe_columns(np.concatenate([blocks[i] for i in selected]))
        outside=sharpe_columns(np.concatenate([blocks[i] for i in range(partitions) if i not in selected]))
        winners=np.flatnonzero(inside==inside.max())
        if len(winners)>1: tie_splits+=1
        ranks=rankdata(outside,method='average')
        # Resolve tied IS winners symmetrically, average their overfit indicators.
        omega=ranks[winners]/(x.shape[1]+1)
        lam=np.log(omega/(1-omega))
        logits.extend(float(v) for v in lam)
        overfit.append(float(np.mean(lam<=0)))
    return {'pbo':float(np.mean(overfit)),'partitions':partitions,'splits':len(overfit),
            'tie_splits':tie_splits,'rows_used':rows,'tail_rows_excluded':len(matrix)-rows,
            'columns':x.shape[1], 'logits':logits,
            'tie_policy':'average over tied IS winners; OOS average ranks; lambda <= 0 counts as overfit'}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(root,relative):
    p=(root/relative).resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('reference escapes project')
    return p


def run(root,output):
    root=Path(root).resolve(); output=Path(output).resolve()
    if output==root or output.is_relative_to(root/'reports'):
        raise ValueError('write results to a separate Stage 2 folder')
    inputs=root/'reports/dsr_inputs_1a.csv'; comp=root/'reports/comparable_sets_1a.json'
    families=root/'reports/selection_families_1a.json'
    with inputs.open(newline='') as f: raw=list(csv.DictReader(f))
    sets=json.loads(comp.read_text()); registry={x['family_id']:x for x in json.loads(families.read_text())}
    if len(raw)!=277 or len(sets)!=33: raise ValueError('expected exactly 277 DSR rows and 33 comparable matrices')
    if len({r['trial_id'] for r in raw})!=277: raise ValueError('duplicate trial')
    parsed=[]
    for r in raw:
        t=int(r['T']); n=int(r['family_n']); freq=r['frequency']; fam=r['selection_family_id']
        if int(r['global_n'])!=1483 or r['objective_metric']!='annualized_sharpe' or freq not in FACTORS:
            raise ValueError('unexpected research context')
        if n!=registry[fam]['alternatives_evaluated']: raise ValueError('family N disagrees with registry')
        sr=float(r['observed_sharpe_recomputed'])/math.sqrt(FACTORS[freq])*math.sqrt((t-1)/t)
        parsed.append({**r,'sr_period':sr,'T':t,'family_n':n})
    results=[]
    for r in parsed:
        family=[x for x in parsed if x['selection_family_id']==r['selection_family_id'] and x['frequency']==r['frequency']]
        byeq={x['return_equivalence_id']:x['sr_period'] for x in family}
        pool={x['return_equivalence_id']:x['sr_period'] for x in parsed if x['frequency']==r['frequency']}
        # Same-frequency global pool is only a sensitivity estimate, NOT full research dispersion.
        global_variance=float(np.var(list(pool.values()),ddof=1)) if len(pool)>1 else None
        family_variance=float(np.var(list(byeq.values()),ddof=1)) if len(byeq)>1 else (0. if r['family_n']==1 else None)
        def calc(n,var):
            if var is None: return {'status':'unavailable_dispersion','N':n}
            try: return {'status':'conditional_sensitivity',**dsr(r['sr_period'],r['T'],float(r['skew']),float(r['kurtosis_pearson']),n,var)}
            except ValueError as e: return {'status':'invalid_moments','N':n,'reason':str(e)}
        results.append({'trial_id':r['trial_id'],'selection_family_id':r['selection_family_id'],
                        'frequency':r['frequency'],'T':r['T'],'period_sharpe':r['sr_period'],
                        'global':calc(1483,global_variance),'family':calc(r['family_n'],family_variance),
                        'global_dispersion_observed_unique':len(pool),'family_dispersion_observed_unique':len(byeq),
                        'family_research_N':r['family_n'],'verdict':'structural_only',
                        'reason':'dispersion is observed subset; IID assumption; legacy costs not revalidated; no candidate promotion'})
    pbo=[]; parents={str(inputs.relative_to(root)):sha(inputs),str(comp.relative_to(root)):sha(comp),str(families.relative_to(root)):sha(families)}
    for entry in sets:
        p=safe_path(root,entry['matrix_ref']); digest=sha(p)
        if digest!=entry['matrix_sha256']: raise ValueError('matrix hash mismatch: '+entry['set_id'])
        parents[entry['matrix_ref']]=digest
        with gzip.open(p,'rt',newline='') as f:
            reader=csv.reader(f); header=next(reader); rows=list(reader)
        if header!=['ts']+entry['representative_columns'] or len(rows)!=entry['rows']:
            raise ValueError('matrix shape/columns mismatch')
        times=[int(r[0]) for r in rows]
        if any(b<=a for a,b in zip(times,times[1:])) or times[0]!=entry['first_ts'] or times[-1]!=entry['last_ts']:
            raise ValueError('matrix timestamp mismatch')
        x=np.asarray([[float(v) for v in row[1:]] for row in rows])
        if x.shape[1]!=entry['distinct_columns']: raise ValueError('matrix column count mismatch')
        try: record={'status':'computed',**cscv(x)}
        except ValueError as e: record={'status':'unavailable','reason':str(e)}
        pbo.append({'set_id':entry['set_id'],'matrix_sha256':digest,
                    'selection_family_id':entry['selection_family_id'],'global_research_N':1483,
                    'family_research_N':registry[entry['selection_family_id']]['alternatives_evaluated'],
                    'interpretation':'PBO for supplied comparable columns only; not chronological walk-forward evidence',**record})
    # Validate parents again before writing; source content is immutable.
    for rel,digest in parents.items():
        if sha(root/rel)!=digest: raise ValueError('concurrent input change')
    output.mkdir(parents=True,exist_ok=True)
    result={'stage':'2','global_research_N':1483,'dsr_rows':len(results),'cscv_sets':len(pbo),
            'dsr':results,'cscv':pbo,'input_hashes':parents,
            'method':'DSR nonannualized sample Sharpe; unbiased input moments; IID approximation; fixed S=8 CSCV',
            'limitations':'Global and family dispersion may be incomplete. DSR sensitivities cannot authorize strategy selection. Current fee documentation does not prove historical fee schedules.'}
    (output/'STATISTICS_STAGE2_ChatGPT_2026-10-04.json').write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return result
