# APEX v1.0: Stage 1 Report

**Stage 1 scope:** a point-in-time data layer, source provenance, the CoverageGate, the trial ledger, and reconstructed return series.

**Status:** complete. Stopped for review; no Stage 2 work was started.

**Precedence applied:**
1. the current handoff;
2. the Stage 0 review (ChatGPT, approving Stage 0 with six amendments);
3. the frozen package and evidence;
4. reviewer notes;
5. the historical chat.

**Research only.** There are no credentials, no order code, and no deployment permissions. Nothing was optimized, trained or selected, and no new strategy candidate was run.

## 0. Result in one paragraph

The frozen v0.9 database (`ac53b123…`) was byte-copied and then extended. Every table it already had is logically identical to the frozen file, and the frozen file itself was never opened for writing.

The copy received seven additive tables (six data tables plus `schema_version`):
- funding events from four venues, each venue kept separate;
- macro series from five originator sources (H.4.1, NY Fed RRP, Treasury TGA, Treasury par yields, CBOE VIX), all tagged with availability quality;
- a release calendar;
- availability rules for the legacy readings;
- a provenance table;
- a family registry.

Every value traces to one of 328 archived raw payloads. A rebuild from that archive reproduces the database. The logical hash matches on any machine, and the file is byte-identical on the same SQLite build.

The CoverageGate grades all 51 data families over 6 standard windows: 71 PASS, 170 PARTIAL and 65 FAIL. A trial cannot use a family that does not PASS unless it explicitly fails, shortens its window (and the shorter window must PASS), or names an ablation.

The trial ledger holds 1,483 records, one per genuinely evaluated trial, imported from v0.5 through v0.9 including controls, sensitivities and one failed check:
- 839 return series are stored and 496 can be derived exactly; every stored or derived series was checked against the frozen numbers.
- All 1,339 reconciliation checks pass; the largest difference is 7.1e-15.
- 148 trials have no recoverable series; they are counted in the trial total but are absent from any return matrix.

All 68 tests pass.

## 1. How the Stage 0 amendments were applied

| # | Amendment | Implementation | Where tested |
|---|---|---|---|
| 1 | One TrialRecord per genuinely evaluated hypothesis; `return_equivalence_id`; collapse only duplicate artifact rows; conservative DSR N; dependence reported separately; PBO/CSCV handles equivalent paths | `TrialRecord.identity_sha256()` defines a trial (version, family, name, parameters, asset, venue, product, code/spec/data hashes, window, cost model). Rows with the same identity merge their `artifact_refs` (0 such rows occurred). `return_equivalence_id` = SHA-256 of the realized `(t, r)` pairs, so T11 and T12 stay two trials sharing one id. `LEDGER_SUMMARY.json` reports N = 1,483 (all viewed real-data trials), the 820 equivalence classes, and a participation-ratio dependence diagnostic, which never replaces N. `EvidenceBundle` carries `n_trials_effective` and `n_return_equivalence_classes`; PBO must collapse identical columns by class (see `reports/reconstruction_plan.md`) | `test_stage1_ledger`, `test_interfaces` |
| 2 | Allowlisted `SanitizedFeatureSet`, not a blacklist | `Feature(name, value, known_at_ts, provenance_id, availability_quality)`. The name must be `<namespace>.<name>` with namespace ∈ {price_structure, geometry, volatility, liquidity, macro, attention, onchain, cross_asset}. Provenance must be `data:` or `operator:`. `ExpertInput` holds only the feature set, the pivots and the expert's own history | `test_interfaces` |
| 3 | Router weights keyed by `(expert_id, asset)` | `StrategyMixture.weights: Mapping[(expert_id, asset), float]`. Each asset's weights sum to at most 1, and every key must match a forecast | `test_interfaces` |
| 4 | Strict invariants | `GeometryForecast`: direction ±1; positive reference price and swing length; strictly increasing positive ratios; probabilities in [0,1] and non-increasing; invalidation finite and on the correct side; no non-positive projected target. `RiskAllocation`: positive caps; condition number finite and ≥ 1. `ExecutionEvent`: positive fill prices for priced kinds; `fee_paid ≥ 0` and `rebate_received ≥ 0`; `funding_paid` signed (+ = the account paid) and present only on funding events, together with rate and event time | `test_interfaces` |
| 5 | `reports/coverage_gate_v10.json`, PASS/PARTIAL/FAIL plus availability quality per family and window; FAIL sources must fail, shorten or ablate | `apex_v10/data/coverage.py`: `evaluate`, `gate_report` and `require(on_partial=…, on_fail=…)`. A shortened window is re-evaluated and must PASS for every family still used. Shortening is refused for holes, for approximate timing, and for a family with no data inside the window. Every decision record names the policy and the ablated families | `test_stage1_pit_coverage`, `test_stage1_database` |
| 6 | `availability_quality` mandatory, including `source_timestamp` | NOT NULL plus a CHECK constraint in every v1.0 data table (funding_events, macro_observations, release_calendar, reading_availability, data_families); `Observation` and `Feature` require it. Values: `exact_release`, `source_timestamp`, `conservative_lag`, `approximate` | `test_stage1_sources`, `test_stage1_database` |

