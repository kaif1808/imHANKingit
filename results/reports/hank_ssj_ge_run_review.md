# Full SSJ GE Run Review

```json
{
  "status": "completed",
  "model": "sequence-jacobian one-asset HANK GE",
  "deliverables": [
    "hank_ssj_ge_steady_state.csv",
    "hank_ssj_ge_jacobian_col0.csv",
    "hank_ssj_ge_irf.csv"
  ],
  "data_gaps_for_full_brazil_calibration": [
    "No household consumption panel at monthly frequency (POF is repeated cross-section).",
    "No full micro-level balance-sheet maturity structure needed for URE-rich calibration.",
    "No direct mapping from Brazilian fiscal/tax incidence into model transfer rules in current repo artifacts.",
    "Model currently uses stylized macro block parameters (mu, kappa, phi, B) rather than Brazil-estimated structural moments."
  ]
}
```
