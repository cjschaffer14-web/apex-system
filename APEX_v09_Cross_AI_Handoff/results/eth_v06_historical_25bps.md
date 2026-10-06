# APEX v0.6 backtest batch

Bars: 3788 | cost: 25.0 bps/turnover | trials counted: 64

| Strategy | CAGR | Sharpe | Max DD | Turnover/yr | Mean exp | Max exp |
|---|---:|---:|---:|---:|---:|---:|
| hold | 66.8% | 1.01 | 94.0% | 0.1 | 1.00 | 1.00 |
| sma200 | 90.0% | 1.26 | 81.2% | 5.7 | 0.52 | 1.00 |
| T11_elliott_soft_wave4 | -0.4% | 0.08 | 56.8% | 3.5 | 0.04 | 1.00 |
| T12_named_fibonacci | -0.4% | 0.08 | 56.8% | 3.5 | 0.04 | 1.00 |
| T13_bill_williams | 31.7% | 0.92 | 45.6% | 20.6 | 0.11 | 1.00 |
| T14_sma200_plus_choppiness38_2 | 38.7% | 1.08 | 33.1% | 11.0 | 0.09 | 1.00 |
| T14_control_chop_30 | 16.1% | 0.72 | 42.2% | 5.2 | 0.03 | 1.00 |
| T14_control_chop_45 | 60.0% | 1.23 | 51.7% | 17.7 | 0.17 | 1.00 |
| T14_control_chop_55 | 60.2% | 1.07 | 62.6% | 25.3 | 0.37 | 1.00 |
| T20_pyramid_sma200_0_5_1_1_5x | 130.5% | 1.39 | 72.5% | 12.9 | 0.58 | 1.50 |
| T21_control_voltarget50 | 60.4% | 1.37 | 44.2% | 6.5 | 0.35 | 1.00 |
| T21_fractional_kelly_05pct | 6.8% | 1.09 | 7.1% | 1.3 | 0.03 | 0.99 |
| T21_fractional_kelly_10pct | 12.7% | 1.08 | 13.7% | 2.3 | 0.07 | 1.00 |
| T21_fractional_kelly_25pct | 30.6% | 1.10 | 31.6% | 4.8 | 0.16 | 1.00 |

## T12 Fibonacci placebo
Named-anchor Sharpe 0.08; placebo mean 0.11; z -0.21; percentile 38.0%.

