# 2026-05-23 Candidate Screening (Horizon-Aligned H49)

Purpose:
- Re-test tuning after enforcing full LP horizon alignment (`0..48`) and refreshed DI-shock TWFE LP tables.
- Compare structural `c_based` candidate and wealth-focused variants without polluting active output folders.

## Candidates

1. `wrich_c_based_h49`
- Tuning weights emphasized wealth fit within `c_based` mapping.
- Acceptance: `6/7` (wealth gap still fails).
- Key outputs:
  - `tuned_overrides_wrich_c_based_h49.json`
  - `calibration_review_metrics_wrich_c_based_h49.csv`
  - `calibration_acceptance_review_wrich_c_based_h49.md`

2. `wm_h49` (`wealth_model_series=wealth_measurement`)
- Allows linear wealth-measurement coefficients to tune directly to wealth LP targets.
- Acceptance: `7/7` (passes wealth gap threshold).
- Caveat:
  - Best fit uses strong negative/large measurement loadings (`theta_wP_*`) that are likely overfitting reduced-form mapping rather than revealing structural balance-sheet dynamics.
- Key outputs:
  - `tuned_overrides_wm_h49.json`
  - `calibration_review_metrics_wm_h49.csv`
  - `calibration_acceptance_review_wm_h49.md`

## Selection Interpretation

- Active structural run remains `c_based` because it is more interpretable as a model comparison benchmark.
- `wm_h49` is retained as an empirical-fit upper bound and a signal that wealth-target mismatch is currently absorbed by measurement flexibility rather than structural mechanisms.
