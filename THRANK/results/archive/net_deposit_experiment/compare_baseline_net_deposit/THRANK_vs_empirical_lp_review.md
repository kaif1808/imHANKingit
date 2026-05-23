# THRANK vs Empirical LP IRFs (DI shock, TWFE)

## Scope
- Empirical references: `lp_controls`, `lp_income`, `lp_wealth` directional LP tables.
- Required LP spec: `twfe_directional_dummies`, `driscoll_kraay`, `cumulative`.
- THRANK reference: cumulative monetary-shock IRFs (`irf_mp_shock_cumulative.csv`).
- Mapping: `lp_controls`/`lp_income` use PH2M->`cP`, WH2M->`cW`; `lp_wealth` uses PH2M->`wP`, WH2M->`wW`; expansionary terms use linear sign inversion.

## Data Schema Check
- LP dataset path: `results/datasets/basic_state_month_lp/state_month_lp_dataset.csv`
- Exists: `True`
- Has `mp_shock_di`: `True`
- Has `mp_shock`: `False`
- Number of columns: `61`

## Calibration Snapshot Used
- THRANK `mp_shock_size`: 0.000677
- `r_R`: 0.730, `r_pi`: 0.700, `r_Y`: 0.130
- `beta_R`: 0.996, `beta_W`: 0.992, `eta`: 2.000

## Horizon Diagnostics (H0-H24)
|dataset|term|corr|sign_match_share|ci_hit_share|impact_lp_h0|impact_model_h0|h24_lp|h24_model|mean_abs_gap|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|lp_controls|PH2M contractionary|-0.427|0.520|0.000|0.0038|-0.0510|-0.0073|-0.0517|0.0506|
|lp_controls|PH2M expansionary|-0.546|0.520|0.000|-0.0002|0.0754|0.0110|0.0764|0.0777|
|lp_controls|WH2M contractionary|0.846|0.960|0.000|0.0004|-0.0432|-0.0429|-0.2158|0.1276|
|lp_controls|WH2M expansionary|0.604|0.960|0.000|0.0023|0.0637|0.0216|0.3188|0.2082|
|lp_income|PH2M contractionary|-0.151|0.840|0.000|-0.0161|-0.0510|0.0061|-0.0517|0.0431|
|lp_income|PH2M expansionary|0.279|0.560|0.000|0.0005|0.0754|-0.0039|0.0764|0.0762|
|lp_income|WH2M contractionary|-0.130|0.480|0.000|-0.0066|-0.0432|0.0054|-0.2158|0.1486|
|lp_income|WH2M expansionary|0.239|1.000|0.040|0.0413|0.0637|0.0326|0.3188|0.1853|
|lp_wealth|PH2M contractionary|-0.572|0.000|0.320|0.0483|-0.0127|0.3867|-0.0655|0.4528|
|lp_wealth|PH2M expansionary|-0.769|0.040|0.160|0.0032|0.0187|-0.1187|0.0967|0.3234|
|lp_wealth|WH2M contractionary|-0.232|0.000|0.000|-0.0487|0.0574|-0.3095|0.7115|0.7089|
|lp_wealth|WH2M expansionary|-0.291|0.040|0.000|0.0197|-0.0848|0.0937|-1.0509|0.7914|

## Differential (PH2M - WH2M) Summary
- lp_controls (contractionary): corr=0.312, mean_abs_gap=0.0787
- lp_controls (expansionary): corr=0.220, mean_abs_gap=0.1316
- lp_income (contractionary): corr=-0.131, mean_abs_gap=0.1055
- lp_income (expansionary): corr=0.513, mean_abs_gap=0.1145
- lp_wealth (contractionary): corr=-0.257, mean_abs_gap=1.1617
- lp_wealth (expansionary): corr=-0.508, mean_abs_gap=1.1148

## Critical Interrogation
- Expansionary and contractionary LP terms are estimated separately; THRANK treats them as symmetric by construction. Any strong asymmetry in LPs is therefore a model shortcoming, not a calibration bug.
- Persistent low CI hit-share indicates structural mismatch in channels/persistence, not only shock scaling.
- `lp_wealth` remains hardest to match because it is a proxy outcome (`asinh(net_liquid_proxy)`), while THRANK observables are consumption-centric.

## Recommended Upgrade Loop
1. Replace reduced-form wealth observables (`wP`, `wW`) with richer structural balance-sheet blocks linked to deposits and debt by agent type.
2. Add asymmetry in transmission if directional LP asymmetry is treated as a target moment.
3. Use weighted calibration objective by LP uncertainty (SE/CI width) and horizon bands (H0-H3, H6-H24).
