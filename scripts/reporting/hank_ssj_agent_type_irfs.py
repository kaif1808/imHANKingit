#!/usr/bin/env python3
"""Run SSJ monetary-shock IRFs for agent types (PH2M, WH2M, Ricardian).

Approach:
1) Load calibrated macro/HH parameters from prior full calibration.
2) Solve SSJ steady state.
3) Calibrate two liquid-asset cutoffs so model distribution matches empirical
   PH2M/WH2M/Ricardian shares from individual_agent_types.parquet.
4) Re-solve SSJ with type-output accounting and run GE linear IRFs.
"""

from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd
import sequence_jacobian as sj


ROOT = Path(__file__).resolve().parents[2]
RESULTS_TABLES = ROOT / "results" / "tables"
RESULTS_REPORTS = ROOT / "results" / "reports"

hh = sj.hetblocks.hh_labor.hh


@sj.simple
def firm(Y, w, Z, pi, mu, kappa):
    L = Y / Z
    Div = Y - w * L - mu / (mu - 1) / (2 * kappa) * (1 + pi).apply(np.log) ** 2 * Y
    return L, Div


@sj.simple
def monetary(pi, rstar, phi):
    r = (1 + rstar(-1) + phi * pi(-1)) / (1 + pi) - 1
    return r


@sj.simple
def nkpc(pi, w, Z, Y, r, mu, kappa):
    nkpc_res = (
        kappa * (w / Z - 1 / mu)
        + Y(+1) / Y * (1 + pi(+1)).apply(np.log) / (1 + r(+1))
        - (1 + pi).apply(np.log)
    )
    return nkpc_res


@sj.simple
def fiscal(r, B):
    Tax = r * B
    return Tax


@sj.simple
def mkt_clearing(A, NE, C, L, Y, B, pi, mu, kappa):
    asset_mkt = A - B
    labor_mkt = NE - L
    goods_mkt = Y - C - mu / (mu - 1) / (2 * kappa) * (1 + pi).apply(np.log) ** 2 * Y
    return asset_mkt, labor_mkt, goods_mkt


@sj.simple
def nkpc_ss(Z, mu):
    w = Z / mu
    return w


def make_grids(rho_s, sigma_s, nS, amax, nA):
    e_grid, pi_e, Pi = sj.grids.markov_rouwenhorst(rho=rho_s, sigma=sigma_s, N=nS)
    a_grid = sj.grids.agrid(amax=amax, n=nA)
    return e_grid, pi_e, Pi, a_grid


def transfers(pi_e, Div, Tax, e_grid):
    tax_rule = e_grid
    div_rule = e_grid
    div = Div / np.sum(pi_e * div_rule) * div_rule
    tax = Tax / np.sum(pi_e * tax_rule) * tax_rule
    T = div - tax
    return T


def wages(w, e_grid):
    we = w * e_grid
    return we


def labor_supply(n, e_grid):
    ne = e_grid[:, np.newaxis] * n
    return ne


def type_consumption(c, a_grid, a_ph2m_max, a_wh2m_max):
    # Fixed bucket masks on liquid-asset grid => smooth Jacobians.
    is_ph = (a_grid <= a_ph2m_max).astype(float)[np.newaxis, :]
    is_wh = ((a_grid > a_ph2m_max) & (a_grid <= a_wh2m_max)).astype(float)[np.newaxis, :]
    is_ric = (a_grid > a_wh2m_max).astype(float)[np.newaxis, :]
    c_ph2m = c * is_ph
    c_wh2m = c * is_wh
    c_ric = c * is_ric
    return c_ph2m, c_wh2m, c_ric


def build_models(include_type_outputs: bool):
    household = hh.add_hetinputs([transfers, wages, make_grids]).add_hetoutputs([labor_supply])
    if include_type_outputs:
        household = household.add_hetoutputs([type_consumption])

    blocks = [household, firm, monetary, fiscal, mkt_clearing, nkpc]
    blocks_ss = [household, firm, monetary, fiscal, mkt_clearing, nkpc_ss]
    model = sj.create_model(blocks, name="HANK GE Type IRFs")
    model_ss = sj.create_model(blocks_ss, name="HANK GE Type IRFs SS")
    return model, model_ss


