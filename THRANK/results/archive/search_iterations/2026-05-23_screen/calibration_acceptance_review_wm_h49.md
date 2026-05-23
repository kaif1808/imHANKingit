# THRANK Calibration Acceptance Review

## Thresholds
- `controls_gap_max`: `0.05`
- `income_gap_max`: `0.05`
- `wealth_gap_max`: `0.2`
- `controls_ci_hit_min`: `0.2`
- `income_ci_hit_min`: `0.3`
- `wealth_ci_hit_min`: `0.5`
- `max_h0_sign_mismatches`: `2`
- `impact_sign_epsilon`: `0.005`

## Candidate vs Baseline
|metric|baseline|candidate|delta|
|---|---:|---:|---:|
|controls_gap|0.1160|0.0243|-0.0917|
|income_gap|0.1133|0.0235|-0.0898|
|wealth_gap|0.2513|0.1923|-0.0590|
|controls_ci_hit|0.0000|0.2800|0.2800|
|income_ci_hit|0.0100|0.5400|0.5300|
|wealth_ci_hit|0.5700|0.8100|0.2400|
|h0_sign_mismatches|1.0000|0.0000|-1.0000|
|h0_near_zero_ignored|6.0000|6.0000|0.0000|
|overall_corr|0.1113|0.2456|0.1343|

## Pass/Fail
- controls_gap_pass: PASS
- income_gap_pass: PASS
- wealth_gap_pass: PASS
- controls_ci_pass: PASS
- income_ci_pass: PASS
- wealth_ci_pass: PASS
- h0_sign_pass: PASS

## Summary
- Candidate passed `7/7` acceptance checks.
