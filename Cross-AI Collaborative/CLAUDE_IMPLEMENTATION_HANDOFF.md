# APEX v1.0 — Claude Implementation Handoff

## Purpose

Implement the next APEX research architecture from the frozen v0.9 baseline. This handoff consolidates the Gemini and DeepSeek reviews, but **does not accept every suggestion literally**. The implementation must preserve historical provenance, make financial claims falsifiable, and keep state estimation, strategy forecasts, risk sizing, and execution separate.

**Research only. No live trading authority. Do not add exchange credentials, live-order code, or production deployment permissions.**

## Baseline that must remain immutable

- `baseline_v09/data/market_2026-10-03.sqlite`
- v0.9 frozen spec and result files under `baseline_v09/research/` and `baseline_v09/results/`
- Do not modify the original SQLite file in place.
- Every new artifact must have a version, SHA-256 hash, source/provenance metadata, and parent baseline hash.
- Re-running a historical experiment is allowed; silently changing its definition is not.

## Architectural decision

Retain the eight-layer DAG concept:

1. Data & chronology
2. Reusable structural operators
3. Environmental state engine
4. Strategy expert pool
5. State-conditioned mixture router
6. Risk allocation / fractional Matrix Kelly
7. Venue execution / microstructure
8. Evidence, falsification, and trial accounting

The DAG is a chassis, not a claim that any particular model is correct. HMM, GMM, change-point models, TCNs, neural ODEs, and other models are **candidate implementations behind interfaces**, not architecture-level commitments.

## Important modifications to the Gemini/DeepSeek proposals

### 1. Trial ledger must contain evidence, not just summary Sharpe values

Build `trial_ledger.jsonl` (JSONL is preferred to a monolithic JSON array). Each actual research trial gets one immutable record with:

- trial ID and parent/lineage
- model/strategy family and exact parameterization
- asset/venue/product
- code hash, frozen-spec hash, data hash
- train/validation/test windows
- cost/execution model ID
- nominal metrics
- path or hash for the **per-period return series**
- failure/rejection status
- whether it was viewed before a later choice was made

Do **not** inflate N by repeating aggregate rows or a `trial_count` field. Count actual evaluated candidates.

DSR can use trial-level Sharpe information plus the candidate's return series, but CSCV/PBO requires an aligned return matrix. If old runs did not save per-period returns, reconstruct them from the frozen code/spec or explicitly mark them unavailable. Do not fabricate PBO from summary statistics.

Use a DSR confidence gate of **0.95**, not “DSR > 1.0”. DSR is a probability-like quantity bounded by 0 and 1.

For overlapping 5/20/60-day labels, use purging/embargo in walk-forward or cross-validation logic so adjacent samples do not leak outcomes across folds.

### 2. Macro data must be point-in-time and revision-aware

Create `market_2026-10-03_v10.sqlite` as a clone/migration. Keep the original untouched.

Every macro observation should include at least:

- `source`
- `series_id`
- `observation_timestamp`
- `published_timestamp`
- `retrieved_timestamp`
- `value`
- `vintage_or_release_id` when available
- `raw_payload_hash`
- `availability_quality` (`exact_release`, `conservative_lag`, `approximate`)

Feature joins must use the latest value whose `published_timestamp <= decision_timestamp`. Never backfill data into time before publication.

Do not hard-code approximate publication lags as if they were exact. Where an official release calendar/archive exists, derive the release timestamp from it. If exact historical availability cannot be proven, use a conservative lag and tag the quality.

Direct-source preference:

- Federal Reserve Board H.4.1 for balance-sheet assets
- U.S. Treasury Fiscal Data for TGA / Treasury series where supported
- New York Fed for reverse repo
- authoritative market-data source for VIX/DXY/equity indexes; if a third-party library is used, mark it as such rather than calling it direct-source

### 3. Funding must be event-driven, not hard-coded to an 8-hour schedule

Ingest actual funding events with venue, symbol, `funding_timestamp`, rate, and any available interval metadata. The execution engine accrues funding from the **event timestamps in the dataset**.

Do not assume every contract always settles every 8 hours. Funding intervals can change over time or by contract. Historical backtests must use the recorded settlement events.

### 4. Execution assumptions must be versioned and conservative

Do not hard-code maker 1.5 bps, taker 4.5 bps, or a single 0.5% MMR as universal historical truth. Create dated/configurable venue schedules:

- maker/taker fees
- funding events
- maintenance-margin tiers by notional
- liquidation fees if modeled
- minimum tick/lot rules where relevant

