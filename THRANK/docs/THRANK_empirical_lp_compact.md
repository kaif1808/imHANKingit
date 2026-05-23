# THRANK vs DI-TWFE LP IRFs: Compact Critical Review (Current Canonical)

## Empirical Target Confirmation
- Empirical IRFs come directly from the three directional-dummy TWFE scripts:
  - `scripts/reporting/celina_lp_lpirfs_direction_dummy.r`
  - `scripts/reporting/celina_lp_income_lpirfs_direction_dummy.r`
  - `scripts/reporting/celina_lp_wealth_lpirfs_direction_dummy.r`
- Comparison inputs: `results/tables/lp_controls/*twfe_dk.csv`, `results/tables/lp_income/*twfe_dk.csv`, `results/tables/lp_wealth/*twfe_dk.csv`.
- Enforced filters: `spec=twfe_directional_dummies`, `se_method=driscoll_kraay`, `response_type=cumulative`.
- Input fingerprints are written per comparison run in `empirical_irf_provenance.json`.
- Horizon coverage check (`thrank_lp_horizon_coverage.csv`) confirms full overlap `0..48` for LP and model in the current canonical run.

## Data Schema Snapshot
- `results/datasets/basic_state_month_lp/state_month_lp_dataset.csv` has 61 columns.
- Shock fields: `mp_shock_di` present, `mp_shock` absent.
- Wealth target in LP script is `asinh(net_liquid_proxy)`, with `net_liquid_proxy = deposits_pc_real - pf_credit_pc_real`.

## Canonical Structural Specification
- Uses explicit asymmetric monetary shocks in THRANK: `e_R` (contractionary) and `e_R_neg` (expansionary), with tunable `chi_R_neg`.
- Active mapping mode: `wealth_model_series=c_based` (best performing among tested structural variants).

## Calibration Progress (Canonical)
- Joint objective: `0.502825 -> 0.176991` (**64.80% improvement**).
- Key tuned parameters: `r_R=0.403`, `r_pi=1.657`, `r_Y=0.349`, `kappa=0.378`, `phi=0.055`, `chi_R_neg=0.239`.

## Baseline vs Tuned (H0-H24)
|dataset|gap baseline|gap tuned|CI-hit baseline|CI-hit tuned|corr baseline|corr tuned|
|---|---:|---:|---:|---:|---:|---:|
|lp_controls|0.1160|0.0138|0.00|0.65|0.120|0.251|
|lp_income|0.1133|0.0212|0.01|0.65|0.059|0.024|
|lp_wealth|0.2513|0.2463|0.57|0.72|0.156|0.337|

- H0 sign mismatches: raw `4/12`; tolerance-adjusted (`epsilon=0.005`) `1/12` with `6` near-zero empirical impacts ignored.

## Acceptance Gate (Canonical)
- PASS: controls gap, income gap, controls CI-hit, income CI-hit, wealth CI-hit, H0 sign gate (epsilon-adjusted)
- FAIL: wealth gap threshold (`<=0.20`)
- Net: **6/7 passed**

## Remaining Worst Mismatches
- lp_wealth | PH2M contractionary | gap=0.4097 | corr=0.299 | H0 LP=0.0483, model=-0.0199
- lp_wealth | PH2M expansionary | gap=0.2452 | corr=0.499 | H0 LP=0.0032, model=0.0070
- lp_wealth | WH2M contractionary | gap=0.2132 | corr=0.248 | H0 LP=-0.0487, model=-0.0164
- lp_wealth | WH2M expansionary | gap=0.1173 | corr=0.303 | H0 LP=0.0197, model=0.0058

## Structural Variants Tested and Rejected
- `net_deposit` mapping for wealth (`wP=dP`, `wW=dW-bW`): underperformed (4/7 checks).
- `wealth_measurement` can reach a 7/7 acceptance candidate after horizon alignment, but does so with aggressive measurement loadings (`theta_wP_*` large/negative), which looks like reduced-form overfit rather than structural identification.
- Candidate screening snapshots are archived in `THRANK/results/archive/search_iterations/2026-05-23_screen/`.

## Priority Gaps and Improvements
1. Wealth channel remains underfit: add true type-level balance-sheet state dynamics targeted to `asinh(net_liquid_proxy)` moments.
2. Directional asymmetry still imperfect in PH2M controls/wealth; add richer nonlinearity beyond scalar `chi_R_neg`.
3. Add data targets for debt-service, delinquency, and deposit-rate pass-through by type/state-month to pin wealth/credit dynamics and reduce reliance on flexible measurement mapping.

## Canonical Output Paths
- Baseline compare: `THRANK/results/compare_baseline/`
- Tuned compare (canonical): `THRANK/results/compare_tuned_joint_di_twfe/`
- Plot outputs: `THRANK/results/compare_tuned_joint_di_twfe/plots/`
- Provenance hashes: `THRANK/results/compare_tuned_joint_di_twfe/empirical_irf_provenance.json`
- Archive map: `THRANK/results/MANIFEST.md`
