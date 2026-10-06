# APEX v1.0: Stage 0 Report

**Prepared by:** Claude, 3 October 2026.

**Scope:** Prompt 0 (Stage 0 only) from `handoff/SEQUENTIAL_CLAUDE_PROMPTS.md`.

**Status:** Stage 0 is complete and stopped for review.
* No database migration, model training or change to any historical strategy definition was made.
* No new performance claim is made.
* Nothing in this work has live-trading authority.

## 0. Result in one paragraph

The frozen v0.9 baseline checks out.
* **Hashes:** all 45 package files and all 36 baseline files match their manifests, the database SHA-256 and row counts match `DATA_MANIFEST.json`, and the frozen-spec hash matches.
* **Validation:** the original `validate_v09.py`, run with its file paths redirected, reproduces all 11 frozen tests exactly.
* **Reproducibility:** the frozen v0.6 and v0.8 results regenerate byte-for-byte from the frozen code, and the v0.9 historical results regenerate with identical structure, differing by at most 7.1 × 10⁻¹⁵.
* **What this enables:** the per-period return series that the trial ledger and CSCV/PBO need can be rebuilt exactly. They do not have to be marked unavailable.
* **Delivered:**
  * typed DAG interfaces with 16 contract tests (20 Stage 0 tests in total, all passing);
  * an exact Stage 1 file plan;
  * five decisions needed before Stage 1 starts (section 9).

## 1. How the three reviews were reconciled (aligned to the ChatGPT handoff)

The ChatGPT handoff is treated as authoritative. Where Gemini's or DeepSeek's proposal conflicts with it, the handoff wins. Stage 0 checks added evidence on several points.

| Topic | Gemini / DeepSeek proposal | Adopted (handoff) | Stage 0 evidence |
|---|---|---|---|
| Funding | 8-hour Binance funding, 2019–2026, accrued at 00/08/16 UTC | Accrue from recorded settlement events and interval metadata | Binance returned **HTTP 451** ("restricted location") and Bybit **403** from this US network. The Binance plan cannot run as written, and it would bypass an eligibility restriction. BitMEX exposes `fundingInterval` per event; its first record shows a 24-hour interval and current records show 8 hours. That confirms intervals change. |
| Fees and margin | Maker 1.5 bps, taker 4.5 bps, 0.5% maintenance margin everywhere | Versioned venue/date/notional schedules plus sensitivity runs | — |
| Macro data | FRED API, later direct endpoints with hard-coded lags | Direct sources first, with release times from calendars or conservative-lag tags | NY Fed reverse-repo API, Treasury Daily Treasury Statement API, the Treasury yield-curve CSV and the CBOE VIX CSV all answered **200**. The Fed's Data Download Program page is online; that contradicts the claim that it was retired. Yahoo (yfinance) returned **429**. |
| Trial ledger | Scrape summaries until N ≥ 64 | One immutable record per actual trial, with lineage, hashes and a return-series reference | The "64" is v0.6's `trial_count_this_batch`: 14 runs plus 50 Fibonacci placebos per asset. There are duplicates: `T12_named_fibonacci` and `T11_elliott_soft_wave4` are the same exposure series, and v0.6 `hold`/`sma200` equal v0.9 `hold_long`/`sma200_long`. The ledger must deduplicate by return-series hash. |
| DSR gate | DSR > 1.0 in one draft | DSR ≥ 0.95, bounded in [0, 1] | Enforced in `EvidenceBundle` |
| PBO | Computed from the ledger | Only from aligned per-period return matrices | The return paths can be rebuilt (section 4) |
| Matrix Kelly | Ledoit-Wolf, plus a 50% diagonal blend if the condition number exceeds 50 | Ledoit-Wolf, then a deterministic ladder (eigenvalue floor → recheck → independent fractional Kelly → zero) | The frozen code uses a fixed ridge of 0.20 with a pseudo-inverse and no condition check |
| Expert output | A float in [−1, 1] | A structured `ExpertForecast` with a common horizon and units | Implemented |
| Geometry head | `cummin(sigmoid)` with an unused `ratio_grid` | `ratio_grid` drives labels and inference, with a differentiable monotone parameterization | The interface enforces monotonicity and grid use |
| State model | HMM/GMM on net liquidity | A family of candidate models; the deterministic v0.9 classifier stays as the baseline | One-hot baseline factory provided |
| Plugins | Auto-import with importlib | Registry with manifest, hash and allowlist | Stage 2 |
| Qwen/vendor compliance | Discussed at length | Excluded from the quantitative implementation | The v1.0 research code uses no language model |

