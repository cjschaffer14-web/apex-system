# Pre-review verification: APEX v1.0 Stage 1A

**Date:** 2026-10-04
**Source:** `APEX_v1_0_stage1a_complete.zip` (sha256 `7ea36a02bb0c5f9130edb3c4bbc9e07d296c5381f8018cd32b90ee528bb99d52`), unpacked unchanged into `APEX_v1_0/`.
**Environment:** macOS 26.6.2 arm64; Python 3.14.7; SQLite 3.51.0; numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, scikit-learn 1.9.1 (the versions pinned in `requirements-v10.txt`).

These checks confirm that the package matches what its report claims. They are not a review of the methodology.

## Results

| Check | Result |
|---|---|
| `stage1a/STAGE1A_MANIFEST.json`: 1,639 files plus 12 core artifacts re-hashed | **All match** |
| `PACKAGE_MANIFEST.json` (45 files) | **All match** |
| `stage1/STAGE1_MANIFEST.json` (642 files) | 2 differ, both test files (`test_stage1_pit_coverage.py`, `test_stage1_sources.py`), as disclosed in report §1 |
| Stage 1 manifest / DB file / ledger hashes | `a4591d7e…`, `2b5f420c…`, `70661932…`: **match the report** |
| Stage 1A DB file hash | `0861688a…cc908`: **matches** |
| Stage 1A ledger hash | `7740820d…903ba`: **matches** |
| Stage 1A DB `integrity_check` / foreign-key violations | `ok` / 0 |
| Stage 1A DB row counts (8 tables) | **All match report §2** |
| Ledger records / DSR rows | 1,483 / 277: **match** |
| Forensic outcomes (148 trials) | 59 series / 86 statistic-only / 3 mismatch: **match** |
| Evidence gate grades (52 families × 6 windows) | 65 PASS / 92 PARTIAL / 155 FAIL: **match** |
| Stray files (`.DS_Store`, `__pycache__`, `*.pyc`) | None |
| Secret/key pattern scan (excluding raw source archives) | No hits |
| Full test suite, one process (`scripts/run_tests.py`) | **74 / 75 pass, 0 ResourceWarnings, 1 failure (see below)** |

The report's 75/75 result came from running the suite one module at a time, on Linux x86_64 with Python 3.13.5, numpy 2.3.5, pandas 2.2.3, scipy 1.17.0 and scikit-learn 1.8.0. That environment does not match the pinned requirements. The full log of this run is in `logs/full_suite_macos_arm64.txt`.

## The one failure, which is a portability issue

`test_stage0_baseline.FrozenValidation.test_v09_validation_reruns_identically_and_leaves_baseline_untouched`

The frozen v0.9 validation re-runs, and **all 11 of its checks pass**. However, one recorded value is not bit-identical to the frozen output:

| Check | Frozen | This run |
|---|---|---|
| `matrix_kelly_near_singular_covariance_is_finite_and_gross_capped`, `max_gross` | `3.0000000000000004` | `3.0` |

The difference is one unit in the last place, on a gross-leverage cap of 3.0. The baseline database hash is identical, and the baseline tree is unchanged.

**Likely cause:** a different floating-point/BLAS path (arm64 vs x86_64, and different numpy/scipy versions).

**Suggested resolution, for the reviewer to decide.** Leave the frozen evidence alone. Either:

- record this as a known cross-platform difference, or
- have a later stage compare this field with a tolerance (e.g. 1e-12) while keeping exact comparison for everything else.

Nothing in the package was changed to make this test pass.
