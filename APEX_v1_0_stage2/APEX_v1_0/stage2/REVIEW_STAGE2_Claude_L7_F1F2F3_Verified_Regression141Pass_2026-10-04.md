# Stage 2 Layer 7 F1–F3 verification — Claude — 2026-10-04

## Verdict

ACCEPT. ChatGPT's F1–F3 follow-up patch closes all three findings. The complete regression passes on macOS arm64 with 141 tests (the previous 138 plus ChatGPT's 3 new pinning tests), 0 failures, 0 errors, 0 skips, 0 ResourceWarnings. Frozen evidence and statistics outputs are unchanged. Layer 7 is ready for Stage 2 acceptance, subject to the owner decisions below.

## What was checked

1. **Patch integrity.** `APEX_Stage2_ChatGPT_L7_F1_F2_F3_Fixes_2026-10-04.zip` passed `unzip -t`. The SHA256 of `apex_v10/stage2_layer7.py` (`565f59a9…afc146`) and `tests_v10/test_stage2_layer7_ChatGPT.py` (`c14ce973…b55ecd`) match `PATCH_CHECKSUMS_ChatGPT_L7_F1_F2_F3_2026-10-04.json`. Only those two code files changed; pre-patch copies are kept in `stage2/pre_F1F2F3_backup_2026-10-04/`.
2. **Full regression.** `scripts/run_tests.py` in the project venv (Python 3.14.7, numpy 2.5.3): 141 tests, PASS. Log: `stage2/test_output_full_regression_141_with_ChatGPT_L7_F1F2F3_macOS_2026-10-04.txt`.
3. **Frozen evidence.** `data_v10/market_2026-10-03_v10_1a.sqlite` SHA256 `0861688a…acc908` matches `DB_MANIFEST_1A.json`. The statistics runner re-verified its parent hashes and completed; its regenerated JSON matches the stored `STATISTICS_STAGE2_ChatGPT_2026-10-04.json` on all 4,482 floats (max difference 2.2e-16, inside atol=1e-12) with identical keys, statuses and strings.
4. **Findings re-probed.** `stage2/probe_L7_F1F2F3_followup_Claude_2026-10-04.py` re-runs the original scenarios against the new API (output in `probe_L7_F1F2F3_followup_output_Claude_2026-10-04.txt`):
   - F1: an ETH weight on a BTC-PERPETUAL schedule is refused ("asset/schedule symbol mismatch"); a quote whose symbol differs from the schedule is refused; a matching ETH mapping still fills.
   - F2: an ~11.5-day-old quote is refused as stale in both `rebalance` and `liquidation_required`.
   - F3: after a `FundingPositionClose` at the last accrual, the 08:00 UTC settlement succeeds; accrual after the close is refused.

## Code review notes

- Staleness is measured from `quote.ts` (observation time), not `known_at_ts`, which is the conservative choice.
- `FundingPositionClose` requires coverage accrued exactly through the close timestamp and sorts between accruals and settlements at the same timestamp, so a close and settlement at 08:00 apply in the right order.
- `Quote.symbol` was added as the first positional field. All in-repo callers were updated; any external caller that builds `Quote` positionally must be updated too.

## New observation for ChatGPT (low, non-blocking)

- **F4 (low): a closed symbol can never reopen in the same ledger.** `FundingLedger.closed` is permanent, so a strategy that closes BTC-PERPETUAL and reopens it in a later funding session is refused ("accrual after explicit position close"). This fails closed but would block a multi-session replay, the same class of problem as F3. Suggested fix: clear the symbol from `closed` once the next settlement is recorded, or add an explicit timestamped `FundingPositionOpen` event. Please pin it with a test. Claude does not consider this blocking for Stage 2 acceptance, because no strategy replay runs in Stage 2.

## Not changed by Claude

Claude did not edit ChatGPT's Layer 7 code, guard defaults, frozen files or strategies, and did not run `write_stage_manifest.py`.

## Open owner decisions

- Confirm the guard defaults: condition-number cap 1e4, minimum history 60/20, volatility-spike guard (20-period volatility above 2x halves gross).
- Approve writing the Stage 2 manifest with `scripts/write_stage_manifest.py` (excluding .DS_Store files). F1–F3 are now closed, so this is the last gate.
- Decide whether F4 must be fixed before the manifest is written or can move to Stage 3.
