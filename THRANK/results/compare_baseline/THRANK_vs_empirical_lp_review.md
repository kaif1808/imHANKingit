# THRANK vs Empirical LP IRFs (DI shock, TWFE)

## Scope
- Empirical references: `lp_controls`, `lp_income`, `lp_wealth` directional LP tables.
- Required LP spec: `twfe_directional_dummies`, `driscoll_kraay`, `cumulative`.
- THRANK reference: cumulative monetary-shock IRFs (`irf_mp_shock_cumulative.csv`).
- Separate expansionary model shock file available: `True`
- Input fingerprints: `empirical_irf_provenance.json`
- Mapping: all datasets use PH2M->`cP`, WH2M->`cW`.
- Expansionary terms use direct THRANK `e_R_neg` simulations (no sign inversion fallback).

## Data Schema Check
- LP dataset path: `results/datasets/basic_state_month_lp/state_month_lp_dataset.csv`
- Exists: `True`
- Has `mp_shock_di`: `True`
- Has `mp_shock`: `False`
- Number of columns: `61`

## Horizon Coverage
|dataset|direction|lp_h_range|model_h_range|overlap_range|missing_lp_h_in_model|
|---|---|---|---|---|---|
|lp_controls|contractionary|0-48|0-48|0-48|none|
|lp_controls|expansionary|0-48|0-48|0-48|none|
|lp_income|contractionary|0-48|0-48|0-48|none|
|lp_income|expansionary|0-48|0-48|0-48|none|
|lp_wealth|contractionary|0-48|0-48|0-48|none|
|lp_wealth|expansionary|0-48|0-48|0-48|none|

## Calibration Snapshot Used
- THRANK `mp_shock_size`: 0.000677
- `r_R`: 0.730, `r_pi`: 0.700, `r_Y`: 0.130
- `beta_R`: 0.996, `beta_W`: 0.992, `eta`: 2.000

## Horizon Diagnostics (H0-H24)
|dataset|term|corr|sign_match_share|ci_hit_share|impact_lp_h0|impact_model_h0|h24_lp|h24_model|mean_abs_gap|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|lp_controls|PH2M contractionary|-0.426|0.520|0.000|0.0038|-0.0510|-0.0073|-0.0517|0.0506|
|lp_controls|PH2M expansionary|-0.545|0.520|0.000|-0.0002|0.0754|0.0110|0.0764|0.0777|
|lp_controls|WH2M contractionary|0.846|0.960|0.000|0.0004|-0.0432|-0.0429|-0.2159|0.1276|
|lp_controls|WH2M expansionary|0.604|0.960|0.000|0.0023|0.0637|0.0216|0.3189|0.2082|
|lp_income|PH2M contractionary|-0.151|0.840|0.000|-0.0161|-0.0510|0.0061|-0.0517|0.0431|
|lp_income|PH2M expansionary|0.279|0.560|0.000|0.0005|0.0754|-0.0039|0.0764|0.0762|
|lp_income|WH2M contractionary|-0.130|0.480|0.000|-0.0066|-0.0432|0.0054|-0.2159|0.1487|
|lp_income|WH2M expansionary|0.239|1.000|0.040|0.0413|0.0637|0.0326|0.3189|0.1853|
|lp_wealth|PH2M contractionary|-0.121|0.000|0.240|0.0483|-0.0510|0.3867|-0.0517|0.4498|
|lp_wealth|PH2M expansionary|0.181|0.040|0.120|0.0032|0.0754|-0.1187|0.0764|0.3189|
|lp_wealth|WH2M contractionary|0.256|1.000|0.960|-0.0487|-0.0432|-0.3095|-0.2159|0.1316|
|lp_wealth|WH2M expansionary|0.307|0.960|0.960|0.0197|0.0638|0.0937|0.3189|0.1049|

## Differential (PH2M - WH2M) Summary
- lp_controls (contractionary): corr=0.312, mean_abs_gap=0.0787
- lp_controls (expansionary): corr=0.220, mean_abs_gap=0.1316
- lp_income (contractionary): corr=-0.131, mean_abs_gap=0.1055
- lp_income (expansionary): corr=0.513, mean_abs_gap=0.1145
- lp_wealth (contractionary): corr=0.251, mean_abs_gap=0.5646
- lp_wealth (expansionary): corr=0.503, mean_abs_gap=0.2352

## Critical Interrogation
- Expansionary and contractionary LP terms are estimated separately; THRANK now includes a separate expansionary shock (`e_R_neg`) but asymmetry is still low-dimensional (`chi_R_neg` scalar) relative to empirical shape differences.
- Persistent low CI hit-share indicates structural mismatch in channels/persistence, not only shock scaling.
- `lp_wealth` remains hardest to match because it is a proxy outcome (`asinh(net_liquid_proxy)`), and the current observable mapping is still reduced-form rather than a full balance-sheet block.

## Recommended Upgrade Loop
1. Replace reduced-form wealth observables (`wP`, `wW`) with richer structural balance-sheet blocks linked to deposits and debt by agent type.
2. Add asymmetry in transmission if directional LP asymmetry is treated as a target moment.
3. Use weighted calibration objective by LP uncertainty (SE/CI width) and horizon bands (H0-H3, H6-H24).
