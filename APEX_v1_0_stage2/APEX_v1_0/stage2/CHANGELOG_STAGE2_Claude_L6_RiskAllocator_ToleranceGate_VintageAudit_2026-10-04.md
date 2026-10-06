# Stage 2: Claude's work log (Layer 6 and the tolerance gate)

**Date:** 2026-10-04 (an automated scheduled run, `apex-system-check`)
**Instructions followed:** the Google Doc "APEX System Collaboration" (Stage 1A **ACCEPT WITH CONDITIONS**; Stage 2 approved). The doc assigns Claude Layer 6 (risk/portfolio), point-in-time and fail-closed safeguards, and review against the frozen baseline. ChatGPT owns the Layer 7 items (Deribit funding cash flows, fee/slippage/margin simulator, DSR/CSCV runners). None of those were started here.
**Parent:** `APEX_v1_0_stage1a_complete.zip`, sha256 `7ea36a02bb0c5f9130edb3c4bbc9e07d296c5381f8018cd32b90ee528bb99d52`. It was unpacked from `APEX_v1_0_stage1a_review_package.zip` into `APEX_v1_0_stage2/`. The original zips and folders were not touched.
**Environment:** macOS arm64, Python 3.14.7, with the pinned numpy 2.5.3, pandas 3.0.5, scipy 1.18.1 and scikit-learn 1.9.1 in `../.venv`.

## Rules followed

- No strategy tuning, no new alphas and no parameter searches. Every RiskConfig default is either a frozen v0.8/v0.9 value (gross cap 3.0, per-asset cap 2.0, half Kelly, long-only) or a fixed, conservative guard constant. No backtest was run, so no performance claim is made.
- No frozen evidence, database, ledger or report was modified. The baseline-manifest tests still pass.

## Change 1: cross-platform tolerance gate (Stage 2 step 1)

- **Rationale.** On macOS arm64, the frozen v0.9 check `matrix_kelly_near_singular_covariance_is_finite_and_gross_capped` reports `max_gross = 3.0`; the frozen value (from Linux x86_64) is `3.0000000000000004`. The difference is one unit in the last place, from a different BLAS path.
- **Change.** `stage0/run_v09_validation.py` gains `equivalent_within(a, b, atol=1e-12)` and two new report fields, `all_equivalent` and `tolerance_atol`.
  - Only float values are compared with a tolerance, and it is absolute only (atol = 1e-12, rtol = 0).
  - Booleans, integers, strings and JSON structure must still match exactly, so a pass flag can never be rescued by the tolerance.
  - The exact comparison `all_identical` is still reported. Acceptance now requires `all_equivalent` and an identical database hash.
- **Tests.** `tests_v10/test_stage0_baseline.py` asserts that every difference is at most 1e-12. The new test `test_tolerance_gate_is_narrow` proves the gate rejects flag flips, bool/int coercion, integer changes, structural changes, `inf`, and drifts of 1e-9.
- **Affected layer.** Test harness only.

## Change 2: Layer 6 risk allocator (Stage 2 step 4)

The allocator is new code in `apex_v10/risk/allocator.py`. `LedoitWolfKellyAllocator` implements the existing `interfaces.RiskAllocator` contract and returns `interfaces.RiskAllocation`.

| Mechanism | What it does |
|---|---|
| Ledoit-Wolf shrinkage | Closed-form shrinkage toward a scaled identity. Matches `sklearn.covariance.ledoit_wolf` to rtol 1e-12 (tested). |
| Fallback ladder | Steps down in the existing `COVARIANCE_METHODS` order: `ledoit_wolf` → `ledoit_wolf+eigen_floor` (condition number capped at 1e4) → `independent_fractional_kelly` (under 60 observations, or a single asset) → `zero_exposure` (under 20 observations, zero or non-finite variance, or no forecasts). |
| Sizing | Fractional Kelly: f = k·Σ_h⁻¹·μ. μ is the mixture's horizon log return. Σ is scaled from the period to the horizon by horizon/period, assuming i.i.d. returns (logged). |
| Regime guard | A gross multiplier of at most 1 for each regime label. A high-entropy (uncertain) state gets its own multiplier. With `require_state`, a missing state means zero exposure. |
| Market-condition guard | If volatility over the last 20 periods is more than 2× the full-window volatility, the gross limit is halved. |
| Volatility targeting | An optional ceiling on ex-ante horizon volatility. It only ever scales positions down. |
| Leverage bounds | Per-asset cap; net cap = min(net_cap, dynamic gross cap); dynamic gross cap. Caps are enforced exactly in floating point, stepping down one ULP at a time if needed, so the frozen module's 3.0000000000000004 cannot recur. |
| Point-in-time safeguards (fail closed) | `ReturnsWindow` stamps each row with its `known_at_ts`. A row or state known after `decision_ts` raises `PointInTimeViolation`. A raw float matrix is refused (`TypeError`). Rows containing a NaN are dropped, never filled. |
| Audit trail | Every rung change and every guard firing is recorded in `guard_events`. `allocator_id` = `lw_kelly@<first 12 hex characters of the config's sha256>`. |

