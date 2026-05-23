from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds


@dataclass(frozen=True)
class ThrankDataMoments:
    lambda_R: float
    lambda_W: float
    lambda_P: float
    alpha_R: float
    alpha_W: float
    alpha_P: float
    cR_share_data: float
    cW_share_data: float
    cP_share_data: float
    transfer_share_ph2m: float
    informal_share: float
    conta_propria_share: float
    formal_share: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def _clip(value: float, low: float, high: float) -> float:
    return float(min(high, max(low, value)))


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    total_weight = float(weights.sum())
    if total_weight <= 0:
        raise ValueError("Cannot compute weighted mean with non-positive total weight.")
    return float((values * weights).sum() / total_weight)


def load_data_moments(repo_root: Path) -> ThrankDataMoments:
    pof_path = repo_root / "results" / "tables" / "pof_group_wealth_income_summary.csv"
    labor_path = repo_root / "results" / "tables" / "state_month_labour_market.parquet"
    individual_path = repo_root / "results" / "tables" / "individual_agent_types.parquet"

    if not pof_path.exists():
        raise FileNotFoundError(f"Missing required file: {pof_path}")
    if not labor_path.exists():
        raise FileNotFoundError(f"Missing required file: {labor_path}")

    pof = pd.read_csv(pof_path)
    required_pof_cols = {
        "agent_type",
        "weighted_n",
        "mean_monthly_income",
        "mean_total_labor_income",
        "mean_govt_transfers",
    }
    missing_pof = required_pof_cols.difference(pof.columns)
    if missing_pof:
        raise ValueError(f"POF table is missing required columns: {sorted(missing_pof)}")

    pof_idx = pof.set_index("agent_type")
    required_groups = {"Ricardian", "WH2M", "PH2M"}
    if not required_groups.issubset(pof_idx.index):
        raise ValueError(
            "POF table must include exactly these agent_type rows: Ricardian, WH2M, PH2M."
        )

    pop_weights = pof_idx["weighted_n"]
    population_total = float(pop_weights.sum())
    lambda_R = float(pop_weights["Ricardian"] / population_total)
    lambda_W = float(pop_weights["WH2M"] / population_total)
    lambda_P = float(pop_weights["PH2M"] / population_total)

    labor_income = pof_idx["mean_total_labor_income"]
    weighted_labor = {
        "Ricardian": lambda_R * float(labor_income["Ricardian"]),
        "WH2M": lambda_W * float(labor_income["WH2M"]),
        "PH2M": lambda_P * float(labor_income["PH2M"]),
    }
    labor_total = sum(weighted_labor.values())
    alpha_R = float(weighted_labor["Ricardian"] / labor_total)
    alpha_W = float(weighted_labor["WH2M"] / labor_total)
    alpha_P = float(weighted_labor["PH2M"] / labor_total)

    monthly_income = pof_idx["mean_monthly_income"]
    weighted_consumption = {
        "Ricardian": lambda_R * float(monthly_income["Ricardian"]),
        "WH2M": lambda_W * float(monthly_income["WH2M"]),
        "PH2M": lambda_P * float(monthly_income["PH2M"]),
    }
    consumption_total = sum(weighted_consumption.values())
    cR_share_data = float(weighted_consumption["Ricardian"] / consumption_total)
    cW_share_data = float(weighted_consumption["WH2M"] / consumption_total)
    cP_share_data = float(weighted_consumption["PH2M"] / consumption_total)

    ph2m_row = pof_idx.loc["PH2M"]
    transfer_share_ph2m = float(ph2m_row["mean_govt_transfers"] / ph2m_row["mean_monthly_income"])

    if individual_path.exists():
        # Preferred source: PH2M-conditioned worker shares from micro data.
        ph2m_tbl = ds.dataset(individual_path, format="parquet").to_table(
            columns=["agent_type", "labor_status", "weight"],
            filter=(ds.field("agent_type") == "PH2M"),
        )
        ph2m = ph2m_tbl.to_pandas()
        ph2m = ph2m.dropna(subset=["labor_status", "weight"])
        ph2m = ph2m[ph2m["weight"] > 0]
        status_w = ph2m.groupby("labor_status", observed=True)["weight"].sum()
        employed_total = float(
            status_w.get("formal", 0.0)
            + status_w.get("informal", 0.0)
            + status_w.get("self_employed", 0.0)
        )
        if employed_total <= 0:
            raise ValueError("PH2M employed mass is zero in individual_agent_types.parquet.")
        formal_share = float(status_w.get("formal", 0.0) / employed_total)
        informal_share = float(status_w.get("informal", 0.0) / employed_total)
        conta_propria_share = float(status_w.get("self_employed", 0.0) / employed_total)
    else:
        # Fallback source: aggregate labour table (less precise).
        labor = pd.read_parquet(labor_path)
        required_labor_cols = {"informal_share", "conta_propria_share", "employed_weight.x"}
        missing_labor = required_labor_cols.difference(labor.columns)
        if missing_labor:
            raise ValueError(f"Labour parquet is missing required columns: {sorted(missing_labor)}")

        valid_labor = labor.dropna(
            subset=["informal_share", "conta_propria_share", "employed_weight.x"]
        ).copy()
        valid_labor = valid_labor[valid_labor["employed_weight.x"] > 0]
        if valid_labor.empty:
            raise ValueError("No valid labour rows to compute informality moments.")

        weights = valid_labor["employed_weight.x"]
        informal_share = _weighted_mean(valid_labor["informal_share"], weights)
        conta_propria_share = _weighted_mean(valid_labor["conta_propria_share"], weights)
        formal_share = float(1.0 - informal_share - conta_propria_share)

    return ThrankDataMoments(
        lambda_R=lambda_R,
        lambda_W=lambda_W,
        lambda_P=lambda_P,
        alpha_R=alpha_R,
        alpha_W=alpha_W,
        alpha_P=alpha_P,
        cR_share_data=cR_share_data,
        cW_share_data=cW_share_data,
        cP_share_data=cP_share_data,
        transfer_share_ph2m=transfer_share_ph2m,
        informal_share=informal_share,
        conta_propria_share=conta_propria_share,
        formal_share=formal_share,
    )


