# HANK Run Review

## Summary
Run completed for calibration, IRF simulation, and state-level validation.

## Machine-readable snapshot
```json
{
  "phase_1_calibration": {
    "share_PH2M": 0.20014244602176137,
    "share_WH2M": 0.24644839327809903,
    "share_Ricardian": 0.5534091607001388,
    "mpc_PH2M": 0.61,
    "mpc_WH2M": 0.62,
    "mpc_Ricardian": 0.2,
    "mpc_aggregate": 0.38556672804572356
  },
  "phase_1_income_process": {
    "rho_monthly": 0.9644322149363704,
    "sigma_eps_monthly": 0.02905738284535281,
    "rho_quarterly": 0.8970468511690703,
    "sigma_eps_quarterly_approx": 0.04943652117565071
  },
  "phase_2_irf_head": [
    {
      "h": 0,
      "dr": 0.0025,
      "dy": -0.00075,
      "dC_ph2m": -0.000571875,
      "dC_wh2m": -0.000372,
      "dC_ric": -0.0010525,
      "dC_ric_income": -5.2499999999999995e-05,
      "dC_ric_substitution": -0.001,
      "dC_agg": -0.0007885984052550437,
      "cum_dC_agg": -0.0007885984052550437
    },
    {
      "h": 1,
      "dr": 0.0017499999999999998,
      "dy": -0.000525,
      "dC_ph2m": -0.00040031249999999995,
      "dC_wh2m": -0.0002604,
      "dC_ric": -0.00073675,
      "dC_ric_income": -3.674999999999999e-05,
      "dC_ric_substitution": -0.0007,
      "dC_agg": -0.0005520188836785306,
      "cum_dC_agg": -0.0013406172889335742
    },
    {
      "h": 2,
      "dr": 0.001225,
      "dy": -0.0003675,
      "dC_ph2m": -0.00028021875,
      "dC_wh2m": -0.00018228,
      "dC_ric": -0.000515725,
      "dC_ric_income": -2.5724999999999995e-05,
      "dC_ric_substitution": -0.00049,
      "dC_agg": -0.0003864132185749714,
      "cum_dC_agg": -0.0017270305075085457
    },
    {
      "h": 3,
      "dr": 0.0008574999999999998,
      "dy": -0.00025724999999999994,
      "dC_ph2m": -0.00019615312499999995,
      "dC_wh2m": -0.00012759599999999998,
      "dC_ric": -0.00036100749999999995,
      "dC_ric_income": -1.8007499999999993e-05,
      "dC_ric_substitution": -0.00034299999999999993,
      "dC_agg": -0.0002704892530024799,
      "cum_dC_agg": -0.0019975197605110254
    },
    {
      "h": 4,
      "dr": 0.0006002499999999999,
      "dy": -0.00018007499999999995,
      "dC_ph2m": -0.00013730718749999996,
      "dC_wh2m": -8.931719999999997e-05,
      "dC_ric": -0.00025270524999999996,
      "dC_ric_income": -1.2605249999999994e-05,
      "dC_ric_substitution": -0.00024009999999999995,
      "dC_agg": -0.00018934247710173594,
      "cum_dC_agg": -0.0021868622376127614
    },
    {
      "h": 5,
      "dr": 0.00042017499999999985,
      "dy": -0.00012605249999999996,
      "dC_ph2m": -9.611503124999997e-05,
      "dC_wh2m": -6.252203999999998e-05,
      "dC_ric": -0.00017689367499999995,
      "dC_ric_income": -8.823674999999996e-06,
      "dC_ric_substitution": -0.00016806999999999995,
      "dC_agg": -0.00013253973397121517,
      "cum_dC_agg": -0.0023194019715839765
    }
  ],
  "phase_3_state_validation": {
    "coef_shock_x_htm": 0.18786232472673317,
    "se_shock_x_htm": 0.6507937912424423,
    "tstat_shock_x_htm": 0.28866643667279274,
    "pvalue_shock_x_htm": 0.7728366494078707,
    "nobs": 1215,
    "rsquared_within": 0.1987091652846149
  },
  "notes": [
    "Implemented as a reduced-form 3-agent HANK-style model in Python using repository data.",
    "Uses instructions' MPC targets for constrained groups and empirical HtM shares from imHANKingit outputs.",
    "State-level validation estimated with two-way fixed effects and clustered SE by state."
  ]
}
```