The execution engine must support at least two fill models:

- `conservative_bar`: bar-touch does not automatically guarantee a passive maker fill; ambiguous same-bar stop/target sequences resolve pessimistically unless finer data resolves ordering
- `research_optimistic`: explicit sensitivity case only, clearly labeled

High-leverage T20 tests should preferentially use the finest reliable bar data available. If mark-price data is absent, flag liquidation as approximate rather than exact.

### 5. Strategy experts should emit a structured forecast, not only a float

A float in [-1,1] is too lossy for probabilistic geometry and Matrix Kelly. Define a strict `ExpertForecast` contract such as:

```python
@dataclass(frozen=True)
class ExpertForecast:
    asset: str
    horizon_bars: int
    expected_return: float
    expected_volatility: float | None
    confidence: float
    direction_score: float       # [-1, 1], diagnostic
    capacity_hint: float | None
    metadata: Mapping[str, Any]
```

Experts may read sanitized structural features and their own history. They may **not** read account equity, leverage, final allocation, future labels, or router output. The environmental state estimator remains descriptive. The router combines expert forecasts using state probabilities; the risk layer sizes the resulting expected-return vector.

All expected-return quantities passed to Matrix Kelly must share a clearly defined horizon/unit.

### 6. Matrix Kelly: Ledoit-Wolf plus deterministic fallback

Use Ledoit-Wolf on the rolling return matrix. Add per-asset and gross-exposure caps. Log every guard activation.

If the covariance condition number exceeds the configured threshold, do not rely on a single arbitrary 50% diagonal blend. Use a deterministic fallback ladder:

1. Ledoit-Wolf covariance
2. eigenvalue floor / additional diagonal shrinkage
3. recompute condition number
4. if still unstable, fall back to independent fractional Kelly for that timestamp
5. if inputs are invalid, reduce exposure to zero rather than inventing a weight

Treat the threshold (initially 50) as a research/config value, not a mathematical constant.

### 7. Continuous geometry should be a competing-risk probability surface

Keep Elliott/fractal geometry as a causal structural generator using **confirmed** pivots only. Exact Fibonacci constants remain markers/placebo controls, not privileged truths.

The neural head should estimate something like:

`P(target ratio r is reached before invalidation by horizon tau | features_t)`

`ratio_grid` must be used to construct labels and map predictions back to price targets.

Prefer a differentiable monotone parameterization over `cummin(sigmoid(logits))`. One acceptable implementation is to construct ratio logits from a base logit minus cumulative `softplus` increments, which makes target-reach probability non-increasing with farther ratios while preserving gradients. If multiple horizons are modeled, enforce or test that probability of reaching a fixed target by time tau is non-decreasing with tau.

Evaluate calibration (Brier score/log loss/reliability), not only P&L. Required ablations:

- generic structural features
- fractal/multiscale features
- continuous geometry features
- named Fibonacci markers
- randomized/neighbor ratio placebos

A geometry head can be retained as a structural representation even if it fails alpha gates, but must not be promoted as predictive alpha without out-of-sample calibration and financial evidence.

### 8. State engine is a model comparison, not an HMM commitment

Implement a common `StateEstimator` interface and at least preserve the deterministic v0.9 state rules as baseline. Candidate probabilistic implementations may include GMM/HMM/change-point methods. Do not select a winner using the final holdout.

Outputs must be state probabilities plus diagnostics (entropy, transition persistence, feature provenance). State names are descriptive; they do not imply long/short action.

### 9. Plugin architecture: registry first, arbitrary auto-import later

Implement a safe plugin registry now. Each plugin should have a manifest, class/interface version, hash, and explicit enablement. Avoid importing arbitrary files dropped into a directory in any process that could later hold execution authority.

Phase 1 is model calibration/retraining with static code. Agentic code mutation is out of scope for this Claude implementation.

### 10. Cross-domain curriculum is accepted but not blocking Stage 1–4

Keep the reusable structural trunk/adapters modular so later pretraining on synthetic/physical/biological systems can attach cleanly. Do not delay data chronology, execution realism, or statistical falsification in order to train the cross-domain curriculum now.

The eventual curriculum should test whether learned operators transfer across domains; it should not be used to manufacture financial validation.

## Required implementation stages

### Stage 0 — Inventory, interfaces, and frozen baseline

**Goal:** establish exactly what exists before changing it.

Deliver:

