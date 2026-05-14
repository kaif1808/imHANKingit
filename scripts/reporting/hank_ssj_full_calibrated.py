#!/usr/bin/env python3
"""Data-calibrated SSJ HANK GE solve.

Calibration targets:
- Total H2M share from results/tables/individual_agent_types.parquet
- Labor-market clearing target NE = 1
- Asset market clearing target A = B (via asset_mkt = 0)

Then computes:
- GE Jacobian wrt monetary shock rstar
- GE linear IRFs
"""

from __future__ import annotations

from pathlib import Path
import json
from dataclasses import dataclass

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


@dataclass
class Targets:
    h2m_share: float
    rho_monthly: float
    sigma_monthly: float
    sigma_quarterly: float


def load_targets() -> Targets:
    micro = pd.read_parquet(
        ROOT / "results" / "tables" / "individual_agent_types.parquet",
        columns=["is_PH2M", "is_WH2M", "weight"],
    )
    w = micro["weight"].to_numpy()
    h2m = float(
        ((micro["is_PH2M"].to_numpy() + micro["is_WH2M"].to_numpy()) * w).sum()
        / w.sum()
    )

    ip = pd.read_csv(ROOT / "results" / "tables" / "hank_income_process.csv")
    rho = float(ip.loc[0, "rho_monthly"])
    sigma = float(ip.loc[0, "sigma_eps_monthly"])
    sigma_q = float(ip.loc[0, "sigma_eps_quarterly_approx"])
    return Targets(h2m_share=h2m, rho_monthly=rho, sigma_monthly=sigma, sigma_quarterly=sigma_q)


def build_models():
    household = hh.add_hetinputs([transfers, wages, make_grids])
    household = household.add_hetoutputs([labor_supply])
    blocks = [household, firm, monetary, fiscal, mkt_clearing, nkpc]
    blocks_ss = [household, firm, monetary, fiscal, mkt_clearing, nkpc_ss]
    model = sj.create_model(blocks, name="One-Asset HANK GE Calibrated")
    model_ss = sj.create_model(blocks_ss, name="One-Asset HANK GE Calibrated SS")
    return model, model_ss


def h2m_from_ss(ss) -> float:
    ints = ss.internals["hh"]
    D = np.asarray(ints["D"])
    a = np.asarray(ints["a"])
    n = np.asarray(ints["n"])
    we = np.asarray(ints["we"])
    T = np.asarray(ints["T"])

    # H2M threshold: liquid assets below half a paycheck-like flow.
    flow_income = np.maximum(1e-10, we[:, None] * n + T[:, None])
    thr = 0.5 * flow_income
    is_h2m = (a < thr).astype(float)
    return float(np.sum(D * is_h2m))


def solve_ss_given_B(model_ss, calibration_base: dict[str, float], B: float):
    calibration = calibration_base.copy()
    calibration["B"] = float(B)
    unknowns_ss = {"beta": 0.985, "vphi": 0.8}
    targets_ss = {"asset_mkt": 0.0, "NE": 1.0}
    sol = model_ss.solve_steady_state(
        calibration, unknowns_ss, targets_ss, solver="broyden_custom"
    )
    return sol


def calibrate_B_to_h2m(model_ss, calibration_base: dict[str, float], target_h2m: float):
    # Continuation scan is robust when some B guesses fail.
    grid = np.round(np.arange(1.0, 2.01, 0.01), 4)
    rows = []
    beta_seed, vphi_seed = 0.99, 0.9
    for B in grid:
        cal = calibration_base.copy()
        cal["B"] = float(B)
        solved = False
        for b0, v0 in [
            (beta_seed, vphi_seed),
            (0.99, 1.0),
            (0.99, 0.8),
            (0.985, 0.8),
            (0.995, 0.8),
        ]:
            try:
                ss_sol = model_ss.solve_steady_state(
                    cal,
                    {"beta": float(b0), "vphi": float(v0)},
                    {"asset_mkt": 0.0, "NE": 1.0},
                    solver="broyden_custom",
                )
                h2m = h2m_from_ss(ss_sol)
                beta_seed, vphi_seed = float(ss_sol["beta"]), float(ss_sol["vphi"])
                rows.append((float(B), h2m, ss_sol))
                solved = True
                break
            except Exception:
                continue
        if not solved:
            rows.append((float(B), np.nan, None))

    valid = [(b, h, ss) for b, h, ss in rows if np.isfinite(h)]
    if not valid:
        raise RuntimeError("No feasible steady states found in calibration scan.")

    best = min(valid, key=lambda x: abs(x[1] - target_h2m))
    B_star, h2m_star, ss_star = float(best[0]), float(best[1]), best[2]
    grid_evals = [(b, (h - target_h2m) if np.isfinite(h) else np.nan) for b, h, _ in rows]
    return B_star, ss_star, h2m_star, grid_evals


