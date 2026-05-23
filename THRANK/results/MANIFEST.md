# THRANK Results Manifest

## Active (Canonical)
- `baseline/`: current baseline structural run outputs.
- `compare_baseline/`: DI-TWFE empirical comparison for baseline + provenance hashes + horizon coverage.
- `tuned_joint_di_twfe/`: current best tuned structural run (active).
- `compare_tuned_joint_di_twfe/`: canonical tuned diagnostics, acceptance review, overlays.
  - `plots/`: all rendered IRF/overlay PNGs (kept out of top-level metrics folder).

## Archived (Non-Canonical)
- `archive/sensitivity_25bp/`: shock-size sensitivity run.
- `archive/net_deposit_experiment/`: failed wealth mapping variant (`wealth_model_series=net_deposit`).
- `archive/wealth_measurement_experiment/`: failed calibrated wealth-measurement variant (`wealth_model_series=wealth_measurement`).
- `archive/search_iterations/`: superseded tuning sweeps and candidate runs.
  - `archive/search_iterations/2026-05-23_screen/`: horizon-aligned candidate screening snapshots (`c_based` wealth-push and `wealth_measurement` 7/7 fit upper bound).
- `archive/weight_sensitivity/`: alternate weighting sweeps.
- `archive/legacy_lp_controls_tuning/`: old lp-controls-only tuning artifacts.
- `archive/compare_tuned_lp_controls/`, `archive/tuned_lp_controls/`: superseded early comparison runs.
- `archive/baseline_extras/`, `archive/archive_output_with_plot/`: deprecated plotting/output bundles.

## Selection Rule
- Canonical run is chosen by highest acceptance score under `review_calibration_runs.py` and strongest wealth fit without degrading controls/income.
- Current canonical acceptance status (with `impact_sign_epsilon=0.005`): `6/7` checks passed for `compare_tuned_joint_di_twfe`.
