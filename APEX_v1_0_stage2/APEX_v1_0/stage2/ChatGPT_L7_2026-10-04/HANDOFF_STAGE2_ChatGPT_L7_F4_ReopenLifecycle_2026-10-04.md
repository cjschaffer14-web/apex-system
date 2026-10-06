# Stage 2 Layer 7 F4 lifecycle fix — ChatGPT — 2026-10-04

Claude's non-blocking F4 finding is addressed with explicit lifecycle evidence rather than implicit state clearing.

- Added `FundingPositionOpen`, a timestamped, currency- and provenance-bearing event.
- Reopen is accepted only for a previously closed symbol and only after the prior session's pending funding has been settled.
- Reopen sorts after a same-timestamp settlement and explicitly clears the closed state, allowing later exact accruals.
- Reopening an active symbol or reopening before settlement fails closed.

Validation: `python -m unittest tests_v10/test_stage2_layer7_ChatGPT.py` ran 41 tests with 0 failures and 0 errors on Linux x86_64. Python compilation and ZIP integrity checks passed. Two new tests pin close → settlement → reopen → later accrual and the invalid-reopen cases. Claude's 141-test macOS regression remains the latest complete regression; after merging this follow-up, the complete suite should contain 143 tests.

No frozen data, parent hashes, DSR/CSCV outputs, risk guard defaults, strategies, alpha, or Stage 2 manifest were changed.

Files changed: `apex_v10/stage2_layer7.py`, `tests_v10/test_stage2_layer7_ChatGPT.py`.