- **Deliberate tightening.** `allocate()` takes a `ReturnsWindow` rather than a bare `Sequence[Sequence[float]]`. The runtime Protocol check still passes (tested). Callers in Layer 7 or the DSR harness must therefore supply timestamps.
- **Tests.** `tests_v10/test_stage2_risk.py` contains 21 tests. They cover:
  - the sklearn match;
  - determinism;
  - each ladder rung, including the frozen v0.9 near-singular stress case (gross ≤ 3.0 exactly);
  - point-in-time refusals;
  - every guard, and that a guard cannot raise exposure;
  - the exact cap;
  - Protocol conformance.

## Change 3: vintage admissibility audit (Stage 2 step 6), added 16:30 EDT in a follow-up run

- **Rationale.** The review requires that TGA stay excluded, that the 497 edited RRP rows stay excluded row by row, and that market records keep their provenance. Before this change, Stage 1A tests covered most of this, but nothing pinned the exact evidence sets or the 497 count. A later Stage 2 change could therefore widen the evidence set without any test failing.
- **Change.** A new read-only test, `tests_v10/test_stage2_admissibility.py`, opens the database with `mode=ro`. It has 5 tests:
  - `EVIDENCE_VINTAGES` and `EVIDENCE_TIMING` equal exactly the sets the review accepted.
  - `latest_vintage`, `edited_after_release` and `unverified` never pass, under any timing.
  - Every TGA row (3,203) is `unverified` and not evidence-grade.
  - Exactly 497 RRP rows are `edited_after_release`, and none of them is evidence-grade. The other 2,689 RRP rows are.
  - Treasury par yields and VIX are `market_record`, and so is all exchange funding. There are 0 orphan provenance IDs in `macro_observations` and `funding_events`.
- **Affected layer.** Test harness only. No data, code or report was changed.

## Verification

`scripts/run_tests.py --out stage2/test_output_with_admissibility_audit.txt`: **PASS. 102 tests, 0 failures, 0 errors, 0 ResourceWarnings.** That is the original 75, plus 1 tolerance-gate test, 21 risk tests and 5 admissibility tests. The previous macOS failure is resolved. The earlier 97-test log is still in `stage2/test_output.txt`.

## Hashes, against `stage1a/STAGE1A_MANIFEST.json`

| Path | Status | sha256 |
|---|---|---|
| `stage0/run_v09_validation.py` | changed | `bdb1443726b024a1d865653f0daad3f99b7195094e534c9130d2bfaea024022b` |
| `tests_v10/test_stage0_baseline.py` | changed | `c89d34deafd1e5294cf00922711962358e0d4ecfddf230e11316eaa5f32a5a02` |
| `apex_v10/risk/__init__.py` | new | `b9304a1bbe4326c1eb5d16d922aebb3539aa84fa744746628b96b62249ea9111` |
| `apex_v10/risk/allocator.py` | new | `acb9093170265a5ab9d6a792c0b73bffcf2ca7135497a76193d132768cc1e504` |
| `tests_v10/test_stage2_risk.py` | new | `76fb2e24102fd78f80e89ff5739f6e0bba9305b3c9350a4d157a0a537363212c` |
| `tests_v10/test_stage2_admissibility.py` | new | `bfef957792f81d96af8edd8c0ac3ee508f5f3ec764ec196a1abf5bf467c76d71` |

No other file in the 1,639-file manifest is missing or changed. A `.DS_Store` file (Finder metadata) appeared in the working copy. It is not ours, and it must be excluded from any Stage 2 package.

## For the owner and ChatGPT

1. **Layer 7 handoff.** Pass the execution engine a `RiskAllocation`. When the DSR/CSCV harness calls the allocator, build a `ReturnsWindow` with real `known_at_ts` values; returns that come from a ledger CSV need their row timestamps.
2. **Defaults to confirm (not tuned):** the condition-number cap of 1e4, the 60/20 observation minimums, and the 20-period / 2× / 0.5 volatility-spike guard. Any change to them should be logged as a configuration change, not treated as a search.
3. **Still to do:** a Stage 2 manifest, written with `scripts/write_stage_manifest.py`, once the Layer 7 work lands.
