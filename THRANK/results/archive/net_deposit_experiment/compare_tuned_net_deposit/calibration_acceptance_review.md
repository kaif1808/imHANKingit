# THRANK Calibration Acceptance Review

## Thresholds
- `controls_gap_max`: `0.05`
- `income_gap_max`: `0.05`
- `wealth_gap_max`: `0.2`
- `controls_ci_hit_min`: `0.2`
- `income_ci_hit_min`: `0.3`
- `wealth_ci_hit_min`: `0.5`
- `max_h0_sign_mismatches`: `2`

## Candidate vs Baseline
|metric|baseline|candidate|delta|
|---|---:|---:|---:|
|controls_gap|0.1160|0.0291|-0.0869|
|income_gap|0.1133|0.0281|-0.0852|
|wealth_gap|0.5691|0.3604|-0.2088|
|controls_ci_hit|0.0000|0.2500|0.2500|
|income_ci_hit|0.0100|0.4500|0.4400|
|wealth_ci_hit|0.1200|0.3000|0.1800|
|h0_sign_mismatches|6.0000|6.0000|0.0000|
|overall_corr|-0.0959|-0.0684|0.0275|

## Pass/Fail
- controls_gap_pass: PASS
- income_gap_pass: PASS
- wealth_gap_pass: FAIL
- controls_ci_pass: PASS
- income_ci_pass: PASS
- wealth_ci_pass: FAIL
- h0_sign_pass: FAIL

## Summary
- Candidate passed `4/7` acceptance checks.
