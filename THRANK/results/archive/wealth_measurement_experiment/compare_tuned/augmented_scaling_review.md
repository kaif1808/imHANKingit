# Augmented Scaling Review

This layer fits dataset/group gains and group-level expansionary asymmetry factors on top of THRANK IRFs.
It does not change structural dynamics; it quantifies measurement/asymmetry gaps.

## Fitted Asymmetry
- PH2M: chi_expansionary=0.4072
- WH2M: chi_expansionary=0.3545

## Fitted Gains
- lp_controls / PH2M: gain=0.1227
- lp_controls / WH2M: gain=0.3929
- lp_income / PH2M: gain=0.5525
- lp_income / WH2M: gain=0.2286
- lp_wealth / PH2M: gain=-26.2419
- lp_wealth / WH2M: gain=4.4202

## MAE Improvement
- lp_controls: struct=0.0343, augmented=0.0051, improvement=0.0292
- lp_income: struct=0.0328, augmented=0.0156, improvement=0.0172
- lp_wealth: struct=0.2354, augmented=0.1013, improvement=0.1341
