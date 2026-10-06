# Cross-Domain Structural Curriculum

## Objective
Train the reasoning/representation layer to discover reusable dynamical operators before asking it to optimize market P&L.

## Curriculum families
- Synthetic stochastic: random walks, AR/MA, HMM, stochastic volatility, jump diffusion, fractional Brownian motion, Levy-like heavy tails, multifractal cascades.
- Deterministic/chaotic: Lorenz/Rossler systems, coupled oscillators, logistic maps, N-body trajectories.
- Physics/geophysics: turbulence, wave fields, seismic sequences, river discharge, weather/ocean oscillations.
- Biological: ECG/EEG, neural spike trains, circadian and population systems.
- Network/operations: packet traffic, queueing systems, power/load systems, congestion and cascades.
- Mathematical/generated: cellular automata, Ising/reaction-diffusion, graph dynamics and known manifolds.
- Financial: multi-asset returns, OHLCV, derivatives/funding, macro/liquidity, on-chain and attention.

## Reusable operator targets
- scale hierarchy and self-similarity;
- persistence/anti-persistence;
- recurrence / nearest historical analogs;
- attractor/manifold localization;
- motif and change-point detection;
- phase/regime state inference;
- causal pivot hierarchy;
- target/invalidation surface generation;
- uncertainty and calibration;
- transfer tests under resampling and scale changes.

## Anti-negative-transfer rule
Cross-domain training is not assumed beneficial. Every source domain must be ablated. Sampling frequency, units, evolution dynamics and noise structure must be normalized or explicitly encoded. A domain is retained only if it improves held-out tasks without degrading core financial representations.

## Training sequence
1. Operator pretraining on synthetic systems with known latent truth.
2. Self-supervised hierarchical time-series representation learning on diverse real scientific datasets.
3. Cross-domain probe tasks to test whether operators are reusable.
4. Financial adaptation with no trading objective at first: forecast returns, MFE/MAE, volatility, state transitions and target-hit probabilities.
5. Freeze representation; train small strategy heads/router.
6. Only then optimize risk allocation and execution.
