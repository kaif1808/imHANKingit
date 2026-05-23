# THRANK Active Run

- Canonical run: `results/tuned_joint_di_twfe` + `results/compare_tuned_joint_di_twfe`
- Empirical target family: DI-shock TWFE directional-dummy LP IRFs
- Horizon alignment: model and LP both `0..48` (`thrank_lp_horizon_coverage.csv` shows full overlap for all terms)
- Provenance file: `results/compare_tuned_joint_di_twfe/empirical_irf_provenance.json`
- Acceptance status: 6/7 passed (epsilon-adjusted H0 sign gate, epsilon=0.005)
- Remaining failed gate: wealth gap (current mean abs gap 0.2463 > 0.2000)

## Selected Parameters
- r_R: 0.403019
- r_pi: 1.656716
- r_Y: 0.349387
- kappa: 0.378478
- phi: 0.054569
- rho_A: 0.637170
- rho_j: 0.403524
- rho_u: 0.480717
- chi_R_neg: 0.239295

## Selection Rationale
- Best controls/income fit while preserving strong CI-hit and robust directional asymmetry handling.
- Outperformed `net_deposit` on both acceptance and fit balance.
- A horizon-aligned `wealth_measurement` candidate achieved `7/7` acceptance in screening, but relies on aggressive measurement loadings (`theta_wP_*`) and is treated as a reduced-form fit upper bound rather than the structural benchmark. See `results/archive/search_iterations/2026-05-23_screen/README.md`.