**Decisions applied:**
- **Funding venues:** BitMEX, Deribit, Kraken Futures and Coinbase International are kept as separate venue-tagged series. Each has its own semantics string and interval source. Nothing is merged.
- **DXY and equity indexes:** deferred.
- **History:** every recoverable v0.5 and v0.5.1 trial was imported. Controls, failures and sensitivities are retained.
- **Reproducibility:** one command rebuilds everything (§12).

## 2. The v1.0 database

| | |
|---|---|
| File | `data_v10/market_2026-10-03_v10.sqlite` (59,748,352 bytes; shipped gzipped, 10.7 MB) |
| File SHA-256 | `2b5f420cebe5823f1e11653ffdcfaf548364d8c2ee4de923d2183d9721ac7e8e` (SQLite 3.45.1; depends on the SQLite build) |
| **Logical SHA-256** | **`b6be7251b11c5a3598d4d718f9b874505c1c4ddf346250637bf653617fb76c51`** (the cross-machine check) |
| Parent (frozen) | `ac53b123361e5de0f4aa00530cbe1c35286cfd3959224d4e2bf845f634267596`, unchanged before and after |
| Schema version | `1.0.0-stage1`; code hash `63437d67…` is stored in `schema_version` |
| As-of | 2026-10-03 02:00 UTC, the close of the last frozen hourly bar. No row is published after it |
| Integrity | `integrity_check = ok`; 0 foreign-key violations; 0 duplicate keys; 0 rows published before they were observed |

Row counts:

| Table | Rows |
|---|---|
| candles | 220,062 (unchanged) |
| readings | 52,583 (unchanged) |
| imports | 0 (unchanged) |
| funding_events | 229,872 |
| macro_observations | 16,675 |
| release_calendar | 1,580 |
| provenance | 328 |
| reading_availability | 15 |
| data_families | 51 |

Per-table logical hashes are in `data_v10/DB_MANIFEST.json`.

The logical hash excludes `schema_version` only: that table holds the code hash, which changes with any code edit. The file hash includes it.

Every full build since the last change that affected data produced the same logical hash, and every full build produced the same ledger hash `70661932…`.

**Clean-room check:**
- Starting point: a directory holding only the 81 frozen package files and the delivered `APEX_v1_0_stage1.zip`, with the database removed.
- `python3 scripts/build_stage1.py` reproduced the file hash, the logical hash and the ledger hash exactly.
- Every report, ledger file and raw payload matched the original byte for byte, and all 68 tests passed. The rebuild test re-ingests every source from the raw archive into a temporary directory. It reproduces the logical hash, every per-table hash, every row count, and the file hash.

