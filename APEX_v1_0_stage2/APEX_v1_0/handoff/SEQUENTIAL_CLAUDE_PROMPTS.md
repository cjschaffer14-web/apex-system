# Sequential Claude Prompts

Use these prompts one at a time. Always attach this handoff package.

## Prompt 0 — Inventory and interfaces

You are implementing APEX v1.0 from an immutable v0.9 research baseline. Read `handoff/CLAUDE_IMPLEMENTATION_HANDOFF.md` and perform **Stage 0 only**. Verify package hashes and baseline immutability, map existing files to DAG layers, run existing validation where possible, and propose typed interfaces/dataclasses and the exact Stage 1 file plan. Do not migrate the database, train models, change historical strategy definitions, or create new performance claims. Return changed files plus test output.

## Prompt 1 — Data and ledger

Stage 0 has been approved. Implement **Stage 1 only** exactly as specified in the handoff. Clone the baseline SQLite database to a versioned v10 database; add point-in-time macro/funding provenance; ingest funding as timestamped events rather than a fixed schedule; and build the trial ledger. Do not compute PBO unless aligned per-period returns exist. Produce coverage/leakage tests and preserve the original DB byte-for-byte. Stop after tests and report unresolved data-quality issues.

## Prompt 2 — Risk and execution

Stage 1 has been approved. Implement **Stage 2 only**. Add typed DAG interfaces, safe plugin registry, structured ExpertForecast, Ledoit-Wolf Matrix Kelly with deterministic stability fallback, and a configurable venue event simulator. Do not hard-code universal fee/MMR/funding assumptions. Implement conservative same-bar ambiguity and maker-fill rules. Add tests for singular covariance, funding interval changes, gaps, stop/target collisions, maintenance-margin tiers, and liquidation approximation flags. Do not train the neural model yet.

## Prompt 3 — State and geometry

Stage 2 has been approved. Implement **Stage 3 only**. Preserve the v0.9 deterministic state classifier as baseline. Add probabilistic state candidates behind a common interface, causal confirmed-pivot structural operators, and a continuous target-before-invalidation geometry head using the ratio grid for labels and inference. Use differentiable monotone parameterization. Include calibration metrics and named-ratio/random-ratio ablations. Do not select a winner using the protected holdout.

## Prompt 4 — Financial-truth evaluation

Stage 3 has been approved. Implement **Stage 4 only**. Build nested/purged walk-forward evaluation, DSR, aligned-return CSCV/PBO, immutable EvidenceBundles, and a protected holdout. Every search candidate—including failures—must append to the trial ledger. Use DSR 0.95 as the confidence threshold. Never compute PBO from summary-only metrics. Return candidate/structural_only/rejected verdicts without production promotion.
