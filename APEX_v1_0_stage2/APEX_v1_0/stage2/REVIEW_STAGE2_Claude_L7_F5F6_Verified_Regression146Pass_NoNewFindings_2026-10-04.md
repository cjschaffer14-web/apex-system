# Stage 2 Layer 7 F5/F6 verification — Claude — 2026-10-04

**Verdict:** Accept ChatGPT's F5/F6 coverage-and-settlement patch. F5 and F6 are closed. The complete regression passes with the expected 146 tests. Frozen evidence is unchanged. Claude found no new blocking or non-blocking defects.

Work window: 21:08 to about 21:20 EDT (estimate was 21:28 EDT).

## Inputs (Drive names)
- APEX_Stage2_ChatGPT_L7_F5_F6_CoverageSettlement_2026-10-04.zip
- HANDOFF_STAGE2_ChatGPT_L7_F5_F6_CoverageSettlement_2026-10-04.md
- TESTS_STAGE2_ChatGPT_L7_F5_F6_2026-10-04.txt

## Integrity and merge
- The ZIP integrity test passed.
- The SHA256 values of `apex_v10/stage2_layer7.py` (cab10047…efb36) and `tests_v10/test_stage2_layer7_ChatGPT.py` (08c2c13e…b2a2f) match `PATCH_CHECKSUMS_ChatGPT_L7_F5_F6_2026-10-04.json`.
- The diff is minimal. It adds `close_ts` and `last_settlement_ts` to the ledger and records the close timestamp. The reopen gate changes from `pending != 0` to "a recorded settlement at or after this symbol's close". On reopen, `ends[symbol]` is set to the open timestamp, and `last_settlement_ts` is set on settlement. The patch also adds three tests.
- The pre-patch copies are in `stage2/pre_F5F6_backup_2026-10-04/`. ChatGPT's handoff, test log, checksums and ZIP are in `stage2/ChatGPT_L7_2026-10-04/`.

## Complete regression
`scripts/run_tests.py` on macOS arm64 (APEX_v1_0_stage2/.venv) reports **PASS: 146 tests (the previous 143 plus ChatGPT's 3 new tests), 0 failures, 0 errors, 0 skips, 0 ResourceWarnings**. The full log is in `test_output_full_regression_146_with_ChatGPT_L7_F5F6_macOS_2026-10-04.txt`.

## Probe (`probe_L7_F5F6_coverage_settlement_Claude_2026-10-04.py`): 12/12 as expected
| Case | Result |
|---|---|
| F4 close → 08:00 settlement → reopen → accrual | accepted |
| F5a accrual 28800→32400 after a reopen at 30000 (flat-period charge) | refused (funding gap or overlap) |
| F5b zero-net close, reopen before settlement | refused |
| F5b zero-net close, reopen after settlement | accepted |
| F6 another BTC instrument accrues after settlement, reopen at 30000 | accepted |
| Stale settlement: second close, then reopen before the next settlement | refused |
| Second cycle with the next-day settlement | accepted |
| Settlement after a reopen with no accrual covering it | refused (fails closed) |
| Settlement after a reopen with accrual through it | accepted |
| Close, settle and reopen all at 08:00 | accepted |
| Reopen with the wrong currency | refused |
| Reopen of an active symbol | refused |

## Frozen evidence
- The Stage 1A database `market_2026-10-03_v10_1a.sqlite` still has SHA256 0861688a…acc908, which matches `DB_MANIFEST_1A.json`.
- `stage2_statistics` does not import Layer 7, so the DSR/CSCV outputs cannot be affected. They were verified at the F4 step (4,482 floats, maximum difference 2.2e-16).

## Observation (not a defect, Stage 3 note)
A symbol that has never been closed can still begin its first accrual at any `start_ts`. Initial coverage is anchored only by the first accrual, and `FundingPositionOpen` applies only to reopens. That matches the existing design and is outside the F5 scope. If Stage 3 replays multi-session funding from position-entry events, consider letting `FundingPositionOpen` also anchor first opens.

## Not changed by Claude
Claude did not edit ChatGPT's Layer 7 code beyond merging the verified patch. Claude also did not change the guard defaults, did not tune strategies, did not write any frozen file and did not run `write_stage_manifest.py`.

## Owner decisions still open
1. Confirm the guard defaults: condition-number cap 1e4, minimum history 60/20, and the volatility-spike guard (20-period volatility above 2x halves gross).
2. Approve writing the Stage 2 manifest (excluding .DS_Store files). With F1–F6 closed and 146/146 tests passing, this is the last gate for Stage 2 acceptance.
