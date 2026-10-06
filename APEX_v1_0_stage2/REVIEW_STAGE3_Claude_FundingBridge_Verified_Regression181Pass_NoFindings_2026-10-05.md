# Claude verifier review - Stage 3 funding bridge (2026-10-05, ~13:25 EDT)

Scope: reduced-scope single verification pass (CLAUDE NEEDED from ChatGPT). Short form.

- **Result: PASS.** Full regression `scripts/run_tests.py` on a scratch merge of the Stage 2 tree + patch: **181 tests, 0 failures, 0 errors, 0 skipped, 0 ResourceWarnings** (164 baseline + 17 new). Log: `test_output_full_regression_181_with_stage3_funding_bridge_macOS_2026-10-05.txt`.
- **ZIP checksum:** `APEX_Stage3_Funding_Bridge_2026-10-05.zip` 13,203 bytes, SHA256 acf266e8...087e9a = published value. Three code/test files match `PATCH_CHECKSUMS.json`.
- **Merge:** additions only (apex_v10/stage3_funding.py, scripts/ingest_stage3_funding.py, tests_v10/test_stage3_funding.py, stage3/*). No Stage 2 file overwritten. Merge verified in a scratch copy; the real stage2 tree was NOT modified (owner/ChatGPT to merge).
- **Frozen hashes:** Stage 1A DB `data_v10/market_2026-10-03_v10_1a.sqlite` = 0861688a...acc908 (unchanged). Stage 2 `allocator.py` = acb9093170265a5ab9d6a792c0b73bffcf2ca7135497a76193d132768cc1e504 (unchanged, matches manifest). `STAGE2_MANIFEST.json` SHA256 2dc63113...d367; all 1,644 entries re-verified, 0 mismatches. Manifest not rewritten.
- **Settlement/PIT review (stage3_funding.py):** no findings. AnchoredFundingLedger requires explicit first open before accrual, keeps Stage 2 close/reopen/settlement rules, rejects duplicate/out-of-order/currency-mismatch opens. Observation availability = max(funding_ts, archived retrieved_ts) (fail-closed, no inferred publication time). Duplicate observations rejected, no nearest-neighbour/averaging. API-error 200 payloads rejected after raw hashing. Cross-reference is presence-only with fill_evidence=False.
- **Notes (not findings):** (1) Mac ingestion not run; validate Kraken v4 endpoint/symbol response on the Mac as ChatGPT said. (2) Stage 2 tree remains unmodified; the 181 count holds only once the additions are merged.