- repository/package inventory
- baseline hashes verified against `PACKAGE_MANIFEST.json`
- dependency file/environment spec
- tests that run the current v0.9 validation without modifying baseline artifacts
- interface proposal for `ObservationFrame`, `StructureState`, `MarketStateDistribution`, `ExpertForecast`, `StrategyMixture`, `RiskAllocation`, `ExecutionEvent`, and `EvidenceBundle`

Acceptance gate:

- original DB SHA-256 remains unchanged
- v0.9 frozen spec remains unchanged
- current validation tests still pass
- no new backtest result is called “validated”

### Stage 1 — Immutable data migration + proof ledger

Deliver:

- `scripts/migrate_market_v10.py`
- `scripts/build_trial_ledger.py`
- source adapters for funding and macro data
- migrated `market_2026-10-03_v10.sqlite`
- coverage report by source/asset/date
- data-quality/provenance report
- `trial_ledger.jsonl`
- reconstruction plan for missing historical return paths

Acceptance gate:

- tuple/set insertion bugs eliminated
- source DB unchanged
- target DB hash recorded
- duplicate/monotonicity/coverage checks pass
- point-in-time joins pass explicit leakage tests
- funding settlements use observed event timestamps
- ledger identifies actual trials without double counting

### Stage 2 — Core DAG + risk + execution

Deliver:

- typed interfaces/dataclasses
- safe plugin registry
- Ledoit-Wolf Matrix Kelly + fallback ladder
- venue execution engine with configurable fee/margin/funding schedules
- conservative bar-event simulator and same-bar ambiguity policy

Acceptance tests include:

- singular/near-singular covariance
- missing values and zero variance
- gross/per-asset caps
- funding event while position is open vs closed
- funding interval changes
- gap-through stop
- stop and target touched in one bar
- maker touch without guaranteed fill
- tier transition in maintenance margin
- liquidation approximation flags

### Stage 3 — State + structural/geometry learning

Deliver:

- v0.9 deterministic state baseline behind interface
- probabilistic state candidates behind same interface
- causal multiscale pivot/geometry features
- monotone continuous geometry probability head
- label builder using `ratio_grid`
- calibration metrics and placebo/ablation harness

Acceptance gate:

- future mutations cannot change past features or state probabilities
- active/unconfirmed swing endpoints never appear in training features
- ratio monotonicity tests pass
- horizon monotonicity tests pass where enforced
- named ratios are evaluated against continuous and randomized controls

### Stage 4 — Walk-forward evaluation and financial-truth gate

Deliver:

- nested/purged walk-forward evaluator
- DSR implementation with tests
- CSCV/PBO only where aligned return matrices exist
- EvidenceBundle generation
- candidate/structural/rejected verdicts
- protected holdout definition that subsequent tuning cannot access

Acceptance gate:

- every optimization trial is appended to the ledger
- no parameter search sees the protected holdout
- DSR threshold uses 0.95
- failed trials remain in the ledger
- PBO is not computed from summary-only data
- evidence bundle records execution/data/model versions

### Stage 5 — Cross-domain representation curriculum (separate experiment)

Only after Stages 0–4 are reproducible. Add stochastic, chaotic, physical, biological, and network datasets behind a common structural-learning interface. Measure transfer to untouched market tasks. Do not alter financial holdouts based on cross-domain results.

## Do not implement in this pass

- live exchange credentials or order placement
- automatic promotion to live trading
- LLM-written self-modifying production code
- arbitrary plugin execution without manifests/allowlists
- optimization against the protected holdout
- claims that Fibonacci ratios are privileged
- claims that an HMM is the chosen state model
- hard-coded funding interval, universal fee tier, or universal MMR
- vendor/model-compliance decisions unrelated to the research code

## Required working style for Claude

1. Work one stage at a time. Do not write the entire repository in one response.
2. Before each stage, list files to add/change and why.
3. Preserve old files; prefer add-only versioned changes.
4. Provide complete runnable code, not pseudocode or placeholders.
5. Add tests in the same stage as implementation.
6. Run the tests when execution is available and report exact failures rather than masking them.
7. Do not tune parameters merely because a historical result looks bad.
8. Every research result must be tagged `candidate`, `structural_only`, or `rejected` until the statistical gate is passed.
9. Record all new trials, including failures.
10. Stop at the end of each stage for review before starting the next stage.

## First task to Claude

Start with **Stage 0 only**. Inspect the package, verify hashes, map the existing files to the eight DAG layers, and propose the typed interfaces/dataclasses plus the exact Stage 1 file plan. Do not migrate data, train models, or change backtests in Stage 0.