One correction to DeepSeek's description of the funding data. The 368 `funding:*` rows are not Binance-style 8-hour settlements. APEX v0.5 wrote them from Kraken Futures (`PF_XBTUSD` and `PF_ETHUSD`): each is a daily sum of hourly funding rates, covering October 2025 to October 2026. Stage 1 must tag them that way. They cannot serve as settlement events.

## 2. Baseline verification (`stage0/verify_baseline.py` → `stage0/outputs/baseline_verification.json`)

| Check | Result |
|---|---|
| Package manifest (45 files) | All present; sizes and SHA-256 match |
| Baseline manifest (36 files) | All present; sizes and SHA-256 match |
| `research/CHECKSUMS.txt` (2 entries, original `/mnt/data` paths) | Both match |
| Frozen spec | `e3415de6…b4707`, matching the hash quoted in `README_HANDOFF.md` |
| Database `market_2026-10-03.sqlite` | SHA `ac53b123…67596`, 20,119,552 bytes, `PRAGMA integrity_check` = ok. All counts match: 220,062 candles, 52,583 readings, every series' row count and first/last timestamp. |
| Unlisted files in the baseline | None |
| Provenance | The database hash equals the file APEX v0.5.1 delivered on 3 October, so the chain from the governed APEX to v0.9 to v1.0 is intact. |

The database is opened read-only and immutable (`mode=ro&immutable=1`) for every check.

## 3. Running the v0.9 validation without touching the baseline

`validate_v09.py` and `trading_backtest_v09.main()` hard-code `/mnt/data/...` paths and write their results there. `stage0/run_v09_validation.py` runs them as follows:
* it executes the original source with exactly two path literals redirected, and stops if either literal is not found exactly once;
* the database is a hash-verified scratch copy;
* the output goes to `stage0/outputs/`;
* every baseline file is hashed before and after.

**Result:** 11 of 11 tests passed and are identical to `results/validation_v09.json`. The baseline was unchanged (37 files hashed).

**An incident, caught by the guard:** the first run imported the frozen modules with bytecode caching on. Python wrote four `.pyc` files into `baseline_v09/code/__pycache__/`, and the before/after hash check flagged them.
* **Repair:** the stray files were removed, and the runner now sets `sys.dont_write_bytecode`.
* **Prevention:** the verifier now flags any unlisted file in the baseline.
* **Proof:** a re-verification showed the baseline byte-identical to its manifest.

Anyone running the frozen code must disable bytecode writing (`PYTHONDONTWRITEBYTECODE=1`).

## 4. Can the historical trials be rebuilt? (`stage0/reproduce_probe.py`)

| Frozen result | Regenerated from frozen code and data |
|---|---|
| `btc_v06_historical_25bps.json`, `eth_v06_historical_25bps.json` | Byte-identical |
| `btc_real_v08_25bps.json`, `eth_real_v08_25bps.json` (including the MLP walk-forward) | Byte-identical |
| `historical_v09_results.json` | Identical structure; largest numeric difference 7.1 × 10⁻¹⁵ (last-digit floating point) |
| `neural_ablation_real_25bps.*` | Generator script not in the package |
| `frozen_ladder_v08_25bps.csv`, `mixture_cost_sensitivity.csv`, `matrix_kelly_btc_eth_25bps.csv`, `state_forward_distributions.csv`, `geometry_named_vs_neighbors.csv` | Derived tables; the derivation scripts are not in the package |

The result files store summary statistics only. Because the code is deterministic, Stage 1 can rebuild each trial's daily return series by calling the frozen functions with unchanged parameters. Each rebuilt series is accepted only if its recomputed summary matches the frozen numbers. The neural-ablation trials stay `unavailable` until their generator is either recovered or rebuilt, and the rebuild has been shown to match the frozen table.

