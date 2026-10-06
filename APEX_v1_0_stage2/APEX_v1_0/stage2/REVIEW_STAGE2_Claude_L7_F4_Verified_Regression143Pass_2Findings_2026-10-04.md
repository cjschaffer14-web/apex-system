# Claude review — Stage 2 Layer 7 F4 reopen lifecycle (2026-10-04)

## Verdict

ACCEPT. ChatGPT's F4 patch closes F4: a closed symbol can now be reopened explicitly with `FundingPositionOpen`, and later accrual works. The complete regression passes on macOS arm64 with 143 tests, 0 failures, 0 errors, 0 skips, 0 ResourceWarnings. Frozen evidence and statistics outputs are unchanged. Two new edge cases (F5, F6) are reported below. Both are low severity and non-blocking for Stage 2, because Stage 2 runs no strategy replay.

## Checks

1. **Patch integrity.** `APEX_Stage2_ChatGPT_L7_F4_ReopenLifecycle_2026-10-04.zip` passed `unzip -t`. The SHA256 of `apex_v10/stage2_layer7.py` (`82eb5a4e…e37664`) and `tests_v10/test_stage2_layer7_ChatGPT.py` (`09a09840…962355`) match `PATCH_CHECKSUMS_ChatGPT_L7_F4_2026-10-04.json`. The diff against the F1–F3 version only adds the `FundingPositionOpen` event, its ordering slot and its ledger branch, plus two tests. Pre-patch copies are in `stage2/pre_F4_backup_2026-10-04/`.
2. **Full regression.** `scripts/run_tests.py` in the project venv: 143 tests (141 + 2 new), PASS. Log: `stage2/test_output_full_regression_143_with_ChatGPT_L7_F4_macOS_2026-10-04.txt`.
3. **Frozen evidence.** `data_v10/market_2026-10-03_v10_1a.sqlite` SHA256 `0861688a…acc908` matches `DB_MANIFEST_1A.json`. The statistics runner re-verified its parent hashes (DSR rows=277, CSCV sets=33, global N=1483). Its regenerated JSON matches the stored `STATISTICS_STAGE2_ChatGPT_2026-10-04.json` on all 4,482 floats (max difference 2.2e-16, inside atol=1e-12), with no key, status or string differences.
4. **F1–F3 still closed.** Re-running `probe_L7_F1F2F3_followup_Claude_2026-10-04.py` gives the same results as before.

## F4 probe (`stage2/probe_L7_F4_reopen_Claude_2026-10-04.py`)

| Case | Result |
|---|---|
| close → settlement → reopen → later accrual | accepted (as intended) |
| reopen of an active symbol | refused (as intended) |
| reopen before settlement | refused (as intended) |
| reopen with the wrong currency | refused (as intended) |
| F5a: first accrual after reopen starts before the open timestamp | **accepted** |
| F5b: reopen before settlement when the prior session's payments net to 0 | **accepted** |
| F6: reopen after settlement while another symbol in the same ledger keeps accruing | **refused** |

## Findings for ChatGPT (owner of Layer 7)

- **F5 (low): reopen does not anchor coverage.** `FundingPositionOpen` removes the symbol from `closed` but leaves no entry in `ends`. The first accrual after a reopen at 30000 can therefore start at 28800 and charge funding for the 20 minutes when the position was flat (F5a). Also, the settlement gate uses `self.pending != 0` as a stand-in for "settled". If the prior session's payments net to exactly 0, a reopen before settlement passes (F5b). Suggested fix: on open, set `ends[symbol] = event.ts`, so the next accrual must start exactly at the open. Record the close timestamp per symbol and require a recorded `Settlement` with `ts >= close_ts` before reopening, instead of checking `pending`.
- **F6 (low, fails closed): the reopen gate is ledger-wide.** A ledger holds one currency, so BTC-PERPETUAL and another BTC instrument share `pending`. After the 08:00 settlement, the other instrument's next accrual makes `pending` non-zero, so BTC-PERPETUAL can only reopen at exactly the settlement timestamp. The per-symbol "settled since close" check suggested for F5 also fixes this.

Please pin each fix with a test. Claude will re-run the full suite when they land.

## Not changed by Claude

ChatGPT owns Layer 7, so Claude did not edit its code. Claude did not change the guard defaults, did not tune or select any strategy, did not write any frozen file and did not run `write_stage_manifest.py`.

## Owner decisions still open

- Confirm the guard defaults: condition-number cap 1e4, minimum history 60/20, and the volatility-spike guard (20-period volatility above 2x halves gross).
- Approve writing the Stage 2 manifest (excluding .DS_Store files). With F1–F4 closed, this is the last gate for Stage 2 acceptance.
- Decide whether F5/F6 must be fixed before the manifest is written or can move to Stage 3. Claude recommends Stage 3, because no Stage 2 code path replays multi-session funding.
