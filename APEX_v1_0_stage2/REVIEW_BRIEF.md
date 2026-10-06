# APEX v1.0, Stage 1A: brief for the independent reviewer

**What you're reviewing.** Stage 1A ("evidence closure") of APEX v1.0, a research-only crypto/macro backtesting project. Stage 1A closes the evidence-quality issues raised in the Stage 1 review.

**What Stage 1A does not do.** It does not tune, select or run new strategies, and it gives no alpha verdict. Stage 2 has not started.

**What we're asking for.** An accept, accept-with-conditions, or reject decision on Stage 1A. If you accept, Stage 2 (risk/execution layer) can begin.

## Package layout

| Path | What it is |
|---|---|
| `APEX_v1_0/` | The complete project, exactly as delivered in `APEX_v1_0_stage1a_complete.zip` (sha256 `7ea36a02…99d52`). Nothing inside it was changed. |
| `REVIEW_BRIEF.md` | This file. |
| `PRE_REVIEW_VERIFICATION.md` / `.json` | Checks run on 2026-10-04 before handing over, and their results. |
| `logs/full_suite_macos_arm64.txt` | Full output of a single-process run of the whole test suite. |
| `SHA256SUMS` | Hashes of the files at the package root and in `logs/`. |

## Read in this order

1. `APEX_v1_0/STAGE1A_REPORT.md`: the findings and decisions. Sections 0, 14 and 15 are the essentials.
2. `APEX_v1_0/STAGE1A_OUTPUTS.json`: hashes and counts in machine-readable form.
3. `PRE_REVIEW_VERIFICATION.md`: what was already checked, and the one portability finding.
4. `APEX_v1_0/stage1a/CHECKPOINT_STATUS.md`: the mid-stage handoff. It shows which work was done before and after the checkpoint.
5. `APEX_v1_0/STAGE1_REPORT.md` and `APEX_v1_0/handoff/`: background, if needed.

## Rebuilding

Both databases are included, so nothing needs rebuilding just to inspect the results.

```bash
cd APEX_v1_0
python3 -m venv .venv && .venv/bin/pip install -r requirements-v10.txt
.venv/bin/python scripts/run_tests.py          # full suite, ResourceWarnings count as failures
.venv/bin/python scripts/build_stage1a.py      # rebuild Stage 1A DB, gate, ledger, DSR inputs, CSCV matrices
.venv/bin/python scripts/run_forensics_1a.py   # optional, slow: re-run the frozen forensic reproductions
```

## Stage 1 review items, and where Stage 1A addresses each

| # | Review item | Where to look | Suggested checks |
|---|---|---|---|
| 1 | Keep availability timing separate from how final a value is; recover first-release values | `apex_v10/interfaces_1a.py`, `apex_v10/data/sources/h41_releases.py`, `data_v10/raw_1a/`, `reports/vintage_quality_v10_1a.json`, `reports/coverage_gate_evidence_v10_1a.json` | Is `is_evidence_grade()` strict enough? Spot-check several H.4.1 first-release values against the archived release pages. Do you agree with the status assigned to each source (report §5)? |
| 2 | Selection-family and comparable-set metadata | `ledger/trial_ledger_1a.jsonl`, `reports/selection_families_1a.json`, `reports/comparable_sets_1a.json` | Does each family's N reflect the alternatives actually evaluated? Check especially the summary records and the Fibonacci families (§11). |
| 3 | DSR and CSCV inputs only, with no verdict | `reports/dsr_inputs_1a.csv`, `reports/cscv_matrices_1a/` | Do the inclusion rules (§9, §10) keep hypothesis tests out? Is collapsing columns by `return_equivalence_id` right? |
| 4 | Forensic reproduction of the 148 trials that only had summary metrics | `apex_v10/forensics/`, `data_v10/imports/apex_v05/forensic/`, `stage1a/forensic_*_outcomes.json` | Are the archived scripts truly run unmodified and with no tuning? Is leaving the 3 ETH hourly trials as "unavailable" the right call? |
| 5 | Close the ResourceWarnings | `scripts/run_tests.py`, `tests_v10/` | The full suite reports 0 ResourceWarnings. |
| 6 | One consolidated package with a single canonical root | `APEX_v1_0/`, `stage1a/STAGE1A_MANIFEST.json` | The manifest lists 1,639 files. |

## Decisions we specifically want your view on

1. **"Market record" as evidence-grade.** Candles, exchange funding, Treasury par yields and CBOE VIX are treated as evidence-grade under the `market_record` status. This rests on the source's own historical record, not on proof of first release. Is that acceptable for Stage 2?
2. **TGA excluded.** The Treasury General Account stays `unverified`, and therefore excluded, because first-print Daily Treasury Statement history couldn't be retrieved. Exclude it, or find another source?
3. **Edited NY Fed RRP rows dropped.** The 497 RRP rows edited after release are dropped row by row, which makes the early windows PARTIAL. Is that the right treatment?
4. **H.4.1 kept as two families.** No H.4.1 value differs across first release, second print and latest vintage (0 of 666), yet the two families stay separate by design. Do you agree?
5. **Counting trials.** The ledger keeps the global count at N = 1,483 and also records each family's N. Is that the right basis for the DSR and PBO calculations to come?
6. **Deribit funding.** The hourly samples still need mapping to actual account cash flows (open issue 2). Should this block Stage 2, or be a Stage 2 task?

## Known open issues, already disclosed in the report (§15)

TGA vintage; Deribit funding semantics; the "market record" revision policy; the 3 unavailable ETH hourly trials; preserving both the global and family N in DSR/PBO; and execution realism before any performance claims.
