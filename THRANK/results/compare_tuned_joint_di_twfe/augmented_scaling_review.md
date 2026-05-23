# Augmented Scaling Review

This layer fits dataset/group gains and group-level expansionary asymmetry factors on top of THRANK IRFs.
It does not change structural dynamics; it quantifies measurement/asymmetry gaps.

## Fitted Asymmetry
- PH2M: chi_expansionary=1.6994
- WH2M: chi_expansionary=1.4812

## Fitted Gains
- lp_controls / PH2M: gain=0.1380
- lp_controls / WH2M: gain=0.4271
- lp_income / PH2M: gain=0.6267
- lp_income / WH2M: gain=0.2496
- lp_wealth / PH2M: gain=-29.7802
- lp_wealth / WH2M: gain=4.8152

## MAE Improvement
- lp_controls: struct=0.0138, augmented=0.0051, improvement=0.0087
- lp_income: struct=0.0212, augmented=0.0156, improvement=0.0056
- lp_wealth: struct=0.2463, augmented=0.1020, improvement=0.1443
