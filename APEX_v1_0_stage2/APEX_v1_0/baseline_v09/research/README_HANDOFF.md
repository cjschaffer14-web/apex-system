# APEX v0.9 Historical / Cross-AI Trading Research Handoff

## Purpose
This packet is a reproducible research handoff for a state-conditioned mixture of strategy experts, multi-scale Elliott/fractal geometry, neural representation tests, and Kelly allocation. It is research-only and contains no live execution authority.

## Central research question
Do reusable structural representations (multi-scale geometry, fractal roughness/persistence, analog state, market regime) add out-of-sample predictive information and improve the selection/sizing of separately testable strategy experts after realistic costs?

## Naming
Use **state-conditioned mixture of strategy experts** (short: **strategy mixture**) rather than treating a market state and a strategy as the same object. A market state is an estimate of environment; a strategy expert is a conditional action policy. The router maps states to a mixture/selection of experts.

## Frozen historical experiment
`FROZEN_SPEC_v09.json` was written before the v0.9 state/geometry result run. The spec hash is:
`e3415de69d1ba2e56f6afeb71fd61be2feb7253b061b5cc1b61a60ffbf4b4707`

Historical database SHA-256 is in `DATA_MANIFEST.json`.

## Main files
- `APEX_v09_Historical_State_Mixture_and_Representative_Learning.docx` - human analysis and projections.
- `trading_backtest_v09.py` - state classification, expert streams, strategy mixtures, geometry target tests, Matrix Kelly.
- `historical_v09_results.json` - full machine-readable results.
- `frozen_ladder_v08_25bps.csv` - frozen T20 and v0.8 results.
- `mixture_cost_sensitivity.csv` - 6/25/85 bps sensitivity.
- `state_forward_distributions.csv` - forward distributions by causal state.
- `geometry_named_vs_neighbors.csv` - direct geometric target test of exact named ratios versus adjacent ratios.
- `neural_ablation_real_25bps.csv` - generic/fractal/named-Fib/placebo-Fib walk-forward neural ablation.
- `matrix_kelly_btc_eth_25bps.csv` - regularized BTC/ETH Matrix Kelly sweep.
- `current_state_and_projections.json` - current state, empirical projection distributions, current geometric target surfaces.
- `market_2026-10-03.sqlite` - source market store included in the full packet.

## High-level result
The historical run reverses the synthetic impression: T20 bull-gated pyramids are positive in BTC and ETH at 25 bps, with the 1x->2.5x->4x ladder stronger than 1x->3x->5x and 1x->4x->7x. But drawdowns remain severe. The long-only strategy mixture is positive at 6 and 25 bps and fails at 85 bps. The naive directional inverse mixture is weaker, because trailing "bear" and "panic" labels do not imply negative next-day crypto returns. Exact Fibonacci numbers did not show a consistent local advantage over neighboring ratios, even when the broader multi-scale geometry had positive expectancy in some target configurations. The current small MLP family is not yet a robust trading model.

## Scientific status
This is not a clean untouched holdout. Earlier APEX work has already used overlapping BTC/ETH history. Treat these results as historical research evidence, not final proof. Promotion requires multiple-testing correction, protected future paper trading, and ideally new venues/assets/time periods that were not used in design.
