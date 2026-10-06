# APEX v0.6 backtest batch

Bars: 4093 | cost: 25.0 bps/turnover | trials counted: 64

| Strategy | CAGR | Sharpe | Max DD | Turnover/yr | Mean exp | Max exp |
|---|---:|---:|---:|---:|---:|---:|
| hold | 66.4% | 1.10 | 83.8% | 0.1 | 1.00 | 1.00 |
| sma200 | 57.0% | 1.14 | 71.1% | 6.3 | 0.58 | 1.00 |
| T11_elliott_soft_wave4 | 9.4% | 0.70 | 18.5% | 4.2 | 0.07 | 1.00 |
| T12_named_fibonacci | 9.4% | 0.70 | 18.5% | 4.2 | 0.07 | 1.00 |
| T13_bill_williams | 17.5% | 0.73 | 38.6% | 24.4 | 0.12 | 1.00 |
| T14_sma200_plus_choppiness38_2 | 32.5% | 1.25 | 24.2% | 12.5 | 0.11 | 1.00 |
| T14_control_chop_30 | 7.1% | 0.52 | 18.5% | 7.7 | 0.04 | 1.00 |
| T14_control_chop_45 | 51.6% | 1.35 | 40.2% | 19.2 | 0.21 | 1.00 |
| T14_control_chop_55 | 54.8% | 1.19 | 67.3% | 23.1 | 0.42 | 1.00 |
| T20_pyramid_sma200_0_5_1_1_5x | 63.6% | 1.11 | 74.3% | 15.9 | 0.64 | 1.50 |
| T21_control_voltarget50 | 47.2% | 1.21 | 54.6% | 7.2 | 0.49 | 1.00 |
| T21_fractional_kelly_05pct | 6.9% | 1.08 | 10.7% | 1.7 | 0.05 | 1.00 |
| T21_fractional_kelly_10pct | 14.1% | 1.12 | 18.0% | 3.0 | 0.11 | 1.00 |
| T21_fractional_kelly_25pct | 33.7% | 1.16 | 36.4% | 5.4 | 0.26 | 1.00 |

## T12 Fibonacci placebo
Named-anchor Sharpe 0.70; placebo mean 0.61; z +0.38; percentile 56.0%.

