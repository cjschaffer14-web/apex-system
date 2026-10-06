# APEX v1.0 — Stage 1A Evidence Closure Report

**Status:** complete. Stage 2 has **not** started.

**Purpose:** close the evidence-quality issues identified in the Stage 1 review without tuning, selecting, or running any new strategy candidate. Stage 1A separates information-availability timing from value vintage, completes frozen forensic reconstruction where possible, adds selection-family and comparable-set metadata, prepares DSR/CSCV inputs, and strengthens reproducibility/testing.

## 0. Result in one paragraph

Stage 1A is complete. The accepted Stage 1 database and ledger hashes remain the parent anchors. A new `1.0.1-stage1a` database was produced with separate vintage-quality semantics and a fully recovered Federal Reserve H.4.1 first-release series. All **666/666** archived H.4.1 weekly releases now parse successfully; in this recovered sample, none of the 666 total-assets observations differs between first release and the Stage 1 latest-vintage value, but the two sources remain classified separately so the system does not infer future equivalence. All **148** formerly metric-only historical trials were forensically examined under frozen definitions: **59** exact return paths were recovered, **86** reproduced as statistics only, and **3** remain unavailable because their generating ETH-hourly script version was not archived. The research ledger still contains **1,483** distinct viewed trials; it now maps them into **84** selection families and **33** aligned comparable sets. It prepares **277** DSR input rows for Sharpe-objective, investable stored return series, but computes no DSR/PBO verdict. The evidence-grade coverage gate has 65 PASS, 92 PARTIAL and 155 FAIL family-window cells. The final warning-as-error suite passes **75 tests with 0 ResourceWarnings** when run by module. No Stage 2 code was implemented.

## 1. Parent Stage 1 remains the accepted anchor

The Stage 1 evidence anchors are unchanged:

| Artifact | Accepted Stage 1 hash |
|---|---|
| Stage 1 manifest | `a4591d7e7e501232c50658b0019061b7029d74b56bd40a5fec614f616749f8ee` |
| Stage 1 database file | `2b5f420cebe5823f1e11653ffdcfaf548364d8c2ee4de923d2183d9721ac7e8e` |
| Stage 1 database logical | `b6be7251b11c5a3598d4d718f9b874505c1c4ddf346250637bf653617fb76c51` |
| Stage 1 trial ledger | `70661932c844e427c69ca7afb46fdc0a135920987129e77cea1f0ef02b529d3e` |

The accepted Stage 1 database and ledger were used as immutable parents. Two inherited **test files only** differ from the Stage 1 manifest because Claude's Stage 1A checkpoint closed previously unclosed SQLite test connections; the production/data/evidence parent artifacts remain anchored by the hashes above. The Stage 1A additions are versioned separately.

## 2. Stage 1A database

The new database is additive and has a new schema/hash rather than silently replacing Stage 1.

| Field | Stage 1A value |
|---|---|
| File | `data_v10/market_2026-10-03_v10_1a.sqlite` |
| Schema | `1.0.1-stage1a` |
| File SHA-256 | `0861688a774baf94e39df222a551449f0d5933af7b026dcaadee57cffbacc908` |
| Logical SHA-256 | `60164b73cb5dc6a14c7d003d4f366c48a9382e7ca225dcbb4ef219bffdf7b5e3` |
| Parent Stage 1 file SHA | `2b5f420c…1ac7e8e` |
| Parent Stage 1 logical SHA | `b6be7251…fb76c51` |
| Integrity check | `ok` |
| Foreign-key violations | 0 |

Row counts after the additive migration:

| Table/family | Rows |
|---|---:|
| candles | 220,062 |
| readings | 52,583 |
| funding_events | 229,872 |
| macro_observations | 17,341 |
| macro_revisions | 666 |
| provenance | 994 |
| data_families | 52 |
| vintage_policy | 52 |

The Stage 1A code verifies the accepted Stage 1 parent hash before it constructs the new database.

## 3. Timing quality and value-vintage quality are now separate