def run_ge(model, ss):
    unknowns = ["w", "Y", "pi"]
    targets = ["asset_mkt", "goods_mkt", "nkpc_res"]
    T = 120
    J = model.solve_jacobian(
        ss=ss,
        unknowns=unknowns,
        targets=targets,
        inputs=["rstar"],
        outputs=["C", "Y", "pi", "r", "w"],
        T=T,
    )
    drstar = 0.0025 * (0.7 ** np.arange(T))
    irf = model.solve_impulse_linear(
        ss=ss,
        unknowns=unknowns,
        targets=targets,
        inputs={"rstar": drstar},
        outputs=["C", "Y", "pi", "r", "w"],
    )
    return J, irf


def main():
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)
    RESULTS_REPORTS.mkdir(parents=True, exist_ok=True)

    targets = load_targets()
    model, model_ss = build_models()

    # Keep macro block parameters at standard NK values; calibrate HH distribution moments to data.
    calibration_base = {
        "r": 0.005, "rstar": 0.005,
        "eis": 0.5, "frisch": 0.5,
        "mu": 1.2, "kappa": 0.1, "phi": 1.5,
        "Y": 1.0, "Z": 1.0, "pi": 0.0,
        "rho_s": targets.rho_monthly,
        "sigma_s": targets.sigma_quarterly,
        "nS": 7, "amax": 180, "nA": 100,
    }

    B_star, ss_star, h2m_star, grid_evals = calibrate_B_to_h2m(
        model_ss, calibration_base, targets.h2m_share
    )

    # Evaluate full model at calibrated steady state.
    ss_full = model.steady_state(ss_star)
    J, irf = run_ge(model, ss_full)

    # Save fit diagnostics
    fit = pd.DataFrame([{
        "target_h2m_share": targets.h2m_share,
        "model_h2m_share": h2m_star,
        "h2m_abs_error": abs(h2m_star - targets.h2m_share),
        "rho_monthly_target": targets.rho_monthly,
        "sigma_monthly_target": targets.sigma_monthly,
        "B_calibrated": B_star,
        "beta_calibrated": float(ss_full["beta"]),
        "vphi_calibrated": float(ss_full["vphi"]),
        "A_ss": float(ss_full["A"]),
        "C_ss": float(ss_full["C"]),
        "Y_ss": float(ss_full["Y"]),
    }])
    fit.to_csv(RESULTS_TABLES / "hank_ssj_full_calibration_fit.csv", index=False)

    grid_df = pd.DataFrame(grid_evals, columns=["B_guess", "h2m_gap"])
    grid_df.to_csv(RESULTS_TABLES / "hank_ssj_full_calibration_grid.csv", index=False)

    Tj = np.asarray(J["C", "rstar"]).shape[0]
    jac_df = pd.DataFrame({
        "t": np.arange(Tj),
        "dC_drstar_0": np.asarray(J["C", "rstar"])[:, 0],
        "dY_drstar_0": np.asarray(J["Y", "rstar"])[:, 0],
        "dpi_drstar_0": np.asarray(J["pi", "rstar"])[:, 0],
    })
    jac_df.to_csv(RESULTS_TABLES / "hank_ssj_full_jacobian_col0.csv", index=False)

    irf_df = pd.DataFrame({
        "t": np.arange(irf.T),
        "C": np.asarray(irf["C"]),
        "Y": np.asarray(irf["Y"]),
        "pi": np.asarray(irf["pi"]),
        "r": np.asarray(irf["r"]),
        "w": np.asarray(irf["w"]),
    })
    irf_df.to_csv(RESULTS_TABLES / "hank_ssj_full_irf.csv", index=False)

    review = {
        "status": "completed",
        "targets": {
            "h2m_share": targets.h2m_share,
            "rho_monthly": targets.rho_monthly,
            "sigma_monthly": targets.sigma_monthly,
        },
        "calibrated": {
            "B": B_star,
            "beta": float(ss_full["beta"]),
            "vphi": float(ss_full["vphi"]),
            "model_h2m_share": h2m_star,
        },
        "notes": [
            "This is a full SSJ GE solve with calibrated steady state, Jacobian, and IRFs.",
            "Within this one-asset HH block, calibration can match total H2M exposure but not PH2M vs WH2M split.",
        ],
    }
    (RESULTS_REPORTS / "hank_ssj_full_calibrated_review.md").write_text(
        "# Full Calibrated SSJ HANK Review\n\n```json\n"
        + json.dumps(review, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )

    print("Fully calibrated SSJ HANK solve complete.")
    print(f"H2M target={targets.h2m_share:.6f}, model={h2m_star:.6f}, B={B_star:.6f}")
    print(f"beta={float(ss_full['beta']):.6f}, vphi={float(ss_full['vphi']):.6f}")


if __name__ == "__main__":
    main()
