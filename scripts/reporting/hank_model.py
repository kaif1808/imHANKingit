#!/usr/bin/env python3
"""End-to-end HANK-style implementation using available imHANKingit datasets.

Phases implemented from hank_instructions.md:
1) Calibration from microdata/state panel
2) Python simulation of HANK-style IRFs (3-agent reduced-form block model)
3) State-level validation via panel FE regression
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

import numpy as np
import pandas as pd
import statsmodels.api as sm

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]
RESULTS_TABLES = ROOT / "results" / "tables"
RESULTS_PLOTS = ROOT / "results" / "plots"
RESULTS_REPORTS = ROOT / "results" / "reports"


@dataclass
class Calibration:
    share_ph2m: float
    share_wh2m: float
    share_ric: float
    mpc_ph2m: float
    mpc_wh2m: float
    mpc_ric: float
    mpc_agg: float
    rho_monthly: float
    sigma_eps_monthly: float


def ensure_dirs() -> None:
    for p in [RESULTS_TABLES, RESULTS_PLOTS, RESULTS_REPORTS]:
        p.mkdir(parents=True, exist_ok=True)


def calibrate_from_data() -> Calibration:
    micro = pd.read_parquet(
        ROOT / "results" / "tables" / "individual_agent_types.parquet",
        columns=["is_PH2M", "is_WH2M", "is_Ricardian", "weight"],
    )
    w = micro["weight"].to_numpy()
    share_ph2m = float((micro["is_PH2M"].to_numpy() * w).sum() / w.sum())
    share_wh2m = float((micro["is_WH2M"].to_numpy() * w).sum() / w.sum())
    share_ric = float((micro["is_Ricardian"].to_numpy() * w).sum() / w.sum())

    # Strategy A targets from hank_instructions.md (Palomo et al. mapping).
    mpc_ph2m = 0.61
    mpc_wh2m = 0.62
    mpc_ric = 0.20
    mpc_agg = share_ph2m * mpc_ph2m + share_wh2m * mpc_wh2m + share_ric * mpc_ric

    cov = pd.read_csv(ROOT / "results" / "datasets" / "state_monthly_covariates.csv")
    income = cov[["uf_code", "date", "log_y"]].dropna().copy().sort_values(["uf_code", "date"])
    income["lag_log_y"] = income.groupby("uf_code")["log_y"].shift(1)
    income = income.dropna(subset=["lag_log_y"])

    ar = sm.OLS(income["log_y"], sm.add_constant(income["lag_log_y"])).fit()
    rho_monthly = float(ar.params["lag_log_y"])
    sigma_eps_monthly = float(np.sqrt(ar.mse_resid))

    return Calibration(
        share_ph2m=share_ph2m,
        share_wh2m=share_wh2m,
        share_ric=share_ric,
        mpc_ph2m=mpc_ph2m,
        mpc_wh2m=mpc_wh2m,
        mpc_ric=mpc_ric,
        mpc_agg=mpc_agg,
        rho_monthly=rho_monthly,
        sigma_eps_monthly=sigma_eps_monthly,
    )


def simulate_hank_irf(cal: Calibration, horizon: int = 24) -> pd.DataFrame:
    t = np.arange(horizon + 1)

    # 25bp monthly contractionary monetary shock with AR(1) persistence.
    shock0 = 0.0025
    rho_r = 0.70
    dr = shock0 * (rho_r ** t)

    # Reduced-form 3-agent HANK channels.
    eis_ric = 0.40
    okun = -0.30
    income_load_ph2m = 1.25
    income_load_wh2m = 0.80
    income_load_ric = 0.35

    dy = okun * dr
    dC_ph2m = cal.mpc_ph2m * income_load_ph2m * dy
    dC_wh2m = cal.mpc_wh2m * income_load_wh2m * dy
    dC_ric_income = cal.mpc_ric * income_load_ric * dy
    dC_ric_subst = -eis_ric * dr
    dC_ric = dC_ric_income + dC_ric_subst

    dC_agg = (
        cal.share_ph2m * dC_ph2m
        + cal.share_wh2m * dC_wh2m
        + cal.share_ric * dC_ric
    )

    out = pd.DataFrame(
        {
            "h": t,
            "dr": dr,
            "dy": dy,
            "dC_ph2m": dC_ph2m,
            "dC_wh2m": dC_wh2m,
            "dC_ric": dC_ric,
            "dC_ric_income": dC_ric_income,
            "dC_ric_substitution": dC_ric_subst,
            "dC_agg": dC_agg,
        }
    )
    out["cum_dC_agg"] = out["dC_agg"].cumsum()
    return out


def run_state_panel_validation() -> tuple[pd.DataFrame, dict[str, float]]:
    df = pd.read_csv(ROOT / "results" / "datasets" / "state_monthly_covariates.csv")
    df = df[["uf_code", "date", "consumption_index", "mp_shock", "share_PH2M"]].copy()
    df = df.sort_values(["uf_code", "date"])
    df["dlog_retail"] = df.groupby("uf_code")["consumption_index"].transform(lambda x: np.log(x).diff())
    df["shock_x_htm"] = df["mp_shock"] * df["share_PH2M"]
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["dlog_retail", "shock_x_htm"])
    lo, hi = df["dlog_retail"].quantile([0.01, 0.99])
    df["dlog_retail"] = df["dlog_retail"].clip(lo, hi)

    X = pd.concat(
        [
            df[["shock_x_htm"]],
            pd.get_dummies(df["uf_code"].astype(str), prefix="uf", drop_first=True),
            pd.get_dummies(df["date"].astype(str), prefix="t", drop_first=True),
        ],
        axis=1,
    ).astype(float)
    y = df["dlog_retail"]
    ols = sm.OLS(y, sm.add_constant(X)).fit(
        cov_type="cluster",
        cov_kwds={"groups": df["uf_code"]},
    )

    summary = {
        "coef_shock_x_htm": float(ols.params["shock_x_htm"]),
        "se_shock_x_htm": float(ols.bse["shock_x_htm"]),
        "tstat_shock_x_htm": float(ols.tvalues["shock_x_htm"]),
        "pvalue_shock_x_htm": float(ols.pvalues["shock_x_htm"]),
        "nobs": int(ols.nobs),
        "rsquared_within": float(ols.rsquared),
    }

    coef_df = pd.DataFrame([summary])
    return coef_df, summary


def save_outputs(cal: Calibration, irf: pd.DataFrame, validation_df: pd.DataFrame, validation_summary: dict[str, float]) -> None:
    cal_df = pd.DataFrame(
        [
            {
                "share_PH2M": cal.share_ph2m,
                "share_WH2M": cal.share_wh2m,
                "share_Ricardian": cal.share_ric,
                "mpc_PH2M": cal.mpc_ph2m,
                "mpc_WH2M": cal.mpc_wh2m,
                "mpc_Ricardian": cal.mpc_ric,
                "mpc_aggregate": cal.mpc_agg,
            }
        ]
    )
    income_df = pd.DataFrame(
        [
            {
                "rho_monthly": cal.rho_monthly,
                "sigma_eps_monthly": cal.sigma_eps_monthly,
                "rho_quarterly": cal.rho_monthly**3,
                "sigma_eps_quarterly_approx": cal.sigma_eps_monthly * np.sqrt(1 + cal.rho_monthly + cal.rho_monthly**2),
            }
        ]
    )

    cal_df.to_csv(RESULTS_TABLES / "hank_calibration_summary.csv", index=False)
    income_df.to_csv(RESULTS_TABLES / "hank_income_process.csv", index=False)
    irf.to_csv(RESULTS_TABLES / "hank_irf_simulation.csv", index=False)
    validation_df.to_csv(RESULTS_TABLES / "hank_state_validation.csv", index=False)

    plt.figure(figsize=(8, 5))
    plt.plot(irf["h"], 100 * irf["dC_agg"], lw=2, label="Aggregate consumption IRF")
    plt.axhline(0.0, color="black", lw=0.8)
    plt.xlabel("Months after shock")
    plt.ylabel("Percent deviation")
    plt.title("HANK IRF: Aggregate Consumption to 25bp Rate Shock")
    plt.legend()
    plt.tight_layout()
    plt.savefig(RESULTS_PLOTS / "hank_irf_consumption.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.plot(irf["h"], 100 * irf["dC_ric_substitution"], label="Ricardian substitution", lw=2)
    plt.plot(irf["h"], 100 * (irf["dC_ph2m"] * cal.share_ph2m + irf["dC_wh2m"] * cal.share_wh2m + irf["dC_ric_income"] * cal.share_ric), label="Income channel", lw=2)
    plt.plot(irf["h"], 100 * irf["dC_agg"], label="Total", lw=2, color="black")
    plt.axhline(0.0, color="black", lw=0.8)
    plt.xlabel("Months after shock")
    plt.ylabel("Percent deviation")
    plt.title("HANK IRF Decomposition")
    plt.legend()
    plt.tight_layout()
    plt.savefig(RESULTS_PLOTS / "hank_irf_decomposition.png", dpi=160)
    plt.close()

    report = {
        "phase_1_calibration": cal_df.to_dict(orient="records")[0],
        "phase_1_income_process": income_df.to_dict(orient="records")[0],
        "phase_2_irf_head": irf.head(6).to_dict(orient="records"),
        "phase_3_state_validation": validation_summary,
        "notes": [
            "Implemented as a reduced-form 3-agent HANK-style model in Python using repository data.",
            "Uses instructions' MPC targets for constrained groups and empirical HtM shares from imHANKingit outputs.",
            "State-level validation estimated with two-way fixed effects and clustered SE by state.",
        ],
    }
    (RESULTS_REPORTS / "hank_run_review.md").write_text(
        "# HANK Run Review\n\n"
        "## Summary\n"
        "Run completed for calibration, IRF simulation, and state-level validation.\n\n"
        "## Machine-readable snapshot\n"
        f"```json\n{json.dumps(report, indent=2)}\n```\n",
        encoding="utf-8",
    )


def main() -> None:
    ensure_dirs()
    cal = calibrate_from_data()
    irf = simulate_hank_irf(cal, horizon=24)
    validation_df, validation_summary = run_state_panel_validation()
    save_outputs(cal, irf, validation_df, validation_summary)

    print("HANK workflow complete.")
    print(f"Aggregate MPC: {cal.mpc_agg:.4f}")
    print(f"Income AR(1) rho_monthly: {cal.rho_monthly:.4f}, sigma_eps_monthly: {cal.sigma_eps_monthly:.4f}")
    print(f"State validation beta(shock_x_htm): {validation_summary['coef_shock_x_htm']:.4f} (p={validation_summary['pvalue_shock_x_htm']:.4f})")


if __name__ == "__main__":
    main()
