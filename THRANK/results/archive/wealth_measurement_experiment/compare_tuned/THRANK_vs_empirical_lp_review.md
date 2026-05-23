# THRANK vs Empirical LP IRFs (DI shock, TWFE)

## Scope
- Empirical references: `lp_controls`, `lp_income`, `lp_wealth` directional LP tables.
- Required LP spec: `twfe_directional_dummies`, `driscoll_kraay`, `cumulative`.
- THRANK reference: cumulative monetary-shock IRFs (`irf_mp_shock_cumulative.csv`).
- Mapping: `lp_controls`/`lp_income` use PH2M->`cP`, WH2M->`cW`; `lp_wealth` uses PH2M->`wP`, WH2M->`wW` from calibrated linear measurement equations; expansionary terms use linear sign inversion.

## Data Schema Check
- LP dataset path: `results/datasets/basic_state_month_lp/state_month_lp_dataset.csv`
- Exists: `True`
- Has `mp_shock_di`: `True`
- Has `mp_shock`: `False`
- Number of columns: `61`

## Calibration Snapshot Used
- THRANK `mp_shock_size`: 0.000677
- `r_R`: 0.464, `r_pi`: 1.748, `r_Y`: 0.376
- `beta_R`: 0.996, `beta_W`: 0.992, `eta`: 2.000

## Horizon Diagnostics (H0-H24)
|dataset|term|corr|sign_match_share|ci_hit_share|impact_lp_h0|impact_model_h0|h24_lp|h24_model|mean_abs_gap|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|lp_controls|PH2M contractionary|-0.294|0.520|0.440|0.0038|-0.0210|-0.0073|-0.0140|0.0135|
|lp_controls|PH2M expansionary|-0.224|0.520|0.200|-0.0002|0.0310|0.0110|0.0206|0.0212|
|lp_controls|WH2M contractionary|0.841|0.960|0.120|0.0004|-0.0159|-0.0429|-0.0804|0.0333|
|lp_controls|WH2M expansionary|0.605|0.960|0.000|0.0023|0.0235|0.0216|0.1188|0.0690|
|lp_income|PH2M contractionary|0.045|0.840|0.640|-0.0161|-0.0210|0.0061|-0.0140|0.0090|
|lp_income|PH2M expansionary|-0.002|0.560|0.400|0.0005|0.0310|-0.0039|0.0206|0.0197|
|lp_income|WH2M contractionary|-0.129|0.480|0.120|-0.0066|-0.0159|0.0054|-0.0804|0.0544|
|lp_income|WH2M expansionary|0.243|1.000|0.240|0.0413|0.0235|0.0326|0.1188|0.0482|
|lp_wealth|PH2M contractionary|0.496|0.000|0.320|0.0483|-0.0361|0.3867|-0.0134|0.4134|
|lp_wealth|PH2M expansionary|0.714|0.040|0.600|0.0032|0.0534|-0.1187|0.0199|0.2651|
|lp_wealth|WH2M contractionary|0.222|1.000|0.760|-0.0487|-0.0211|-0.3095|-0.0625|0.2190|
|lp_wealth|WH2M expansionary|0.285|0.960|1.000|0.0197|0.0311|0.0937|0.0924|0.0720|

## Differential (PH2M - WH2M) Summary
- lp_controls (contractionary): corr=0.321, mean_abs_gap=0.0227
- lp_controls (expansionary): corr=0.223, mean_abs_gap=0.0486
- lp_income (contractionary): corr=-0.131, mean_abs_gap=0.0498
- lp_income (expansionary): corr=0.495, mean_abs_gap=0.0334
- lp_wealth (contractionary): corr=0.310, mean_abs_gap=0.6324
- lp_wealth (expansionary): corr=0.544, mean_abs_gap=0.3330

## Critical Interrogation
- Expansionary and contractionary LP terms are estimated separately; THRANK treats them as symmetric by construction. Any strong asymmetry in LPs is therefore a model shortcoming, not a calibration bug.
- Persistent low CI hit-share indicates structural mismatch in channels/persistence, not only shock scaling.
- `lp_wealth` remains hardest to match because it is a proxy outcome (`asinh(net_liquid_proxy)`), and the current observable mapping is still reduced-form rather than a full balance-sheet block.

## Recommended Upgrade Loop
1. Replace reduced-form wealth observables (`wP`, `wW`) with richer structural balance-sheet blocks linked to deposits and debt by agent type.
2. Add asymmetry in transmission if directional LP asymmetry is treated as a target moment.
3. Use weighted calibration objective by LP uncertainty (SE/CI width) and horizon bands (H0-H3, H6-H24).