Stage 1A no longer treats a historically correct release timestamp as sufficient proof that the retrieved numerical value was the value known at that time.

Every relevant observation can now distinguish:

- **availability-time quality:** `exact_release`, `source_timestamp`, `conservative_lag`, or `approximate`;
- **value-vintage quality:** `first_release`, `unrevised_since_release`, `market_record`, `latest_vintage`, `edited_after_release`, or `unverified`.

An observation is evidence-grade only when both dimensions qualify. The accepted vintage classes are:

- `first_release`;
- `unrevised_since_release`;
- `market_record`.

`latest_vintage`, `edited_after_release`, and `unverified` fail the evidence-grade vintage gate.

### Market-record interpretation

`market_record` is deliberately narrower than “verified first print.” It means that the originating source's historical/event record is being treated as the canonical market record for the backtest. It does **not** assert that the provider can never make retrospective corrections.

Stage 1A uses `market_record` for candles, exchange funding records, Treasury par-yield history, and CBOE VIX history. Their source provenance remains attached so a later audit can tighten that classification if a formal revision mechanism is found.

## 4. H.4.1 first-release recovery

Claude's checkpoint had recovered 651 of 666 archived weekly H.4.1 observations. The remaining 15 failures were caused by taking the first date found in a document header rather than the date attached to the correct “Wednesday <date>” table column.

The parser was tightened rather than relaxed: it identifies the consolidated-statement header associated with the `Total assets` row and resolves the current/prior Wednesday columns from their seven-day relationship.

**Final result: 666 of 666 archived H.4.1 pages parse successfully.**

The recovered family is stored separately as:

`macro:fed_h41_first_release:RESPPMA_N.WW`

with:

- availability-time quality: `exact_release`;
- value-vintage quality: `first_release`.

The older Stage 1 DDP family remains `latest_vintage` and therefore fails the evidence-grade gate even though the recovered historical comparison happened to show no value differences.

### H.4.1 revision audit

Across the 666 observations available to this audit:

- first release → second print changed: **0 / 666**;
- first release → DDP latest value changed: **0 / 666**.

This empirical result is useful, but it does not collapse the first-release and latest-vintage classifications. The system continues to prefer the recovered first-release family for evidence-grade tests.

## 5. Other macro vintage decisions

### NY Fed RRP

Rows with a source-time record and no detected later edit are classified `unrevised_since_release`. The 497 records known to have later edits are classified `edited_after_release` and are excluded row-wise from evidence-grade coverage. This makes early RRP history PARTIAL rather than pretending the revision issue does not exist.

### Treasury General Account

TGA remains `unverified` because first-print Daily Treasury Statement document history could not be verified from the available environment. It is therefore excluded from evidence-grade trials. It remains available for exploratory/sensitivity work, explicitly labeled.

### Treasury yields and VIX

Treasury par yields and CBOE VIX historical records are accepted as `market_record`, with the caveat above: this is canonical source-record treatment, not proof of a first-release vintage.

### Legacy alternative/on-chain readings

Legacy attention/on-chain data lacking defensible historical publication/vintage information is not silently promoted. It remains exploratory unless later re-sourced with stronger provenance.

## 6. Evidence-grade coverage gate

Stage 1A applies the Stage 1 coverage logic **after** filtering out observations that fail timing or vintage evidence quality.

Across 52 registered families and six standard windows (312 family-window cells):

| Grade | Cells |
|---|---:|
| PASS | 65 |
| PARTIAL | 92 |
| FAIL | 155 |

Notable consequences:

- recovered H.4.1 first-release: PASS across all six standard windows;
- Stage 1 H.4.1 latest-vintage family: FAIL for evidence-grade use;
- TGA: FAIL for evidence-grade use;
- Treasury 2Y/10Y and VIX: PASS in the principal windows;
- NY Fed RRP: PARTIAL in early windows affected by edited records; PASS in later windows where the evidence-quality coverage is sufficient;
- legacy approximate-timing/vintage data fails or remains partial rather than being silently filled.

