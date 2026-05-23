# THRANK vs Empirical LP IRFs (DI shock, TWFE)

## Scope
- Empirical references: `lp_controls`, `lp_income`, `lp_wealth` directional LP tables.
- Required LP spec: `twfe_directional_dummies`, `driscoll_kraay`, `cumulative`.
- THRANK reference: cumulative monetary-shock IRFs (`irf_mp_shock_cumulative.csv`).
- Mapping: PH2M -> `cP`, WH2M -> `cW`; expansionary terms use linear sign inversion.

## Data Schema Check
- LP dataset path: `results/datasets/basic_state_month_lp/state_month_lp_dataset.csv`
- Exists: `True`
- Has `mp_shock_di`: `True`
- Has `mp_shock`: `False`
- Number of columns: `61`

## Calibration Snapshot Used
- THRANK `mp_shock_size`: 0.000677
- `r_R`: 0.401, `r_pi`: 1.835, `r_Y`: 0.233
- `beta_R`: 0.996, `beta_W`: 0.992, `eta`: 2.000

## Horizon Diagnostics (H0-H24)
|dataset|term|corr|sign_match_share|ci_hit_share|impact_lp_h0|impact_model_h0|h24_lp|h24_model|mean_abs_gap|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|lp_controls|PH2M contractionary|-0.224|0.520|0.560|0.0038|-0.0192|-0.0073|-0.0109|0.0113|
|lp_controls|PH2M expansionary|-0.184|0.520|0.320|-0.0002|0.0283|0.0110|0.0161|0.0167|
|lp_controls|WH2M contractionary|0.838|0.960|0.120|0.0004|-0.0177|-0.0429|-0.0708|0.0277|
|lp_controls|WH2M expansionary|0.607|0.960|0.000|0.0023|0.0261|0.0216|0.1046|0.0607|
|lp_income|PH2M contractionary|0.016|0.840|0.720|-0.0161|-0.0192|0.0061|-0.0109|0.0082|
|lp_income|PH2M expansionary|-0.077|0.560|0.560|0.0005|0.0283|-0.0039|0.0161|0.0151|
|lp_income|WH2M contractionary|-0.128|0.480|0.200|-0.0066|-0.0177|0.0054|-0.0708|0.0490|
|lp_income|WH2M expansionary|0.244|1.000|0.320|0.0413|0.0261|0.0326|0.1046|0.0399|
|lp_wealth|PH2M contractionary|0.279|0.000|0.320|0.0483|-0.0192|0.3867|-0.0109|0.4085|
|lp_wealth|PH2M expansionary|0.468|0.040|0.640|0.0032|0.0283|-0.1187|0.0161|0.2579|
|lp_wealth|WH2M contractionary|0.245|1.000|0.800|-0.0487|-0.0177|-0.3095|-0.0708|0.2146|
|lp_wealth|WH2M expansionary|0.302|0.960|1.000|0.0197|0.0261|0.0937|0.1046|0.0658|

## Differential (PH2M - WH2M) Summary
- lp_controls (contractionary): corr=0.322, mean_abs_gap=0.0193
- lp_controls (expansionary): corr=0.221, mean_abs_gap=0.0444
- lp_income (contractionary): corr=-0.132, mean_abs_gap=0.0471
- lp_income (expansionary): corr=0.492, mean_abs_gap=0.0283
- lp_wealth (contractionary): corr=0.262, mean_abs_gap=0.6231
- lp_wealth (expansionary): corr=0.511, mean_abs_gap=0.3193

## Critical Interrogation
- Expansionary and contractionary LP terms are estimated separately; THRANK treats them as symmetric by construction. Any strong asymmetry in LPs is therefore a model shortcoming, not a calibration bug.
- Persistent low CI hit-share indicates structural mismatch in channels/persistence, not only shock scaling.
- `lp_wealth` remains hardest to match because it is a proxy outcome (`asinh(net_liquid_proxy)`), while THRANK observables are consumption-centric.

## Recommended Upgrade Loop
1. Add explicit THRANK observables for income and wealth proxy channels rather than mapping all outcomes to `cP/cW`.
2. Add asymmetry in transmission if directional LP asymmetry is treated as a target moment.
3. Use weighted calibration objective by LP uncertainty (SE/CI width) and horizon bands (H0-H3, H6-H24).
