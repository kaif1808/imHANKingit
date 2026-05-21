# Results Provenance

## Diagnostics From `htm_classification.py`

| Output | Meaning | Rerun command |
| --- | --- | --- |
| `results/diagnostics/pof_zero_income_excluded.csv` | Counts and weighted mass of POF households excluded before bin probabilities because income or ratio denominators are invalid. | `python3 scripts/reporting/htm_classification.py --no-choropleth` |
| `results/diagnostics/selic_sensitivity.csv` | POF national shares under SELIC rates `{0.065, 0.09, 0.14}`. | `python3 scripts/reporting/htm_classification.py --no-choropleth --write-selic-sensitivity` |
| `results/diagnostics/bin_strategy_comparison.csv` | Strategy A vs G bin count, unmatched share, and national share comparison when both strategies are requested. | `python3 scripts/reporting/htm_classification.py --no-choropleth --bin-strategy both --canonical-strategy A` |
| `results/diagnostics/national_htm_trend_yearly.csv` | Annual weight-weighted national HtM time series from state-month outputs. | `python3 scripts/reporting/htm_classification.py --no-choropleth` |
| `results/diagnostics/monthly_htm_coverage.csv::covid_q2q3_2020` | Flag for 202004-202007 disruption months in the existing monthly coverage diagnostic. | `python3 scripts/reporting/htm_classification.py --no-choropleth` |