## 3. Source provenance (`reports/source_provenance_v10.json`)

**Archive and timing.**
- Every row names a `provenance_id`, and every `provenance_id` names an archived payload by SHA-256 and path.
- The archive is `data_v10/raw/`: 328 payloads, about 13 MB, deterministic gzip, plus `MANIFEST.jsonl`.
- All sources are originators. None is third-party, and nothing was entered by hand.
- Retrieval ran 2026-10-03 23:16–23:24 UTC; the TGA seam check ran at 23:31 UTC. Rows published after the 02:00 UTC as-of time are excluded.

| Source | Endpoint | Payloads | Rows | Span | Availability rule (quality) |
|---|---|---|---|---|---|
| bitmex | `/api/v1/funding` (XBTUSD, ETHUSD) | 41 | 20,192 | 2016-05-14 → 2026-09-16 | Settlement timestamp; interval from the per-event `fundingInterval` field (`source_timestamp`) |
| deribit | `get_funding_rate_history` (BTC/ETH-PERPETUAL) | 202 (20 empty windows before 2019-04-30) | 130,206 | 2019-04-30 → 2026-10-03 | Hourly sample of continuous funding (`interest_1h`), not a discrete settlement (`source_timestamp`) |
| kraken_futures | `historicalfundingrates` (PF_XBTUSD, PF_ETHUSD) | 2 | 17,590 | 2025-10-01 → 2026-10-03 | Hourly relative rate; interval derived from spacing; the API returns about 12 months (`source_timestamp`) |
| coinbase_intx | `/instruments/{id}/funding` (BTC-PERP, ETH-PERP) | 62 | 61,884 | 2023-03-22 → 2026-10-01 | Hourly, with mark price; interval derived (`source_timestamp`) |
| fed_h41 | DDP H.4.1 package + `releaseDates.json` | 2 | 666 | Wednesdays 2014 → 2026-09-30 | 16:30 ET on the release date the Fed lists (`exact_release`). Value is the latest vintage |
| nyfed | Markets API, RRP results | 1 | 3,186 | 2014-01-02 → 2026-10-02 | Same-day `lastUpdated` stamp (`source_timestamp`, 2,689 rows). Records edited on a later date are `approximate` (497) |
| treasury_fiscaldata | DTS operating cash balance | 4 (one seam check) | 3,203 | 2014-01-02 → 2026-10-01 balances | 17:00 ET next federal business day (`conservative_lag`). Three layouts are spliced only at verified seams |
| treasury_yields | Daily par yield curve CSV (2Y, 10Y) | 13 | 6,380 | 2014 → 2026-10-02 | 20:00 ET same day (`conservative_lag`) |
| cboe | `VIX_History.csv` | 1 | 3,240 | 2014-01-02 → 2026-10-02 | 17:00 ET same day (`conservative_lag`) |

**Legacy readings** (attention, on-chain, and the v0.5 daily funding sums) carry only a day number. Each of their 15 rules is tagged `approximate` and set deliberately late:
- Wikipedia pageviews: +48h;
- Fear & Greed: +6h;
- GDELT: +30h;
- Coin Metrics: +36h;
- legacy funding: +24h.

The two legacy `funding:*` readings are labelled "AGGREGATE … NOT settlement events". `pit.reading_asof` refuses any reading without a rule.

**Not ingested:**
- Binance: HTTP 451 from a US network.
- Bybit: HTTP 403 from a US network.
- DXY and equity indexes: deferred.
- FRED: not used, because direct sources are preferred.

Neither block was circumvented.

## 4. Coverage gate (`reports/coverage_gate_v10.json`, `reports/coverage_v10.md`)

**Definition:**
- **PASS:** start and end within tolerance, at least 98% of the expected observations, and at most 1% of rows with only approximate timing.
- **FAIL:** no overlap, or less than 50% of the expected observations.
- **PARTIAL:** everything else, with the reason given.

Windows:

