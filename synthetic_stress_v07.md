# APEX v0.7 leverage / Kelly / neural-fractal sweep

Synthetic fixture validates behavior only; no market-performance inference.

| Strategy | CAGR | Sharpe | Max DD | Ann vol | Mean exp | Max exp | Ruin days |
|---|---:|---:|---:|---:|---:|---:|---:|
| T20_base_0.5_1_1.5_fixed2.5ATR | 12.6% | 0.49 | 90.2% | 57.4% | 0.59 | 1.50 | 0 |
| T20_1_2_3x_tight_fixed2.5ATR | -8.7% | 0.49 | 99.6% | 114.8% | 1.17 | 3.00 | 0 |
| T20_1_2_3x_tight | -19.4% | 0.26 | 99.7% | 97.0% | 0.93 | 3.00 | 0 |
| T20_1_2.5_4x_tight_fixed2.5ATR | -27.4% | 0.54 | 100.0% | 150.1% | 1.49 | 4.00 | 0 |
| T20_1_2.5_4x_tight | -28.4% | 0.29 | 99.9% | 116.8% | 1.07 | 4.00 | 0 |
| T20_1_3_5x_tight_fixed2.5ATR | -50.3% | 0.56 | 100.0% | 185.7% | 1.81 | 5.00 | 0 |
| T20_1_3_5x_tight | -44.0% | 0.21 | 100.0% | 133.3% | 1.19 | 5.00 | 0 |
| T20_1_4_7x_tight_stress_fixed2.5ATR | -87.0% | 0.59 | 100.0% | 257.3% | 2.45 | 7.00 | 0 |
| T20_1_4_7x_tight_stress | -61.2% | 0.29 | 100.0% | 172.5% | 1.41 | 7.00 | 0 |
| T21_kelly_fraction_0.25_cap1 | 12.9% | 0.74 | 26.5% | 18.9% | 0.14 | 1.00 | 0 |
| T21_kelly_fraction_0.50_cap2 | 23.2% | 0.74 | 47.3% | 37.7% | 0.29 | 2.00 | 0 |
| T21_kelly_fraction_0.75_cap2.5 | 27.5% | 0.72 | 63.2% | 52.9% | 0.41 | 2.50 | 0 |
| T21_kelly_fraction_1.00_cap3 | 29.1% | 0.71 | 75.0% | 67.8% | 0.53 | 3.00 | 0 |
| T21_kelly_fraction_1.50_cap4 | 23.7% | 0.70 | 90.0% | 97.0% | 0.77 | 4.00 | 0 |
| NN_generic | -30.6% | -0.75 | 98.6% | 38.7% | 0.32 | 1.00 | 0 |
| NN_fractal | -40.2% | -1.34 | 99.7% | 34.0% | 0.29 | 1.00 | 0 |
| NN_fractal_namedFib | -19.0% | -0.21 | 91.5% | 47.1% | 0.47 | 1.00 | 0 |
| NN_fractal_placeboFib | -28.5% | -0.47 | 97.9% | 47.1% | 0.47 | 1.00 | 0 |
| T21_kelly_fraction_2.00_cap5 | 8.7% | 0.69 | 96.8% | 126.2% | 1.01 | 5.00 | 0 |
| T21_kelly_fraction_3.00_cap6 | -27.4% | 0.68 | 99.8% | 171.4% | 1.39 | 6.00 | 0 |

## Stop semantics

tightening stop is close-confirmed and changes next-bar exposure; no claimed intrabar fill

## Neural design

MLP target = positive 5-day forward return. Training is walk-forward; at day t, labels are included only through t-5. Retraining occurs every 180 bars using at most the prior 900 labeled bars. The network is a small 12→6 tanh MLP. Named-Fibonacci features are compared against a fixed placebo-anchor triple.

> These are synthetic-fixture results. They validate mechanics and falsifiers, not market profitability.