def load_empirical_shares():
    df = pd.read_parquet(
        ROOT / "results" / "tables" / "individual_agent_types.parquet",
        columns=["is_PH2M", "is_WH2M", "is_Ricardian", "weight"],
    )
    w = df["weight"].to_numpy()
    s_ph = float((df["is_PH2M"].to_numpy() * w).sum() / w.sum())
    s_wh = float((df["is_WH2M"].to_numpy() * w).sum() / w.sum())
    s_ric = float((df["is_Ricardian"].to_numpy() * w).sum() / w.sum())
    return s_ph, s_wh, s_ric


def load_calibration():
    fit = pd.read_csv(RESULTS_TABLES / "hank_ssj_full_calibration_fit.csv").iloc[0]
    ip = pd.read_csv(RESULTS_TABLES / "hank_income_process.csv").iloc[0]
    return {
        "B": float(fit["B_calibrated"]),
        "beta": float(fit["beta_calibrated"]),
        "vphi": float(fit["vphi_calibrated"]),
        "rho_s": float(ip["rho_monthly"]),
        "sigma_s": float(ip["sigma_eps_quarterly_approx"]),
    }


def solve_ss(model_ss, cal):
    calibration = {
        "r": 0.005,
        "rstar": 0.005,
        "eis": 0.5,
        "frisch": 0.5,
        "mu": 1.2,
        "kappa": 0.1,
        "phi": 1.5,
        "Y": 1.0,
        "Z": 1.0,
        "pi": 0.0,
        "B": cal["B"],
        "rho_s": cal["rho_s"],
        "sigma_s": cal["sigma_s"],
        "nS": 7,
        "amax": 180,
        "nA": 100,
        "a_ph2m_max": cal.get("a_ph2m_max", 0.0),
        "a_wh2m_max": cal.get("a_wh2m_max", 1.0),
    }
    unknowns_ss = {"beta": cal["beta"], "vphi": cal["vphi"]}
    targets_ss = {"asset_mkt": 0.0, "NE": 1.0}
    return model_ss.solve_steady_state(calibration, unknowns_ss, targets_ss, solver="broyden_custom")


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    idx = np.argsort(values)
    v = values[idx]
    w = weights[idx]
    cw = np.cumsum(w) / np.sum(w)
    return float(v[np.searchsorted(cw, q, side="left")])


def compute_cutoffs(ss_base, target_ph: float, target_wh: float):
    hh_int = ss_base.internals["hh"]
    a = np.asarray(hh_int["a"]).ravel()
    D = np.asarray(hh_int["D"]).ravel()
    a1 = weighted_quantile(a, D, target_ph)
    a2 = weighted_quantile(a, D, target_ph + target_wh)
    return a1, a2


def realized_type_shares(ss):
    hh_int = ss.internals["hh"]
    a_grid = np.asarray(hh_int["a_grid"])
    D = np.asarray(hh_int["D"])
    a1 = float(ss["a_ph2m_max"])
    a2 = float(ss["a_wh2m_max"])
    ph = float(D[:, a_grid <= a1].sum())
    wh = float(D[:, (a_grid > a1) & (a_grid <= a2)].sum())
    ric = float(D[:, a_grid > a2].sum())
    return ph, wh, ric


def run_irf(model, ss):
    unknowns = ["w", "Y", "pi"]
    targets = ["asset_mkt", "goods_mkt", "nkpc_res"]
    T = 120
    drstar = 0.0025 * (0.7 ** np.arange(T))
    irf = model.solve_impulse_linear(
        ss=ss,
        unknowns=unknowns,
        targets=targets,
        inputs={"rstar": drstar},
        outputs=["C_PH2M", "C_WH2M", "C_RIC", "C", "Y", "pi", "r", "w"],
    )
    return irf