## 5. The existing code mapped to the eight DAG layers (`stage0/outputs/dag_layer_map.json`)

| Layer | Frozen code | What Stage 2 or 3 must untangle |
|---|---|---|
| 1. Data & chronology | `v06.load_sqlite`, the SQLite store | Readings carry day numbers only, with no publication time. No macro data. Funding covers one year, as daily sums. |
| 2. Structural operators | `sma`, `atr`, `choppiness`, `causal_zigzag` (records the confirmation index), `pivot_state_series`, wave/fractal feature builders | Already causal; prefix invariance is tested |
| 3. State | `v09.classify_states` (frozen priority rules) | Hard labels → one-hot `MarketStateDistribution` baseline |
| 4. Experts | v0.6 signals, v0.7/v0.8 MLP walk-forwards, `t20_intrabar_pyramid`, mean reversion | Experts emit exposures (−1 to 7×), not forecasts. The pyramid mixes expert, execution and costs. |
| 5. Router | `v09.mixture_returns`, `v08.strategy_state_portfolio` | Routing is mixed with execution and costs |
| 6. Risk | `kelly_continuous`, `matrix_kelly` | Fixed ridge 0.20 with a pseudo-inverse and no condition guard. Sizes from trailing means, not from forecasts. |
| 7. Execution | `v06.run_vector` (flat bps on turnover); the pyramid's OHLC simulation | No funding, fee tiers or liquidation. `v06.stats` floors equity at 10⁻⁹, so a leveraged wipe-out is truncated rather than liquidated. The T20 4× and 7× ladders are most exposed. |
| 8. Evidence | `stats`, `batch`, `run_real_single`, `geometry_summary`, `validate_v09.py`, schemas | No DSR, PBO or ledger. Summaries only. |

## 6. Data observations for Stage 1 (recorded, not judged)

**Calendar gaps:**
* XRP-USD daily: 904 missing days. This is consistent with Coinbase's suspension of XRP trading.
* BTC-USD hourly: 53 missing hours; ETH-USD hourly: 38.
* Daily: BCH 4, ETH 2 and LTC 1 missing days.
* Readings: GDELT 32 missing days; Fear & Greed 4.

**Readings timing:** attention and on-chain readings are stored as day numbers with no publication or retrieval time. Stage 1 must assign each source a documented availability rule and tag its quality.

**Not present:** macro series, funding settlement events and venue schedules.

## 7. Interface proposal (`apex_v10/interfaces.py`, standard library only)

Every object passed between layers is a frozen dataclass that validates itself when it is created:

| Layer | Object | Rules enforced when the object is created |
|---|---|---|
| 1 | `Bar`, `Observation`, `ObservationFrame`, `Provenance` | No bar closing after `decision_ts` and no observation published after it. `asof()` picks by publication time. A value cannot be published before it exists. |
| 2 | `Pivot`, `StructureState`, `GeometryForecast` | Confirmed pivots only. `ratio_grid` is strictly increasing and maps to target prices. Reach probability does not increase with distance. |
| 3 | `MarketStateDistribution` | Probabilities sum to 1. Entropy and persistence are reported. It has no sizing fields. `from_label()` wraps the v0.9 rules. |
| 4 | `ExpertInput`, `ExpertForecast` | Experts see structure and their own past forecasts only; a forbidden-field list covers account, leverage, router output and labels. One return unit (log return over the horizon), with bounded confidence and direction. |
| 5 | `StrategyMixture` | Weights are non-negative and sum to at most 1; the rest is cash. All forecasts must share one horizon. |
| 6 | `RiskAllocation` | Per-asset and gross caps. The covariance method must be a named rung of the fallback ladder. Guard events are logged. |
| 7 | `ExecutionEvent` | A funding event needs the recorded settlement time and rate. A same-bar ambiguity must say how it was resolved; `conservative_bar` cannot resolve optimistically. A liquidation without mark-price data must be flagged approximate. |
| 8 | `TrialRecord`, `EvidenceBundle` | Trial identity is a hash of what defines the trial (metrics excluded), and every return series carries a status. DSR lies in [0, 1] and the gate is fixed at 0.95. PBO requires an aligned matrix hash. A `candidate` verdict needs DSR ≥ 0.95 and an untouched holdout. `authority_request` is always false. |

