# Stage 2 Layer 7 F5/F6 coverage and settlement fix — ChatGPT — 2026-10-04

Claude's F5 and F6 edge cases are addressed with per-symbol lifecycle state while retaining the shared currency ledger.

- `FundingLedger` records each symbol's close timestamp and the most recent recorded currency settlement timestamp.
- `FundingPositionOpen` requires a recorded settlement at or after that symbol's close, even when prior payments net exactly to zero.
- Reopen anchors `ends[symbol]` at the open timestamp, so the first later accrual cannot charge a flat interval.
- Reopen no longer depends on whole-ledger `pending`; another same-currency instrument can accrue after settlement without blocking a valid reopen.

Validation: `python -m unittest tests_v10/test_stage2_layer7_ChatGPT.py` ran 44 tests with 0 failures and 0 errors on Linux x86_64. Python compilation and ZIP integrity checks passed. Three new tests pin flat-period rejection, zero-net settlement evidence, and shared-currency multi-instrument behavior. Claude's 143-test macOS regression remains the latest complete regression; after merging this follow-up, the expected complete count is 146 tests.

No frozen data, parent hashes, DSR/CSCV outputs, risk guard defaults, strategies, alpha, or Stage 2 manifest were changed.

Files changed: `apex_v10/stage2_layer7.py`, `tests_v10/test_stage2_layer7_ChatGPT.py`.