def make_default_calibration(repo_root: Path) -> dict[str, float]:
    moments = load_data_moments(repo_root)

    # Monthly model: choose discount factors consistent with plausible annual real rates.
    # beta_R=0.996 implies ~4.9% annual real rate; beta_W lower for constrained borrowers.
    beta_R = 0.996
    beta_W = 0.992
    # Keep eta away from 1.0: equation (L.8) divides by (eta - 1).
    # eta very close to 1 creates near-singular amplification.
    eta = 2.0
    theta = 0.60
    m_ltv = 0.75
    phi = 0.05
    j_ss = 0.10
    X_ss = 1.10
    r_R = 0.73
    r_pi = 0.70
    r_Y = 0.13
    rho_A = 0.90
    rho_j = 0.80
    rho_u = 0.50
    rho_T = 0.95
    rho_dP = 0.80
    rho_dW = 0.85
    chi_dP_y = 0.25
    chi_dW_y = 0.20
    chi_dP_r = 0.08
    chi_dW_r = 0.15
    chi_dP_tp = 0.30
    chi_dW_tp = 0.10
    chi_R_neg = 1.0
    # Wealth-observable measurement defaults (v1): start from c-based mapping.
    theta_wP_c = 1.0
    theta_wP_d = 0.0
    theta_wP_tp = 0.0
    theta_wW_c = 1.0
    theta_wW_d = 0.0
    theta_wW_b = 0.0

    kappa = ((1.0 - theta) * (1.0 - beta_R * theta)) / theta
    beta_w = m_ltv * beta_R + (1.0 - m_ltv) * beta_W
    denom = 1.0 - beta_W - m_ltv * (beta_R - beta_W - j_ss * (1.0 - beta_R))
    if denom <= 0:
        raise ValueError(
            "Steady-state denominator is non-positive. Adjust beta_R, beta_W, m_ltv, or j_ss."
        )

    alphaW_over_X = moments.alpha_W / X_ss
    qhW_share = (j_ss / denom) * alphaW_over_X
    bW_share = (j_ss * beta_R * m_ltv / denom) * alphaW_over_X
    cW_share = (
        (1.0 - beta_W - m_ltv * (beta_R - beta_W)) / denom
    ) * alphaW_over_X
    cR_share = (
        1.0
        / X_ss
        * (
            X_ss
            + moments.alpha_R
            - 1.0
            + moments.alpha_W * j_ss * m_ltv * (1.0 - beta_R) / denom
        )
    )
    cP_share = max(1e-6, 1.0 - cR_share - cW_share)

    hW_num = moments.alpha_W * (1.0 - beta_R)
    hW_den = (
        moments.alpha_W * (1.0 - beta_R) * (1.0 + j_ss * m_ltv)
        + (X_ss + moments.alpha_R - 1.0)
        * (1.0 - beta_W - m_ltv * (beta_R - beta_W - j_ss * (1.0 - beta_R)))
    )
    hW_share = _clip(hW_num / hW_den if hW_den != 0 else 0.25, 1e-4, 1.0 - 1e-4)
    iota = float(hW_share / (1.0 - hW_share))

    omega_transfer_cP = _clip(moments.transfer_share_ph2m, 0.01, 0.80)
    omega_labor_cP = 1.0 - omega_transfer_cP

    calibration = {
        "beta_R": beta_R,
        "beta_W": beta_W,
        "eta": eta,
        "theta": theta,
        "m_ltv": m_ltv,
        "phi": phi,
        "j_ss": j_ss,
        "X_ss": X_ss,
        "r_R": r_R,
        "r_pi": r_pi,
        "r_Y": r_Y,
        "rho_A": rho_A,
        "rho_j": rho_j,
        "rho_u": rho_u,
        "rho_T": rho_T,
        "rho_dP": rho_dP,
        "rho_dW": rho_dW,
        "chi_dP_y": chi_dP_y,
        "chi_dW_y": chi_dW_y,
        "chi_dP_r": chi_dP_r,
        "chi_dW_r": chi_dW_r,
        "chi_dP_tp": chi_dP_tp,
        "chi_dW_tp": chi_dW_tp,
        "chi_R_neg": chi_R_neg,
        "theta_wP_c": theta_wP_c,
        "theta_wP_d": theta_wP_d,
        "theta_wP_tp": theta_wP_tp,
        "theta_wW_c": theta_wW_c,
        "theta_wW_d": theta_wW_d,
        "theta_wW_b": theta_wW_b,
        "kappa": float(kappa),
        "beta_w": float(beta_w),
        "R_bar": float(1.0 / beta_R),
        "iota": iota,
        "alpha_R": moments.alpha_R,
        "alpha_W": moments.alpha_W,
        "alpha_P": moments.alpha_P,
        "alphaW_over_X": alphaW_over_X,
        "cR_share": float(cR_share),
        "cW_share": float(cW_share),
        "cP_share": float(cP_share),
        "bW_share": float(bW_share),
        "qhW_share": float(qhW_share),
        "omega_transfer_cP": float(omega_transfer_cP),
        "omega_labor_cP": float(omega_labor_cP),
        "formal_income_pass_through": _clip(moments.formal_share, 0.10, 1.00),
        "lambda_R": moments.lambda_R,
        "lambda_W": moments.lambda_W,
        "lambda_P": moments.lambda_P,
        "informal_share_data": moments.informal_share,
        "conta_propria_share_data": moments.conta_propria_share,
        "formal_share_data": moments.formal_share,
        "cR_share_data": moments.cR_share_data,
        "cW_share_data": moments.cW_share_data,
        "cP_share_data": moments.cP_share_data,
        "transfer_share_ph2m_data": moments.transfer_share_ph2m,
        "cR": 0.0,
        "cW": 0.0,
        "cP": 0.0,
        "Y": 0.0,
        "X": 0.0,
        "pi": 0.0,
        "R": 0.0,
        "r": 0.0,
        "bW": 0.0,
        "hW": 0.0,
        "q": 0.0,
        "A": 0.0,
        "j": 0.0,
        "u": 0.0,
        "TP": 0.0,
        "dP": 0.0,
        "dW": 0.0,
        "e_R": 0.0,
        "e_R_neg": 0.0,
        "e_A": 0.0,
        "e_j": 0.0,
        "e_u": 0.0,
        "e_T": 0.0,
    }

    if not np.isfinite(np.array(list(calibration.values()), dtype=float)).all():
        raise ValueError("Calibration contains non-finite values.")

    return calibration