| Window | Dates |
|---|---|
| v09_btc_full | 2015-07-20 → 2026-10-02 |
| v09_eth_full | 2016-05-18 → 2026-10-02 |
| pre_2022 | 2015-07-20 → 2021-12-31 |
| post_2022 | 2022-01-01 → 2026-10-02 |
| hourly_2017_on | 2017-01-01 → 2026-10-02 |
| funding_era_2019_on | 2019-01-01 → 2026-10-02 |

Status codes in the table below are PA = PASS, PT = PARTIAL, FA = FAIL.

| Family | btc_full | eth_full | pre_2022 | post_2022 | hourly_2017 | funding_2019 |
|---|---|---|---|---|---|---|
| candles BTC-USD daily | PA | PA | PA | PA | PA | PA |
| candles ETH-USD daily | PT | PA | PT | PA | PA | PA |
| candles BTC/ETH hourly | PT | PT | PT | PA | PA | PA |
| 18 other daily pairs | 10 PT, 8 FA (late listings; XRP has a 904-day hole) | 14 PT, 4 FA | 3 PT, 15 FA | 15 PA, 3 PT | 15 PT, 1 PA, 2 FA | 15 PT, 3 PA |
| funding bitmex XBTUSD/ETHUSD | PT | PT | PT | PT (ends 2026-09-16) | PT | PT |
| funding deribit BTC/ETH | PT | PT | FA | **PA** | PT | PT (starts 2019-04-30) |
| funding coinbase_intx BTC/ETH | FA | FA | FA | PT | FA | FA |
| funding kraken BTC/ETH | FA | FA | FA | FA | FA | FA |
| macro H.4.1, TGA, 2Y/10Y, VIX | PA | PA | PA | PA | PA | PA |
| macro NY Fed RRP | PT (4% approximate) | PA | PT | PA | PA | PA |
| legacy attention/on-chain readings (13) | PT | PT | PT | PT | PT | PT (always: 100% approximate timing) |
| legacy funding readings (2) | FA | FA | FA | FA | FA | FA |

**What this means for later stages:**
- No funding venue PASSes before 2022. Deribit is the only funding proxy that PASSes over post_2022.
- Every legacy attention and on-chain family is PARTIAL in every window, because its timing cannot be proven. Shortening the window cannot fix that.
- A trial that uses these families must therefore declare them as an accepted exception or ablate them. This needs a decision (§14, item 2).

## 5. Data-quality findings (`reports/data_quality_v10.json`)

These are recorded, not repaired.

1. **BitMEX stops at 2026-09-16 12:00 UTC**, 16.6 days before the as-of time, for both symbols. A diagnostic query with `reverse=true` on 2026-10-03 returned the same newest record for both symbols (saved in `stage1/bitmex_latest_check.json`, not ingested), so the source itself ends there and paging did not cut it short. The cause is unknown.
2. **BitMEX intervals change.** XBTUSD settled every 24 hours from 2016-05-14 and every 8 hours from 2016-06-04; there are 21 daily spacings in total. The interval is taken from the source field on every event; none is assumed.
3. **Coinbase International has irregular spacings.** It has 3 settlement stamps not aligned to the hour and 8 irregular spacings (131 s to 12,025 s) on both symbols. They are kept as recorded.
4. **Deribit funding is continuous, sampled hourly.** It is not a settlement event stream. How it maps to an account's actual funding payments is stated in the semantics string but **not verified** against Deribit's settlement documentation in Stage 1. Deribit also has one 3-hour gap.
5. **Kraken Futures returns only 12 months** (from 2025-10-01), with 6 two-hour gaps and 1 three-hour gap.
6. **H.4.1 values are the latest vintage.** Release times are exact, from the Fed's release-date archive (1,580 releases). The DDP package carries only the current value per Wednesday, so a revised Wednesday is seen with its revised value from its first release date. The median lag is 16.5 h and the maximum 112.5 h (holiday weeks).
7. **NY Fed RRP:** 497 of 3,186 records (15.6%; most date from 2014–2015, so only 4% fall inside `v09_btc_full`) were edited on a later date; 479 of them carry one bulk 2015-12-05 stamp. They are tagged `approximate`, with a same-day publication time. The maximum lag is now 3.6 h; before the rule, it was 82,801 h.
8. **The TGA layout seams are verified continuous.** The 2021-09-30 close of 215,160 equals the 2021-10-01 open, and the 2022-04-15 close of 578,473 equals the 2022-04-18 open. A seam that does not match makes the adapter refuse to splice.
9. **Coinbase spot pairs:** XRP-USD has a 904-day hole, and every pair except BTC-USD starts after the `v09_btc_full` window opens (2015-07-20). These come from the frozen data and are visible in the gate.

