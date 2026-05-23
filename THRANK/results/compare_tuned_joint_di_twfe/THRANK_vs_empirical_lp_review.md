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
- `r_R`: 0.403, `r_pi`: 1.657, `r_Y`: 0.349
- `beta_R`: 0.996, `beta_W`: 0.992, `eta`: 2.000

## Horizon Diagnostics (H0-H24)
|dataset|term|corr|sign_match_share|ci_hit_share|impact_lp_h0|impact_model_h0|h24_lp|h24_model|mean_abs_gap|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|lp_controls|PH2M contractionary|-0.247|0.520|0.560|0.0038|-0.0199|-0.0073|-0.0121|0.0122|
|lp_controls|PH2M expansionary|-0.195|0.520|0.920|-0.0002|0.0070|0.0110|0.0043|0.0066|
|lp_controls|WH2M contractionary|0.840|0.960|0.120|0.0004|-0.0164|-0.0429|-0.0736|0.0291|
|lp_controls|WH2M expansionary|0.606|0.960|1.000|0.0023|0.0058|0.0216|0.0260|0.0074|
|lp_income|PH2M contractionary|0.030|0.840|0.720|-0.0161|-0.0199|0.0061|-0.0121|0.0084|
|lp_income|PH2M expansionary|-0.051|0.560|0.880|0.0005|0.0070|-0.0039|0.0043|0.0085|
|lp_income|WH2M contractionary|-0.128|0.480|0.160|-0.0066|-0.0164|0.0054|-0.0736|0.0504|
|lp_income|WH2M expansionary|0.244|1.000|0.840|0.0413|0.0058|0.0326|0.0260|0.0173|
|lp_wealth|PH2M contractionary|0.299|0.000|0.320|0.0483|-0.0199|0.3867|-0.0121|0.4097|
|lp_wealth|PH2M expansionary|0.500|0.040|0.760|0.0032|0.0070|-0.1187|0.0043|0.2452|
|lp_wealth|WH2M contractionary|0.248|1.000|0.800|-0.0487|-0.0164|-0.3095|-0.0736|0.2132|
|lp_wealth|WH2M expansionary|0.303|0.960|1.000|0.0197|0.0058|0.0937|0.0260|0.1173|

## Differential (PH2M - WH2M) Summary
- lp_controls (contractionary): corr=0.322, mean_abs_gap=0.0200
- lp_controls (expansionary): corr=0.222, mean_abs_gap=0.0082
- lp_income (contractionary): corr=-0.132, mean_abs_gap=0.0474
- lp_income (expansionary): corr=0.493, mean_abs_gap=0.0191
- lp_wealth (contractionary): corr=0.263, mean_abs_gap=0.6230
- lp_wealth (expansionary): corr=0.512, mean_abs_gap=0.3611

## Critical Interrogation
- Expansionary and contractionary LP terms are estimated separately; THRANK now includes a separate expansionary shock (`e_R_neg`) but asymmetry is still low-dimensional (`chi_R_neg` scalar) relative to empirical shape differences.
- Persistent low CI hit-share indicates structural mismatch in channels/persistence, not only shock scaling.
- `lp_wealth` remains hardest to match because it is a proxy outcome (`asinh(net_liquid_proxy)`), and the current observable mapping is still reduced-form rather than a full balance-sheet block.

## Recommended Upgrade Loop
1. Replace reduced-form wealth observables (`wP`, `wW`) with richer structural balance-sheet blocks linked to deposits and debt by agent type.
2. Add asymmetry in transmission if directional LP asymmetry is treated as a target moment.
3. Use weighted calibration objective by LP uncertainty (SE/CI width) and horizon bands (H0-H3, H6-H24).
