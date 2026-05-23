# THRANK (Sequence-Jacobian implementation)

This directory contains a tractable THRANK implementation (from `thrank_model.md`) using `sequence-jacobian`, plus DI-shock TWFE empirical comparison utilities.

## Clean Layout

- `thrank_calibration.py`: data moments and baseline calibration.
- `thrank_ssj_model.py`: linear THRANK system block and model builder.
- `run_thrank.py`: solve model, export IRFs/Jacobians, optional calibration overrides.
- `analyze_vs_lp.py`: compare THRANK IRFs to DI-shock TWFE LP targets (`lp_controls`, `lp_income`, `lp_wealth`).
- `tune_to_di_twfe_joint.py`: joint parameter tuning against DI-shock TWFE directional IRFs.
- `review_calibration_runs.py`: acceptance checklist (gaps, CI-hit, H0 sign mismatches) for candidate vs baseline.
- `fit_augmented_scaling.py`: diagnostics-only augmented measurement/asymmetry layer to quantify structural-vs-measurement gaps.
- `render_irfs_ggplot.R`: clear IRF/overlay figures with `ggplot2`.
- `render_augmented_overlay.R`: structural vs augmented overlay figure.
- `results/`: active outputs.
- `results/archive/`: older superseded runs/plots.
- `results/MANIFEST.md`: canonical-vs-archive output map and selection rule.
- `docs/`: compact writeups.
- `legacy/`: old plotting helpers kept only for reference.

## Empirical Targets (Authoritative)

These are the DI-shock TWFE outputs used for calibration/comparison:

- `results/tables/lp_controls/irf_consumption_directional_dummies_twfe_dk.csv`
- `results/tables/lp_income/irf_income_directional_dummies_twfe_dk.csv`
- `results/tables/lp_wealth/irf_wealth_directional_dummies_twfe_dk.csv`

The comparison script enforces:

- `spec == twfe_directional_dummies`
- `se_method == driscoll_kraay`
- `response_type == cumulative`

It also checks schema provenance in `results/datasets/basic_state_month_lp/state_month_lp_dataset.csv` (including `mp_shock_di` presence).
It supports wealth mapping modes:
- `--wealth-model-series c_based` (active default; uses `cP/cW` for all LP targets)
- `--wealth-model-series net_deposit` (experimental; uses derived `wP=dP`, `wW=dW-bW` for `lp_wealth`)

## Core Commands

From repo root:

```bash
.venv/bin/python THRANK/run_thrank.py --horizon 49
.venv/bin/python THRANK/analyze_vs_lp.py --wealth-model-series c_based
Rscript THRANK/render_irfs_ggplot.R
```

This writes baseline outputs to:

- `THRANK/results/baseline/`
- `THRANK/results/compare_baseline/`

Evaluate candidate acceptance:

```bash
.venv/bin/python THRANK/review_calibration_runs.py \
  --baseline-diagnostics THRANK/results/compare_baseline/thrank_lp_diagnostics.csv \
  --candidate-diagnostics THRANK/results/compare_tuned_joint_di_twfe/thrank_lp_diagnostics.csv \
  --output-dir THRANK/results/compare_tuned_joint_di_twfe
```

## Joint DI-TWFE Tuning

```bash
.venv/bin/python THRANK/tune_to_di_twfe_joint.py --wealth-model-series c_based
.venv/bin/python THRANK/run_thrank.py \
  --output-dir THRANK/results/tuned_joint_di_twfe \
  --calibration-overrides THRANK/results/compare_baseline/tuned_overrides_joint_di_twfe.json
.venv/bin/python THRANK/analyze_vs_lp.py \
  --thrank-dir THRANK/results/tuned_joint_di_twfe \
  --output-dir THRANK/results/compare_tuned_joint_di_twfe \
  --wealth-model-series c_based
Rscript THRANK/render_irfs_ggplot.R \
  THRANK/results/tuned_joint_di_twfe \
  THRANK/results/compare_tuned_joint_di_twfe \
  THRANK/results/compare_tuned_joint_di_twfe
```

Optional structural-vs-measurement diagnostic layer:

```bash
.venv/bin/python THRANK/fit_augmented_scaling.py \
  --thrank-dir THRANK/results/tuned_joint_di_twfe \
  --output-dir THRANK/results/compare_tuned_joint_di_twfe
Rscript THRANK/render_augmented_overlay.R THRANK/results/compare_tuned_joint_di_twfe
```

## Notes

- LP objects are cumulative IRFs; THRANK comparisons use cumulative model IRFs (`irf_mp_shock_cumulative.csv`) to avoid definition mismatch.
- Expansionary LP terms (`mp_neg_*`) are compared using direct expansionary model IRFs (`e_R_neg`) when available; sign inversion is only a fallback for legacy runs without `irf_mp_neg_shock_cumulative.csv`.
- `lp_wealth` is based on `asinh(net_liquid_proxy)`, so matching it with consumption-centered observables is intentionally treated as provisional.
- Current best structural run uses `c_based` wealth mapping; `net_deposit` mapping currently underperforms and is archived with search iterations.
- Canonical acceptance review for current best run is at `results/compare_tuned_joint_di_twfe/calibration_acceptance_review.md` (currently `6/7` checks passed with `impact_sign_epsilon=0.005`).
- `results/archive/search_iterations/` contains non-selected tuning/search runs so the active folders stay uncluttered.
- Comparison runs now emit:
  - `empirical_irf_provenance.json` (hashes/timestamps for scripts + LP tables)
  - `thrank_lp_horizon_coverage.csv` (explicit LP-vs-model horizon overlap check)
- Rendered PNGs are grouped under `results/compare_*/plots/` to keep top-level diagnostic folders tidy.