Layer protocols (`DataSource`, `StructuralOperator`, `StateEstimator`, `StrategyExpert`, `Router`, `RiskAllocator`, `ExecutionModel`) define the method each implementation must provide. The implementations themselves arrive in Stages 1–4.

## 8. Exact Stage 1 file plan (to build after approval)

All files are new; nothing in `baseline_v09/` changes.

```
scripts/migrate_market_v10.py        byte-copy DB -> data_v10/market_2026-10-03_v10.sqlite; verify source hash before/after;
                                     additive DDL in the copy only; record target hash + script hash in schema_version
scripts/build_trial_ledger.py        frozen results + rebuilt returns -> ledger/trial_ledger.jsonl (one TrialRecord per trial)
scripts/reconstruct_returns.py       call frozen functions (unchanged parameters) -> ledger/returns/<trial_id>.csv + sha256;
                                     accept only if recomputed summary == frozen summary
apex_v10/data/pit.py                 point-in-time join (latest published_ts <= decision_ts, latest vintage); funding accrual
                                     iterator over recorded events
apex_v10/data/release_timing.py      per-source release rules -> release_calendar rows with quality tags
apex_v10/data/sources/
    funding_bitmex.py                XBTUSD/ETHUSD 2016+, per-event fundingInterval
    funding_deribit.py               BTC/ETH-PERPETUAL 2019+, continuous funding sampled hourly (semantics stored)
    funding_kraken.py                PF_XBTUSD/PF_ETHUSD (API window ~12 months)
    funding_coinbase_intx.py         BTC-PERP/ETH-PERP 2023+
    macro_nyfed_rrp.py               NY Fed reverse repo results API
    macro_treasury_dts.py            Treasury General Account (Daily Treasury Statement, Fiscal Data API)
    macro_treasury_yields.py         Treasury daily par yield curve CSV (2Y, 10Y)
    macro_fed_h41.py                 H.4.1 total assets via the Fed Data Download Program
    market_cboe_vix.py               CBOE VIX history CSV
data_v10/raw/<source>/<sha256>.*     every raw payload, kept for audit
reports/coverage_v10.{json,md}       by source/asset/date
reports/data_quality_v10.md          gaps, duplicates, monotonicity, legacy-readings availability rules
reports/reconstruction_plan.md       which trials are stored / reconstructable / unavailable, and why
tests_v10/test_stage1_migration.py   source DB byte-identical; legacy tables identical row-for-row; target hash recorded;
                                     tuple inserts; PK uniqueness; monotonic timestamps
tests_v10/test_stage1_pit.py         a value published at T+1 is invisible at T; a later vintage is invisible before release;
                                     holiday-shifted release; conservative-lag tagging
tests_v10/test_stage1_funding.py     accrual only at recorded events; 8h->4h interval change; open vs flat at event; gaps
tests_v10/test_stage1_ledger.py      no double counting (identity + return-hash dedupe); aggregates rejected; sensitivity
                                     rows linked to parent; every frozen row maps to exactly one record; rebuilt series
                                     reproduce frozen summaries
tests_v10/fixtures/                  small recorded payloads so every adapter test runs offline
```

**New tables, all in the v10 copy:**
* `schema_version`;
* `provenance`;
* `funding_events` (venue, symbol, funding_ts, rate, interval_s, rate_semantics, mark/index price, provenance), with the primary key (venue, symbol, funding_ts);
* `macro_observations` (source, series_id, observation_ts, published_ts, retrieved_ts, value, vintage_or_release_id, raw_payload_sha256, availability_quality, provenance), with a primary key that keeps revisions;
* `release_calendar`;
* `reading_availability`, the availability rules for the legacy attention and on-chain readings;
* a provenance row that tags the legacy `funding:*` readings as Kraken daily sums.

