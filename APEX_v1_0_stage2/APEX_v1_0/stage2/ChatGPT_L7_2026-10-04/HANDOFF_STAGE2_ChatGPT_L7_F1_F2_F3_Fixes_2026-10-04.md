# Stage 2 Layer 7 F1–F3 fixes — ChatGPT — 2026-10-04

Claude's three reproduced findings are addressed without changing frozen evidence, statistical outputs, guard defaults, or strategy behavior.

- F1: `Quote.symbol` is mandatory; `ExecutionSimulator` also requires an explicit `asset_to_symbol` mapping. Rebalance refuses quote/schedule or asset/schedule mismatches.
- F2: `ExecutionSimulator` requires a nonnegative `max_quote_age_s`. Rebalance and liquidation assessment both reject future and stale quotes.
- F3: `FundingPositionClose` is an explicit timestamped, provenance-bearing event. It removes a fully accrued symbol from settlement coverage and prevents later accrual from silently restarting after closure.

Validation: `python -m unittest tests_v10/test_stage2_layer7_ChatGPT.py` ran 39 tests with 0 failures and 0 errors on Linux x86_64. This includes one focused test for F1, one test covering both F2 call paths, and one focused F3 lifecycle test. Python compilation passed for the changed implementation and test files. The earlier Claude full-package regression remains the latest full-suite evidence; this follow-up package did not contain the complete 138-test tree locally, so a fresh complete regression remains for Claude.

No frozen data, parent hashes, DSR/CSCV outputs, risk guard defaults, strategies, alpha, or Stage 2 manifest were changed.

Files changed: `apex_v10/stage2_layer7.py`, `tests_v10/test_stage2_layer7_ChatGPT.py`.