The gate remains fail-closed: a non-PASS source must be ablated, explicitly accepted as exploratory, or the declared test window must be shortened and re-evaluated.

## 7. Frozen forensic reproduction of the 148 metric-only trials

Stage 1A completed the forensic work Claude had started. Original code, raw inputs, scripts, run logs and hashes are used where available. There was **no tuning** and no parameter search during reconstruction.

Classification of all 148 formerly unavailable trials:

| Source group | Trials | Exact return series | Statistics only | Unavailable/mismatch |
|---|---:|---:|---:|---:|
| 2 Oct ad hoc | 30 | 22 | 5 | 3 |
| 3 Oct owner ideas | 82 | 21 | 61 | 0 |
| governed v0.5 | 21 | 14 | 7 | 0 |
| v0.5.1 | 15 | 2 | 13 | 0 |
| **Total** | **148** | **59** | **86** | **3** |

A path is stored only when the frozen run reconciles to the archived metrics. A statistics-only result remains statistics-only; no synthetic return sequence is invented to make it usable in PBO/CSCV.

### The three trials that remain unavailable

The unresolved trials are:

- ETH-USD hourly walk-forward, 80 bps;
- ETH-USD hourly walk-forward, 40 bps;
- ETH-USD hourly walk-forward, 5 bps.

The archived numbers that still exist reproduce, but the surviving script necessarily emits fields absent from those archived records. The evidence therefore indicates that an earlier script version generated them and that version was not retained. Reconstructing a plausible implementation would be reverse engineering, not forensic reproduction, so the three remain unavailable and still count in research-history N.

## 8. Stage 1A trial ledger and selection lineage

The global research-history count remains:

**N = 1,483 distinct viewed real-data trials.**

Stage 1A does not merge distinct evaluated hypotheses merely because their realized returns are identical. Trial identity remains separate from `return_equivalence_id`.

Final Stage 1A ledger:

| Metric | Value |
|---|---:|
| records | 1,483 |
| selection families | 84 |
| aligned comparable sets | 33 |
| return-equivalence classes | 878 |
| stored return paths | 898 |
| reconstructable from Stage 1 | 496 |
| unavailable | 89 |
| forensic exact paths recovered | 59 |
| forensic statistics-only | 86 |
| forensic unavailable | 3 |
| DSR-preparation rows | 277 |

Ledger SHA-256:

`7740820d1f2fbd57503522fb75069334b51204ef8a7c20f71ecab71d650903ba`

The 1,483-trial global count is retained as the conservative project-wide researcher-degrees-of-freedom count. Family-specific N is also recorded so future statistical reporting can distinguish the global research history from the candidate's actual comparable selection family.

## 9. DSR preparation — inputs only, no verdict

`reports/dsr_inputs_1a.csv` contains **277** rows for investable, stored return series whose selection objective is `annualized_sharpe`.

For each row it records:

- global N = 1,483;
- family N;
- T;
- return frequency;
- recomputed annualized Sharpe;
- skew;
- Pearson kurtosis;
- return-equivalence id;
- comparable-set id where applicable.

Non-Sharpe structural/hypothesis tests such as the Fibonacci placebo statistic remain in the global research ledger and selection-family registry but are **not** presented as DSR-Sharpe inputs.

Stage 1A intentionally does **not** calculate a promotion DSR or declare alpha. That belongs to the later evidence evaluation after the relevant execution/risk definitions are fixed.

## 10. CSCV/PBO preparation — comparable aligned matrices only

Stage 1A creates **33** comparable sets. A trial can become a CSCV/PBO column only when it is:

- investable;
- a stored per-period return series;
- part of a common selection family/objective;
- aligned to a common asset/frequency/cost context;
- a Sharpe-objective policy rather than a structural statistic.

Identical realized return columns are collapsed inside the matrix using `return_equivalence_id`, while all distinct hypotheses remain separately represented in the global research ledger.

Geometry target cells, state-forward statistics, conditional statistics and other non-investable hypothesis-test cells therefore do not automatically become CSCV strategy columns.