## 6. Trial ledger (`ledger/trial_ledger.jsonl`, `ledger/LEDGER_SUMMARY.json`)

The ledger has 1,483 records. Its SHA-256 is `70661932c844e427c69ca7afb46fdc0a135920987129e77cea1f0ef02b529d3e`. Every line is canonical JSON, round-trips exactly through `TrialRecord`, and re-checks every invariant on load (`apex_v10/ledger/io.py`).

**By source version:**

| Source | Records |
|---|---|
| v0.9 | 1,177 |
| v0.6 | 128 |
| owner_ideas_2026-10-03 | 82 |
| adhoc-2026-10-02 | 30 |
| v0.8 | 22 |
| v0.5 | 21 |
| v0.5.1 | 15 |
| v0.7-nn | 8 |

**By kind:**

| Kind | Records |
|---|---|
| hypothesis_test | 902 |
| sensitivity | 351 (every one points to an existing primary trial) |
| control | 131 (placebos, hold, SMA200, chop and vol-target controls, random levels, baskets) |
| candidate | 99 |

**By returns:** 839 stored, 496 reconstructable, 148 unavailable.

**By status:** 1,482 evaluated, and 1 failed (the withdrawn six-cycle calendar check, which is retained).

Counts match the frozen artifacts, independently of the builder:
- v0.6: 2 × (14 runs + 50 placebos).
- v0.8: 2 × 11 runs.
- v0.9:
  - experts: 2 × 9 × 3 costs;
  - mixtures: 2 × 2 × 3;
  - conditional cells: 2 × 72 × 3;
  - geometry cells: 2 × 306;
  - state-forward rows: 64;
  - Matrix Kelly: 3.
- APEX v0.5:
  - 14 governed research trials, from 28 ledger events (each trial was run twice, so it has two artifact rows);
  - 22 owner hypotheses, from 22 events.

**Counting:**
- **Conservative DSR N:** 1,483. This is every viewed real-data trial; nothing is netted out.
- **Stored series:** 839, which form 820 return-equivalence classes; 14 classes are shared by two or more trials.
- **Participation ratio:** 8.96, over the 225 non-constant stored daily series on their 3,787 common days (2016-05-19 → 2026-10-02). It is reported beside N and is not a replacement for it.

**Correction to Stage 0.** The Stage 0 report (D4) said the governed APEX evaluated "21 research trials". The correct figures are:
- **14 governed research trials**, each run twice on the same data; the two ledger events of each trial are kept as two `artifact_refs` on one record (28 events, 14 records);
- **22 owner hypotheses** (7 in v0.5, 15 in v0.5.1).

The "21" was v0.5's own trials-counted figure (14 + 7).

## 7. Return-series reconstruction (`reports/reconstruction_reconciliation.json`, `reports/reconstruction_plan.md`)

**Method:**
- The frozen v0.6–v0.9 functions are called unmodified on a hash-verified scratch copy of the database.
- Only helper functions are wrapped, for the duration of one call, to capture each series.
- A series is stored only if its recomputed statistics reproduce the frozen artifact.

