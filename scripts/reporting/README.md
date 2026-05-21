# Reporting Scripts Order

Run scripts in this order for the current monthly LP workflow:

1. `scripts/data_prep/build_brazil_wealth_panel.py`
2. `scripts/reporting/basic_state_month_lp.py`
3. `scripts/reporting/celina_lp_lpirfs_benchmark.r`
4. `scripts/reporting/celina_lp_lpirfs_direction_dummy.r`
5. `scripts/reporting/celina_lp_income_lpirfs_benchmark.r`
6. `scripts/reporting/celina_lp_income_lpirfs_direction_dummy.r`
7. `scripts/reporting/celina_lp_wealth_lpirfs_direction_dummy.r`

Optional wrappers:

- `scripts/reporting/celina_lp.r`
- `scripts/reporting/celina_lp_income.r`

Deprecated and archived:

- `scripts/reporting/cumulative_irf_heterogeneity.py` (stub only)
- `scripts/reporting/irf_heterogeneity_final.R` (stub only)
- archived copies under `archive/legacy/reporting/`
