# Stage Acceptance Checklist

## Stage 0
- [ ] Verify baseline package manifest and SHA-256 hashes.
- [ ] Verify original SQLite hash; do not modify it.
- [ ] Run existing v0.9 validation tests or document missing dependency/runtime blockers.
- [ ] Map existing code to DAG layers.
- [ ] Propose typed interfaces and file plan only.

## Stage 1
- [ ] Clone DB to a new v10 filename.
- [ ] Add source/provenance/retrieval/release metadata.
- [ ] Funding events are timestamp-driven; no fixed 8h assumption.
- [ ] Macro joins enforce published_timestamp <= decision_timestamp.
- [ ] Build coverage and point-in-time leakage tests.
- [ ] Build trial ledger with one row per actual trial.
- [ ] Ledger references per-period returns; missing paths explicitly marked.
- [ ] Original database remains byte-identical.

## Stage 2
- [ ] ExpertForecast has common horizon and expected-return units.
- [ ] State estimator cannot size trades.
- [ ] Experts cannot read account/leverage/router outputs/future labels.
- [ ] Ledoit-Wolf covariance implemented.
- [ ] Condition-number fallback ladder tested.
- [ ] Gross and per-asset caps tested.
- [ ] Fees/margins/funding are config/time/venue aware.
- [ ] Conservative same-bar ambiguity policy implemented.
- [ ] Funding interval changes supported.

## Stage 3
- [ ] Confirmed pivots only.
- [ ] ratio_grid is used in labels and inference.
- [ ] Target-before-invalidation definition is explicit.
- [ ] Ratio reach probabilities are monotone with target distance.
- [ ] Horizon behavior is checked/enforced.
- [ ] Brier/log-loss calibration metrics included.
- [ ] Fibonacci markers are placebo-controlled.
- [ ] Deterministic state baseline retained.

## Stage 4
- [ ] Walk-forward split is nested/purged/embargoed where needed.
- [ ] Every search candidate is logged before result selection.
- [ ] DSR gate = 0.95.
- [ ] PBO uses aligned per-period return matrices only.
- [ ] Protected holdout is inaccessible to tuning.
- [ ] EvidenceBundle contains code/data/execution hashes.
- [ ] Failed and rejected candidates remain in ledger.

## Stage 5
- [ ] Cross-domain curriculum is separated from financial validation.
- [ ] Transfer evaluated on untouched financial tasks.
- [ ] Financial holdouts are not modified after seeing transfer results.