def main():
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)
    RESULTS_REPORTS.mkdir(parents=True, exist_ok=True)

    s_ph, s_wh, s_ric = load_empirical_shares()
    cal = load_calibration()

    # Step 1: base SS (without type-output thresholds) to infer liquid-asset cutoffs.
    _, model_ss_base = build_models(include_type_outputs=False)
    ss_base = solve_ss(model_ss_base, cal)
    a1, a2 = compute_cutoffs(ss_base, s_ph, s_wh)

    # Step 2: full model with type consumption outputs.
    model, model_ss = build_models(include_type_outputs=True)
    ss = solve_ss(
        model_ss,
        {
            **cal,
            "beta": float(ss_base["beta"]),
            "vphi": float(ss_base["vphi"]),
            "a_ph2m_max": float(a1),
            "a_wh2m_max": float(a2),
        },
    )
    ss_full = model.steady_state(ss)

    ph_m, wh_m, ric_m = realized_type_shares(ss_full)
    irf = run_irf(model, ss_full)

    # Save level and percent IRFs by type.
    Cph_ss, Cwh_ss, Cric_ss = float(ss_full["C_PH2M"]), float(ss_full["C_WH2M"]), float(ss_full["C_RIC"])
    df = pd.DataFrame(
        {
            "t": np.arange(irf.T),
            "C_PH2M": np.asarray(irf["C_PH2M"]),
            "C_WH2M": np.asarray(irf["C_WH2M"]),
            "C_RIC": np.asarray(irf["C_RIC"]),
            "C_total": np.asarray(irf["C"]),
            "Y": np.asarray(irf["Y"]),
            "pi": np.asarray(irf["pi"]),
            "r": np.asarray(irf["r"]),
        }
    )
    df["C_PH2M_pct"] = 100.0 * df["C_PH2M"] / Cph_ss
    df["C_WH2M_pct"] = 100.0 * df["C_WH2M"] / Cwh_ss
    df["C_RIC_pct"] = 100.0 * df["C_RIC"] / Cric_ss
    df.to_csv(RESULTS_TABLES / "hank_ssj_agent_type_irfs.csv", index=False)

    fit = pd.DataFrame(
        [
            {
                "target_share_PH2M": s_ph,
                "target_share_WH2M": s_wh,
                "target_share_Ricardian": s_ric,
                "model_share_PH2M": ph_m,
                "model_share_WH2M": wh_m,
                "model_share_Ricardian": ric_m,
                "a_ph2m_max": a1,
                "a_wh2m_max": a2,
                "C_PH2M_ss": Cph_ss,
                "C_WH2M_ss": Cwh_ss,
                "C_RIC_ss": Cric_ss,
            }
        ]
    )
    fit.to_csv(RESULTS_TABLES / "hank_ssj_agent_type_fit.csv", index=False)

    review = {
        "status": "completed",
        "outputs": [
            "hank_ssj_agent_type_irfs.csv",
            "hank_ssj_agent_type_fit.csv",
        ],
        "notes": [
            "Type IRFs are generated from the calibrated SSJ GE model.",
            "PH2M/WH2M/Ricardian partitions are mapped via liquid-asset cutoffs calibrated to empirical shares.",
        ],
    }
    (RESULTS_REPORTS / "hank_ssj_agent_type_review.md").write_text(
        "# SSJ Agent-Type IRF Review\n\n```json\n"
        + json.dumps(review, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )

    print("Agent-type SSJ IRFs completed.")
    print(
        f"Target shares PH2M={s_ph:.4f}, WH2M={s_wh:.4f}, RIC={s_ric:.4f} | "
        f"Model PH2M={ph_m:.4f}, WH2M={wh_m:.4f}, RIC={ric_m:.4f}"
    )


if __name__ == "__main__":
    main()
