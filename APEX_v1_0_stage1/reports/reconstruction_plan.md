# Return-series reconstruction: what is stored, what can be derived, what is lost

Every trial in `ledger/trial_ledger.jsonl` has one of three `returns_status` values:

- **stored**: the series is in `ledger/returns/`, its file hash is in the ledger, and its `return_equivalence_id` is computed from the values.
- **reconstructable**: the series is not stored separately, but `returns_ref` (`derived:...`) gives an exact rule over a stored series or the frozen candles, and that rule was checked against the frozen numbers.
- **unavailable**: only summary metrics survive.

A series is stored only after its recomputed summary reproduces the frozen artifact. The frozen v0.6–v0.9 code is never edited. It is imported read-only from a hash-verified scratch copy of the database. The helper functions are wrapped for the duration of one call so that each series can be captured.

## Totals

There are 1,483 trials: 839 stored, 496 reconstructable and 148 unavailable. The reconciliation ran 1,339 checks and all 1,339 passed (`reports/reconstruction_reconciliation.json`).

## By family

| Family | Trials | Status | How the series was obtained | Checked against | Max abs diff |
|---|---|---|---|---|---|
| v0.6 batch: T11–T14, T20, T21, hold, sma200 | 28 | stored | `trading_backtest_v06` batch run unmodified; `one` / `run_vector` wrapped to capture daily net returns | Whole batch output equals `*_v06_historical_25bps.json`; per-run stats (full / pre-2022 / post-2022) | 0 |
| v0.6 T12 Fibonacci placebos | 100 | stored | The same batch, placebo loop | `controls.T12_fibonacci_placebo.placebos` (Sharpe, CAGR) | 0 |
| v0.7-code neural ablation | 8 | stored | Generator script is missing from the package. The variant table was rebuilt from `v07.run_sweep`: named anchors .382/.5/.618, placebo anchors .271/.447/.733, seed 20261003 | `neural_ablation_real_25bps.json` (period stats, feature count, signal rate) | 0 |
| v0.8 real runs | 22 | stored | `run_real_single` unmodified; `stats_from_returns` wrapped | Output equals `*_real_v08_25bps.json` | 0 |
| v0.9 experts at 6/25/85 bps | 54 | stored | v0.9 asset run; expert series captured | `historical_v09_results.json` cost runs (`v06.stats`) | 0 (tol 1e-12) |
| v0.9 mixtures at 6/25/85 bps | 12 | stored | As above | As above, plus `mixture_cost_sensitivity.csv` refs | 0 (tol 1e-12) |
| v0.9 Matrix Kelly pair | 3 | stored | `v6.stats` wrapped inside the Kelly run | `matrix_kelly_25bps.rows` | 7.1e-15 (the same floating-point noise as the Stage 0 rerun) |
| v0.9 geometry target cells | 612 | stored (events) | One event file per asset (`v09_<asset>_geometry_events.csv.gz`); each cell is selected by the fragment `#horizon=&scale=&ref=&ratio=` | `geometry.summary`: event count n and mean signed return | 0 (tol 1e-15) |
| v0.9 expert × previous-day state cells | 432 | reconstructable | `derived:<expert series>?prev_state=<state>`: the expert's stored daily returns on days whose previous close was in that state (frozen state labels) | `cost_runs.*.conditional`: n and mean, exact equality | 0 |
| v0.9 state forward distributions | 64 | reconstructable | Generator script is missing from the package. The rule (forward h-day return after a day in state s) was rebuilt from the frozen state labels and candles | `state_forward_distributions.csv`: n and mean | 0 (rel tol 1e-12) |
| APEX v0.5 governed research trials | 14 | unavailable | Only metrics were saved (hash-chained ledger extract, two artifact rows per trial) | — | — |
| APEX v0.5 / v0.5.1 owner hypotheses | 22 | unavailable | Only metrics were saved | — | — |
| Ad hoc 2026-10-02 (walk-forward, Fibonacci, cross-sectional, six-cycle) | 30 | unavailable | Only metrics; scripts imported with hashes | — | — |
| Owner ideas 2026-10-03 (levels, Occam rules, media) | 82 | unavailable | Only metrics; scripts imported with hashes | — | — |

The ledger also records four whole-batch checks: v0.6 batch output equals the frozen JSON for BTC and ETH, and v0.8 `run_real_single` equals the frozen JSON for BTC and ETH.

## Why the 148 unavailable series are not rebuilt in Stage 1

The scripts behind these trials are archived in `data_v10/imports/apex_v05/`, with their hashes recorded on every trial. They ran on the APEX v0.5 store, whose `candles` table is logically identical to the frozen database (the data hash is recorded as `3b1d1bf6…`). Re-running them is therefore technically possible.

Stage 1 is restricted to "do not optimize, train, select or rerun new strategy candidates", so none were re-run. If a later stage needs these paths for PBO/CSCV:

- they should be re-run as historical reproductions, with the definition unchanged and the reproduced metrics reconciled against the recorded ones;
- that re-run needs explicit approval.

Until then, these trials count in the conservative trial number N and are absent from any return matrix.

## How equivalent return paths are handled downstream

`return_equivalence_id` is the SHA-256 of the realized `(t, r)` pairs. There are 839 stored series, which fall into 820 equivalence classes; 14 of those classes are shared by more than one trial. Examples:

- v0.6 T11 and T12 (named Fibonacci) are identical on both assets.
- 3 BTC Fibonacci placebos produce exactly the named-Fibonacci path. The 50 placebos contain only 45 distinct paths on BTC and 44 on ETH.
- v0.6 `hold`/`sma200` are identical to v0.9 `hold_long`/`sma200_long`.

For DSR, N stays the conservative count of every viewed trial (1,483). For PBO/CSCV, identical columns must be treated as one candidate, with tied ranks resolved by the class rather than by the arbitrary column order. The dependence diagnostic (participation ratio 8.96 over 225 non-constant daily series) is reported beside N and never replaces it.