**Result:** all 1,339 checks pass.
- 1,336 checks match exactly, or within a tolerance of 1e-12/1e-15 with observed difference 0.
- The 3 Matrix Kelly rows differ by at most 7.1e-15, the same floating-point noise seen in the Stage 0 rerun.
- The v0.6 batch output equals the frozen JSON for both assets, and so does the v0.8 `run_real_single` output.

**Two generators were missing from the package and were rebuilt, then verified:**
- The v0.7-code neural ablation variant table was rebuilt from `v07.run_sweep`, using placebo anchors .271/.447/.733 and seed 20261003.
- The v0.9 state-forward rule was rebuilt.

**The 148 trials without a series** are the APEX v0.5 runs, the ad hoc runs and the owner-idea runs; only their metrics were saved.
- Their scripts are archived, with hashes, in `data_v10/imports/apex_v05/`.
- They ran on candles identical to the frozen ones, so re-running them is possible.
- They were not re-run, because Stage 1 forbids reruns.

## 8. Findings that matter for the evidence stages

**The v0.6 Fibonacci placebo control is weaker than it looks.**
- On both assets, T11 (Elliott soft wave-4) and T12 (named Fibonacci) produce **identical** daily return paths, so the named ratios changed nothing relative to T11.
- On BTC, 3 of the 50 random-ratio placebos reproduce that same path exactly.
- The placebo sets contain only 45 distinct paths on BTC and 44 on ETH.
- The frozen BTC result (named Fibonacci at the 56th placebo percentile; ETH at the 38th) therefore includes ties. The test has less power than 50 independent draws would give.
- This is recorded as a fact about the historical control, not as a new performance claim.

**v0.6 `hold` and `sma200` are identical to v0.9 `hold_long` and `sma200_long`.** They are kept as separate trials that share an equivalence id.

**Two v0.9 geometry cells share all their events:** BTC fast wave-1 r=0.4 at h=20 and at h=60. All of those events resolve within 20 bars.

## 9. Other corrections made in Stage 1

**The Stage 0 acceptance test overwrote Stage 0 evidence.**
- Re-running the v0.9 validation rewrote `stage0/outputs/v09_validation_rerun_report.json` without its historical section.
- `stage0/run_v09_validation.py` now takes `--outdir`, and the test writes to a temporary directory.
- The delivered Stage 0 outputs were restored and are byte-identical to the Stage 0 zip.

**`stage0/verify_baseline.unlisted_files` now scans only the frozen directories** (`baseline_v09/`, `handoff/`, `reviews/`).
- Add-only v1.0 outputs elsewhere are covered by `stage1/STAGE1_MANIFEST.json`.
- A stray file inside a frozen directory is still flagged; this was tested with `reviews/stray.tmp`.

## 10. Deviations from the Stage 0 file plan

- The nine planned adapter files became two modules, `sources/funding.py` and `sources/macro.py`, plus `common.py`.
- The release-timing rules live in each macro adapter; there is no separate `release_timing.py`.
- `scripts/reconstruct_returns.py` became `apex_v10/ledger/reconstruct.py` and `build_ledger.py`, driven by `scripts/build_trial_ledger.py`.
- The planned test files `test_stage1_migration` / `_pit` / `_funding` became `test_stage1_database`, `test_stage1_pit_coverage` and `test_stage1_sources`, plus `test_stage1_ledger`. Every planned assertion is covered.
- `data_quality_v10.md` is JSON (`data_quality_v10.json`). Its tables appear in this report and in `coverage_v10.md`.
- **Added:**
  - `data/archive.py`, the raw archive with online and raw modes;
  - `data/timeutil.py`, the federal holiday calendar and Eastern Time helpers;
  - `data/coverage.py`, the CoverageGate;
  - `reports/source_provenance_v10.json`;
  - `scripts/build_stage1.py`, the single command;
  - `scripts/write_stage_manifest.py`;
  - `apex_v10/ledger/io.py`.
