# Work Segmentation and Recombination

The system should be decomposed by **epistemic function**, not by model vendor. Each AI may work on any module, but modules recombine through stable contracts.

## Segment A - Data and chronology
Input: raw time-stamped observations.
Output: `ObservationFrame` with source, as-of time, event time, revision status, tradability time, missingness, and provenance hash.
Responsibilities: prevent future leakage, survivorship bias, revision leakage, and inconsistent clocks.

## Segment B - Reusable structural operators
Input: arbitrary time series or multivariate fields.
Output: `StructureState` containing multi-scale roughness, persistence, motifs, recurrence/manifold neighbors, change points, spectral/wavelet structure, causally confirmed pivots, scale hierarchy, uncertainty.
This is the cross-domain curriculum layer. Operators should work on market, physics, biological, network and synthetic systems.

## Segment C - Geometric / Elliott-fractal projector
Input: `StructureState` plus causal pivot hierarchy.
Output: `GeometryForecast` as a probability distribution over target surfaces, invalidation surfaces, time-to-target, MFE/MAE and alternative interpretations. Do not force a single wave count.
Important: geometry can generate candidate future price levels; whether exact Fibonacci ratios are privileged is a separate empirical hypothesis.

## Segment D - Market-state estimator
Input: price structure plus optional macro/liquidity/on-chain/attention features.
Output: `MarketStateDistribution`, e.g. P(bull expansion), P(bull volatile), P(range), P(recovery), P(stress), etc. States are latent environments, not actions.

## Segment E - Strategy experts
Each expert is an independently backtestable policy with no routing authority. Examples: bull pyramid, 1x trend, range mean reversion, carry/basis, long-vol/delta hedge, defensive cash, short/inverse trend. Output: `StrategyIntent` containing desired exposure, expected edge distribution, holding horizon, invalidation rule, liquidity requirements and confidence.

## Segment F - Strategy mixture / router
Input: state distribution and expert evidence.
Output: `StrategyMixture` weights. This can begin as deterministic gating and later become a learned sparse mixture-of-experts router. The router must be evaluated separately from its experts.

## Segment G - Risk / Kelly allocator
Input: posterior expected returns and covariance, uncertainty, drawdown budget.
Output: `RiskAllocation`. Include fixed fractional, rolling continuous Kelly and regularized Matrix Kelly. Kelly is a sizing layer, never an alpha source.

## Segment H - Execution simulator
Input: intended positions.
Output: realized research return stream under venue-specific fees, spread/slippage, funding, intraday stop ordering, liquidation tiers, latency and market impact. This is where a strategy becomes mechanically representative.

## Segment I - Falsification / statistics
Input: every trial and result.
Output: `EvidenceBundle` with placebo comparisons, parameter-neighbor tests, Deflated Sharpe Ratio, CSCV/PBO, bootstrap uncertainty, regime/era splits and failure modes. Failed trials must remain in the ledger.

## Segment J - Cross-AI synthesis
Different AIs should receive the same frozen packet but distinct roles: proposer, falsifier, leakage auditor, execution auditor, statistical reviewer, structural-model reviewer, macro reviewer. No AI's prose output is itself authority. Recombination happens only through the schemas below and a signed/hashed experiment ledger.

## Recombination rule
Do not recombine raw model weights first. Recombine **artifacts and operators**:
`ObservationFrame -> StructureState -> GeometryForecast + MarketStateDistribution -> StrategyIntents -> StrategyMixture -> RiskAllocation -> ExecutionOutcome -> EvidenceBundle`.

This preserves interpretability and allows any module to be replaced without rewriting the rest of the system.
