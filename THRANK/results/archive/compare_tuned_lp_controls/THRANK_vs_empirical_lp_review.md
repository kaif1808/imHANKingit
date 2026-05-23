# THRANK vs Empirical LP IRFs (Critical Review)

## Scope
- Empirical references: `lp_controls`, `lp_income`, `lp_wealth` directional LP tables.
- THRANK reference: cumulative monetary-shock IRFs (`irf_mp_shock_cumulative.csv`).
- Mapping used: PH2M -> `cP`, WH2M -> `cW`, both rescaled to each LP term's `shock_sd`.

## Key Comparability Caveats
- LP responses are cumulative reduced-form responses; THRANK is a linear structural model. Cumulative alignment is required and applied here.
- `lp_income` and `lp_wealth` are not strict consumption outcomes; mapping them to `cP/cW` is a channel proxy, not an identity.
- LP directional terms include shock-by-composition interactions; their `shock_sd` differs by term.

## Calibration Snapshot Used
- THRANK `mp_shock_size`: 0.000677
- `r_R`: 0.460, `r_pi`: 1.467, `r_Y`: 0.174
- `beta_R`: 0.996, `beta_W`: 0.992, `eta`: 2.000

## Horizon Diagnostics (H0-H24)
|dataset|group|corr|sign_match_share|ci_hit_share|impact_lp_h0|impact_model_h0|h24_lp|h24_model|mean_abs_gap|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|lp_controls|PH2M|-0.190|0.520|0.160|0.0039|-0.0324|-0.0029|-0.0214|0.0215|
|lp_controls|WH2M|0.891|0.960|0.000|0.0002|-0.0323|-0.0509|-0.0924|0.0415|
|lp_income|PH2M|0.067|0.840|0.600|-0.0161|-0.0316|0.0061|-0.0209|0.0135|
|lp_income|WH2M|-0.127|0.480|0.080|-0.0066|-0.0315|0.0054|-0.0903|0.0652|
|lp_wealth|PH2M|0.325|0.000|0.320|0.0483|-0.0316|0.3867|-0.0209|0.4187|
|lp_wealth|WH2M|0.234|1.000|0.800|-0.0487|-0.0315|-0.3095|-0.0903|0.1982|

## Differential (PH2M - WH2M) Summary
- lp_controls: corr=0.587, mean_abs_gap=0.0206, h24_lp=0.0479, h24_model=0.0710
- lp_income: corr=-0.129, mean_abs_gap=0.0533, h24_lp=0.0007, h24_model=0.0694
- lp_wealth: corr=0.258, mean_abs_gap=0.6168, h24_lp=0.6961, h24_model=0.0694

## Critical Interrogation
- If signs mismatch in the first 24 months and CI hit-share is low, THRANK is failing on dynamic direction, not just scale.
- If impact signs match but h24 levels diverge, the model likely needs persistence/channel retuning rather than shock-size changes.
- Large gaps in `lp_wealth` relative to `cP/cW` should be interpreted as outcome-space mismatch (wealth proxy vs consumption channels).

## Recommended Upgrade Loop
1. Fit short-run impact (H0-H3) on `lp_controls` by tuning `r_R`, `r_pi`, `kappa` and `phi`.
2. Fit medium-run persistence (H6-H24) by tuning `rho_j`, `rho_u`, `rho_A` and credit channel shares (`bW_share`, `qhW_share`).
3. Re-evaluate income/wealth fits with dedicated THRANK observables (not only `cP/cW`) before claiming success.
