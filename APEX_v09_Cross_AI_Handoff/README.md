# APEX v0.9 Cross-AI Historical Trading Research Handoff

Research-only package for the **state-conditioned mixture of strategy experts** (short: **strategy mixture**) architecture.

## Core distinction
- **Market state**: a causal estimate of environment/regime.
- **Strategy expert**: a separately testable action policy.
- **Strategy mixture/router**: selects or weights experts conditional on state and uncertainty.
- **Risk/Kelly**: sizes posterior edge downstream; it does not create alpha.

## Recombination chain
`ObservationFrame -> StructureState -> GeometryForecast + MarketStateDistribution -> StrategyIntents -> StrategyMixture -> RiskAllocation -> ExecutionOutcome -> EvidenceBundle`

## Frozen experiment
The v0.9 state/geometry specification was frozen before the corresponding historical run. See `research/FROZEN_SPEC_v09.json` and `research/CHECKSUMS.txt`.

## Start here
1. `analysis/APEX_v09_Historical_State_Mixture_and_Representative_Learning.docx`
2. `research/README_HANDOFF.md`
3. `research/WORK_SEGMENTATION_AND_RECOMBINATION.md`
4. `research/FINANCIAL_TRUTH_PROTOCOL.md`
5. `schemas/TASK_ASSIGNMENTS_TEMPLATE.json`

## Important evidence status
The BTC/ETH historical series are real market/research data, but **not a pristine untouched holdout** because earlier APEX design work already examined overlapping periods. Positive results are candidate evidence, not deployment proof. A protected future paper-trading period and full trial-ledger multiple-testing correction remain required.

The source SQLite contains public market/research series only. No live trading credentials are included.