No PBO verdict is calculated in Stage 1A.

## 11. Fibonacci / geometry bookkeeping correction

The v0.6 T12 family is represented as the named Fibonacci formulation plus its 50 random-ratio placebos: **51 evaluated alternatives per asset** in that selection family.

The separate 2 Oct ad-hoc Fibonacci tests are represented as placebo/hypothesis families with **42 alternatives** per asset/granularity (named formulation + 40 random controls + thirds control). They remain useful falsification evidence but are not mislabeled as a DSR Sharpe-selection family.

This preserves the earlier substantive conclusion: the old static/named-ratio implementations did not establish privileged Fibonacci constants. It does not reject multi-scale geometric structure, which remains a separate Stage 3 modeling question.

## 12. Tests and reproducibility

The final suite was run with `ResourceWarning` treated as a failure, partitioned by test module to stay within the external command-runtime limit.

**Aggregate: 75 tests PASS, 0 failures, 0 errors, 0 skipped, 0 ResourceWarnings.**

| Module | Tests |
|---|---:|
| typed interfaces | 22 |
| Stage 0 baseline | 4 |
| Stage 1 database | 13 |
| Stage 1 ledger | 11 |
| Stage 1 PIT/coverage | 9 |
| Stage 1 sources | 9 |
| Stage 1A | 7 |
| **Total** | **75** |

The logs and their hashes are recorded in `stage1a/TEST_SUMMARY_1A.json`.

Stage 1A also retains the ResourceWarning fix from Claude's checkpoint: test SQLite connections are explicitly closed.

## 13. Rebuild commands

From the canonical project root:

```bash
cd APEX_v1_0

# If the accepted Stage 1 DB is absent, reconstruct it from its frozen raw archive.
python3 scripts/build_stage1.py

# Forensic reproduction is intentionally expensive; run it only when re-verifying frozen evidence.
python3 scripts/run_forensics_1a.py

# Build the Stage 1A database, evidence gate, ledger, DSR inputs and CSCV matrices.
python3 scripts/build_stage1a.py

# Warning-as-error tests can be run as one suite where execution time permits:
python3 scripts/run_tests.py
```

For constrained environments, the same warning-as-error runner can be called once per `test_*.py` module; `stage1a/TEST_SUMMARY_1A.json` records the exact module split used for final verification.

## 14. What Stage 1A does **not** claim

Stage 1A is an evidence-closure stage, not an alpha-discovery stage.

It does **not**:

- choose a winning strategy;
- tune any candidate;
- retrain a neural model;
- calculate a promotion DSR/PBO verdict;
- assert that `market_record` is equivalent to first-release proof;
- invent missing return paths;
- normalize distinct venue funding histories into one fictitious canonical series;
- start Stage 2;
- grant any live-trading authority.

## 15. Open issues for the next independent review

1. **TGA:** first-print/vintage verification is still absent. Keep it out of evidence-grade trials until resolved.
2. **Deribit funding:** the stored hourly continuous-funding samples still require formal mapping to actual account cash-flow semantics before an execution simulator charges them.
3. **Market-record revision policy:** yields, VIX, candles and exchange funding are source-record admissible, but the next reviewer can tighten the classification if source-specific correction/vintage mechanisms are documented.
4. **Three ETH hourly trials:** remain unavailable unless the original generating script version is recovered. They must not be reverse-engineered merely to fill a CSCV matrix.
5. **DSR/PBO:** only inputs and aligned matrices are prepared here. Future calculations must preserve both the global N=1,483 view and family/comparable-set context.
6. **Execution realism:** historical strategy performance must not be promoted using the old flat-cost/high-leverage mechanics; Stage 2/Layer 7 work still has to implement the accepted risk/execution safeguards before new financial claims.

## 16. Stage boundary

**Stage 1A is complete. Stage 2 has not started.**

The appropriate next action is an independent review of this completed Stage 1A package. Only after that review should work begin on the risk/execution layer (Ledoit–Wolf/condition guards, venue event accounting, funding, margin/liquidation, and the unified execution contract).