**Ledger contents, all tagged `viewed_before_later_choice=true`:**
* **v0.6:** 2 assets × (14 runs + 50 placebos).
* **v0.8:** 2 × 11 runs.
* **v0.9:**
  * 2 × 9 experts and 2 mixtures, × 3 cost levels;
  * 3 Matrix Kelly fractions;
  * the geometry grid, as a separate hypothesis-test family, because event returns are not aligned per-period series.
* **Neural ablation:** 2 × 4 trials, `unavailable` until reconstructed.
* **Duplicates:** collapsed by return-series hash, with every source row kept as an alias.

## 9. Decisions needed before Stage 1

**D1. Funding history source.** Binance and Bybit are blocked from the US. The reachable sources are BitMEX (2016 onward, with interval metadata), Deribit (2019 onward, continuous funding), Kraken Futures (12 months) and Coinbase International (2023 onward). All are offshore proxies for whichever US venue APEX would eventually use.
* **Recommendation:** store each as its own venue-tagged event series and label backtests "proxy funding".
* **Before ingestion:** confirm each source's terms of use for a US entity, as an owner or attorney question.

**D2. DXY and equity indexes.** Their originators offer no free API.
* **Options:** leave them out of Stage 1, or ingest them from a third party tagged `third_party=true`.

**D3. Trial counting for the DSR.**
* **Proposal:**
  * Placebo controls are recorded with `trial_kind=control`.
  * Cost-sensitivity reruns are recorded as children of their primary trial.
  * Geometry grid cells form their own hypothesis-test family.
* **Reporting:** DSR is reported under both N (candidates only) and N (everything evaluated). The gate uses the larger, conservative N.

**D4. Prior APEX trials.** The governed APEX (v0.5 and v0.5.1) evaluated 21 research trials and 22 owner hypotheses on this same database before v0.9 was designed.
* **Proposal:** import them as prior viewed trials, so the multiple-testing count is honest.

**D5. Where Stage 1 runs.** This build environment reached every direct source listed above. Raw payloads would be stored for audit.
* **Alternative:** run on the owner's Mac, if preferred.

## 10. Files changed in Stage 0 (all new; baseline untouched)

```
STAGE0_REPORT.md
requirements-v10.txt
apex_v10/__init__.py
apex_v10/interfaces.py
stage0/verify_baseline.py
stage0/run_v09_validation.py
stage0/reproduce_probe.py
stage0/outputs/baseline_verification.json
stage0/outputs/v09_validation_rerun.json
stage0/outputs/v09_validation_rerun_report.json
stage0/outputs/reproduce_probe.json
stage0/outputs/dag_layer_map.json
stage0/outputs/environment.json
stage0/outputs/test_output.txt
tests_v10/test_interfaces.py
tests_v10/test_stage0_baseline.py
```

**Environment:** Python 3.13.15, numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, scikit-learn 1.9.1. PyTorch is not installed; it is needed from Stage 3.

## 11. Test output

```
$ PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests_v10 -p "test_*.py" -v
Chronology        frame rejects future bars and unpublished observations ... ok
                  asof uses publication time, not observation time ...... ok
                  bars must be ordered and consistent ................... ok
Evidence          gate rules (authority, DSR bounds, PBO needs matrix,
                  candidate needs DSR >= 0.95 and untouched holdout) .... ok
                  objects frozen; hashes deterministic .................. ok
                  trial identity and returns status ..................... ok
Execution         funding needs recorded event; liquidation flags ....... ok
                  same-bar ambiguity resolved pessimistically ........... ok
Experts           cannot reach account/router/future .................... ok
                  forecast units and bounds ............................. ok
Mixture           common horizon and weights ............................ ok
Risk              caps and fallback rungs ............................... ok
State             sums to one; baseline is one-hot ...................... ok
                  state objects cannot size trades ...................... ok
Structure         geometry forecast monotone, uses ratio_grid ........... ok
                  only confirmed pivots ................................. ok
BaselineHashes    both manifests verify ................................. ok
                  database and frozen spec .............................. ok
FrozenValidation  path redirect is exact ................................ ok
                  v0.9 validation reruns identically, baseline untouched  ok
----------------------------------------------------------------------
Ran 20 tests in 3.2s
OK
```

The full verbose log is in `stage0/outputs/test_output.txt`.
