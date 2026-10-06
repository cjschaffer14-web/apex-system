# Financial Truth Protocol

## Three kinds of truth
1. **Mechanical truth**: the backtester behaves like the rules claim. No future bars, correct stop timing, correct fees/funding/liquidation semantics, deterministic replay and unit tests.
2. **Representative truth**: learned representations capture real, transferable structure rather than one dataset's quirks. They must survive cross-domain, cross-scale, cross-asset and surrogate controls.
3. **Financial truth**: after all research trials are counted, a strategy produces stable net-of-cost out-of-sample value with acceptable tail risk, and continues to do so in protected paper/live-forward data.

## Minimum evidence ladder
- Synthetic/unit fixtures for causal and mechanical correctness.
- Historical walk-forward on BTC and ETH.
- Era splits, especially post-2022.
- Named-feature versus placebo/surrogate controls.
- Parameter-neighbor tests rather than only selected values.
- Cross-asset and cross-venue replication.
- Realistic cost/funding/liquidation sensitivity.
- Deflated Sharpe / multiple-testing correction.
- CSCV/PBO or equivalent model-selection stability test.
- Locked future paper period with no parameter changes.
- Only then consider a separately ratified live experiment.

## Geometry-specific truth test
The geometry module is allowed to project future target surfaces from causally known pivots. It must separately demonstrate:
- calibration of target-hit probabilities;
- incremental information over generic trend/volatility features;
- superiority over randomized or neighboring ratios;
- robustness across scale definitions;
- robustness when the exact wave interpretation is uncertain;
- net-of-cost action value when converted into a trading policy.

## State-mixture truth test
A state name is descriptive, not directional. A "bear" state may have positive forward returns because of rebound asymmetry. Therefore the expert assigned to a state must be learned/tested from forward conditional distributions and then frozen for a fresh holdout. Never assign shorts simply because a state is labeled bear.