- **Planned vs done for the neural ablation:** planned as unavailable; it is now reconstructed and stored (8 trials).
- **Planned vs done for duplicates:** planned as "collapsed by return-series hash". Replaced, per amendment 1, by identity-based collapse plus a shared `return_equivalence_id`.

## 11. Tests (`stage1/test_output.txt`)

**68 tests, all passing, in about 36 s.** Command: `python3 -m unittest discover -s tests_v10 -p "test_*.py" -v`.

| File | Tests | Covers |
|---|---|---|
| `test_interfaces.py` | 22 | Every typed object and invariant, including amendments 2–4 |
| `test_stage0_baseline.py` | 4 | Manifests, database and spec hashes; the v0.9 validation rerun identical; no stray files; exact path redirects |
| `test_stage1_sources.py` | 9 | Every adapter offline against recorded-shape fixtures, covering: BitMEX intervals and as-of cut; Deribit dedupe and semantics; Kraken/INTX spacing; the H.4.1 holiday release; NY Fed late edits; TGA seams, including refusal; yields N/A; VIX; schema CHECKs; archive tampering |
| `test_stage1_pit_coverage.py` | 9 | As-of with revisions (period 2 published before period 1's revision, and later revisions); `MacroSeries` equals SQL on 400 random revisions; legacy lag rules and refusal without a rule; funding accrual only at recorded events, the 8h→4h change, flat at an event, a missing settlement never invented, a position opened after the instant; gate PASS/PARTIAL/FAIL; `require` with fail, ablate and shorten (FAIL and PARTIAL), and refusal when shortening cannot help |
| `test_stage1_database.py` | 13 | Frozen DB unchanged; manifest equals file (file, logical, per-table, counts); integrity and FKs; legacy tables identical; schema_version parent; no future, duplicate or inverted rows; mandatory quality; every row traced to an archived payload whose hash matches; every legacy reading has a rule; venues separate, with BitMEX intervals not constant; family registry; reports complete; **full rebuild from the raw archive reproduces the logical and file hashes** |
| `test_stage1_ledger.py` | 11 | Exact round trip; unique ids and identities; summary equals the file; conservative N; sensitivity parents; every stored series' file hash and equivalence id recomputed; no orphan files; T11/T12 distinct but equivalent; counts equal the frozen artifacts; v0.5 import complete (14 + 22, every event referenced); controls and the failed trial retained; every frozen series reconciled |

## 12. Reproduce on the Mac (one command)

**Setup:**
1. Unzip `APEX_v1_0_Claude_Implementation_Handoff.zip`.
2. Unzip `APEX_v1_0_stage1.zip` into the same folder; it adds files only.
3. Install the packages: `python3 -m pip install -r requirements-v10.txt`. This needs Python 3.11 or later, with numpy, pandas, scipy and scikit-learn.

**Then:**

```
python3 scripts/build_stage1.py                 # rebuild DB, ledger and reports from the archived payloads (about 80 s)
python3 -m unittest discover -s tests_v10 -p "test_*.py"
```

**Expected result:**
- `db_logical_sha256 = b6be7251…` and `ledger_sha256 = 70661932…`.
- The DB file hash will differ if macOS ships another SQLite version; the logical hash is the check.
- The command exits non-zero if the baseline changes or any reconstruction check fails.

**Refreshing the data:** `python3 scripts/build_stage1.py --mode online` refetches every source into a new archive. The old archive is kept as `data_v10/raw_previous_<time>`. The result is a new snapshot with a new logical hash, which is expected. The as-of time stays fixed at 2026-10-03 02:00 UTC unless it is deliberately changed.

**The prebuilt database** ships as `APEX_v1_0_stage1_db.sqlite.gz`. Decompress it to `data_v10/market_2026-10-03_v10.sqlite` if you would rather not rebuild.

## 13. Files changed in Stage 1

All file hashes are listed in `stage1/STAGE1_MANIFEST.json`.

**Changed (from Stage 0):**
- `apex_v10/interfaces.py`: amendments 1–6.
- `tests_v10/test_interfaces.py`.
- `stage0/verify_baseline.py`: `unlisted_files` scope.
- `stage0/run_v09_validation.py`: `--outdir`.
- `tests_v10/test_stage0_baseline.py`: temporary output directory.

**New code:**
- `apex_v10/data/`: `__init__`, `archive`, `timeutil`, `schema`, `pit`, `coverage`, `build`, `reports`.
- `apex_v10/data/sources/`: `__init__`, `common`, `funding`, `macro`.
- `apex_v10/ledger/`: `__init__`, `reconstruct`, `build_ledger`, `io`.

**New scripts:** `scripts/build_stage1.py`, `migrate_market_v10.py`, `ingest_sources_v10.py`, `build_trial_ledger.py`, `write_stage_manifest.py`.

**New tests:**
- `tests_v10/test_stage1_sources.py`, `test_stage1_pit_coverage.py`, `test_stage1_database.py`, `test_stage1_ledger.py`;
- `tests_v10/fixtures/`.

**New data:**
- `data_v10/raw/`: 328 payloads plus `MANIFEST.jsonl`;
- `data_v10/imports/apex_v05/`: the ledger extract (74 events), the research JSON and scripts, and the four v0.5 code files;
- `data_v10/DB_MANIFEST.json`;
- `data_v10/market_2026-10-03_v10.sqlite`, generated (shipped gzipped).

**New ledger:** `ledger/trial_ledger.jsonl`, `ledger/LEDGER_SUMMARY.json`, `ledger/returns/` (229 files).

**New reports:** `coverage_v10.json`, `coverage_v10.md`, `coverage_gate_v10.json`, `data_quality_v10.json`, `source_provenance_v10.json`, `reconstruction_reconciliation.json`, `reconstruction_plan.md`.

**Top level:** `STAGE1_OUTPUTS.json`, `STAGE1_REPORT.md`, `stage1/{build_log.txt, test_output.txt, STAGE1_MANIFEST.json, bitmex_latest_check.json}`.

**Unchanged:** everything in `baseline_v09/`, `handoff/` and `reviews/`, plus `README.md` and `PACKAGE_MANIFEST.json`. Both manifests verify before and after the build.

## 14. Open issues and decisions for review

1. **Legacy reading timing.** Wikipedia, GDELT, Fear & Greed and Coin Metrics carry no publication times and no vintages. They can never PASS the gate. Options:
   - (a) a named, owner-approved exception class: "approximate, deliberately late rule";
   - (b) ablate them from every v1.0 trial;
   - (c) re-source the series from providers that publish timestamps.

   Recommendation: (b) for evidence-grade trials and (a) only for exploratory work, labelled as such.
2. **Deribit funding semantics.** Hourly samples of continuous funding are stored as-is. Before the execution simulator charges Deribit-proxy funding (Stage 4), the mapping from `interest_1h` to account cash flows must be verified against Deribit's documentation.
3. **BitMEX ends 2026-09-16.** If BitMEX is used as a proxy, trials must end by then or shorten their window; the gate enforces this. Whether the stream resumes is unknown.
4. **H.4.1 latest-vintage values.** The timing is exact, but revised Wednesday values carry slight look-ahead. Options: accept and document it (revisions to total assets are rare and small), or tag the series `approximate` for value until first-print vintages can be sourced. Recommendation: accept, documented.
5. **The 148 metric-only historical trials** count in N but are absent from return matrices. Re-running them as historical reproductions in a later stage, with definitions unchanged, needs explicit approval.
6. **Funding history before 2019.** It exists only from BitMEX, so any pre-2019 perp-funding evidence rests on a single offshore venue.
7. **Terms of use.** Confirming each funding source's terms of use for a US person remains an owner or attorney question from Stage 0 (D1). This is not legal advice.

**Stopped here for review. Stage 2 has not started.**
