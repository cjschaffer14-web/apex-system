# APEX profit-first implementation handoff — 2026-10-07

Saved in the actual repository: `/Users/chris/Downloads/APEX System/apex_v2/`.
Base Git commit: `8ae92ae8853922630e4dc8d781e1dc430521cbf4`. Edits are saved, not committed. The existing apex_v2 tree was already untracked; no existing user changes were reset. The separate Observatory update in `/Users/chris/Downloads/APEX_Global_Arbitrage_Observatory_Update/` was also patched. Existing strategies, governor, replay, original backtests and broader APEX strategy definitions were preserved.

## Actual launch status

Mac execution completed: 52 integrated tests and 15 Observatory tests passed; saved Kraken recording audited; one finite public observation run completed and exited. No continuous runner was started, restarted or duplicated. No live mode, live orders, signing, bridge execution, secrets or private credentials were used. Public Coinbase/Kraken/DexScreener were reachable for BTC and ETH. Only Coinbase L1 qualified as executable; Kraken ticker and DexScreener remained references. This produced one executable economic venue per asset, zero cross-venue episodes and no decisions to trade. Existing Python process PID 33387 had its working directory in the older `2026-10-06/ca` workspace and was left alone; its health/policy was not inferred.

## Implemented path

Stable formulas F1–F5 live in economics/formulas.py. CEX candidate generation reuses real book walks; DEX generation reuses integer reserve curves and requires a closed token path. Fees embedded in walks/curves are not charged twice. Unknown account fees or unverified settlement/quality prevent executable candidate selection. Closed cycles retain native reference-free accounting; open transitions require a named declared valuation.

Agent balance-sheet feasibility covers aggregate capital, native venue inventory, margin, venue budgets, latency, settlement, liquidity, quality and legal/operational flags. The F4 allocator is exact within a supplied universe of at most 20 discrete candidates, with mutually exclusive actions per episode. It is not a global continuous optimizer. A discrete capital marginal diagnostic is retained; it is not a dual price and no dual-polyhedra engine was built.

Observatory shadow pricing now excludes nonexecutable/future/stale quotes and uses conservative minimum depth across redundant sources. Public source status is aggregated across assets, with per-asset evidence retained. Spread decay is no longer labeled successful capture. Persistent hysteresis checkpoints, stable episode IDs, SQLite episode storage, frozen birth predictions, feedback updates and credential-field-rejecting AI JSONL export were added. The existing locked runner calls the persistent observation pipeline; this is an extension of that runner, not another launch entrypoint. Pipeline quote pairs remain descriptive until book/curve and cost verification supplies actual executable candidates. Existing two-venue rebalancing remains explicitly a baseline.

## Evaluation and promotion

Seven shadow ablations: spread-only, spread+cost, existing Observatory decision, survival/capture, agent inventory, competition and candidate scientific features. `build_predictions` freezes decision-time policy predictions; `shadow_replay.evaluate` evaluates chronological held-out matched episode IDs, rejecting training/prediction leakage. It reports net value, calibration/Brier, turnover, movement cost, capital-time efficiency, drawdown, failures/risk and compute time. Missing or censored outcomes remain unmeasured. Same-episode chasing versus inventory rebalancing reports net alpha, turnover, movement, capital-time, inventory utilization and risk/failure proxies. The synthetic negative example deliberately lets rebalancing lose.

Promotion refuses missing/nonfinite evidence, unmatched or insufficient episodes, nonpositive economic increment and regressions. Qualification records never authorize orders or automatically become production. Real economic qualification remains absent. Kaplan-Meier survival handles right censoring; capture starts with an explicit uncalibrated prior. Scientific feature namespaces and measurable competition proxies remain research. Nonzero competition adjustment in the economics capture model is blocked until reviewed promotion. Hodge/topology/tropical/RG/polytope/thermodynamic engines are not production dependencies.

## Actual measured evidence

Kraken recording: 122,010 messages; 3,959 eligible decisions; 124 stale decisions rejected; 0 positive F1 candidates for $1,000 input at the configured 0.0026 fee per leg. Maximum F1 was -$7.627613. This is an admission audit, not an OOS profitability result. Checksum verification is still absent and existing depth repair is retained.

## Remaining evidence/implementation gaps

The real global-state inventory hypothesis cannot be tested with the current single-venue labeled data. A multi-venue observation corpus, declared account fee schedules, read-only balance sheets, failure/capture outcomes, settlement/finality evidence and matched policy-specific shadow outcomes are needed. No real capture calibration or competition/scientific increment is established. v3/Aerodrome traversal and queue-position models are still absent. The bounded allocator does not optimize all possible global routes or continuous size. Unknown volatility, half-life and outcomes are exported as null rather than guessed. Scientific namespaces are intentional research boundaries, not completed scientific experiment implementations.

## Reproduce on this Mac

From `/Users/chris/Downloads/APEX System`:

```sh
python3 -m unittest apex_v2.test_profit_engine apex_v2.test_apex apex_v2.test_dex apex_v2.dexdata.test_dexdata
python3 -m apex_v2.evaluation.recorded_books data/kraken_20261007.log --out /path/to/audit.json
python3 -m apex_v2.evaluation.shadow_replay /path/to/episodes.jsonl --train-end-ns TRAIN_END --oos-start-ns OOS_START --out /path/to/evaluation.json
```

The public one-shot probe used the existing `global_observatory_runner.py --once` with a separate finite validation output directory. Its lock and shadow policy remain enabled. Do not start another continuous loop without first checking the existing lock and process ownership. New code is callable by existing collectors and requires no daemon.

## Secure local credential entry

No credentials are needed for the delivered validation. For future read-only account adapters, enter credentials locally using the OS keychain or the provider's secure settings UI. Reuse only read-only permissions; never paste credentials into chat, reports, source files, command arguments or episode metadata. If no secure local credential store is configured, leave the private adapter disabled. Account fee, inventory and margin measurements must not be fabricated from public quotes.

## Outputs

Episode JSON Schema, synthetic packet, seven model cards, synthetic seven-stage replay input/results, matched rebalancing negative fixture, real audit, public observation status, source hashes and launch status are included. Synthetic examples are mechanics tests and cannot qualify a model. No profitability claim or real hypothesis winner is established.
