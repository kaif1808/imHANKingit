#!/usr/bin/env python3
"""Full SSJ block/Jacobian GE solution using sequence-jacobian.

This script implements:
1) Steady-state solve for a one-asset HANK model
2) GE Jacobian solve
3) GE impulse response solve to a monetary shock

Outputs are written to results/tables and results/reports.
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


def load_income_params() -> tuple[float, float]:
    p = ROOT / "results" / "tables" / "hank_income_process.csv"
    if not p.exists():
        return 0.966, 0.50
    df = pd.read_csv(p)
    rho = float(df.loc[0, "rho_monthly"])
    sigma = float(df.loc[0, "sigma_eps_monthly"])
    # Use monthly rho from data. Raise sigma for model tractability if too small.
    return rho, max(0.20, sigma * 10.0)


def build_and_solve():
    household = hh.add_hetinputs([transfers, wages, make_grids])
    household = household.add_hetoutputs([labor_supply])

    blocks = [household, firm, monetary, fiscal, mkt_clearing, nkpc]
    blocks_ss = [household, firm, monetary, fiscal, mkt_clearing, nkpc_ss]

    hank_model = sj.create_model(blocks, name="One-Asset HANK GE")
    hank_model_ss = sj.create_model(blocks_ss, name="One-Asset HANK GE SS")

    rho_s, sigma_s = load_income_params()

    calibration = {
        "r": 0.005,
        "rstar": 0.005,
        "eis": 0.5,
        "frisch": 0.5,
        "B": 5.6,
        "mu": 1.2,
        "rho_s": rho_s,
        "sigma_s": sigma_s,
        "kappa": 0.1,
        "phi": 1.5,
        "Y": 1.0,
        "Z": 1.0,
        "pi": 0.0,
        "nS": 2,
        "amax": 150,
        "nA": 40,
    }
    unknowns_ss = {"beta": 0.986, "vphi": 0.8}
    targets_ss = {"asset_mkt": 0.0, "NE": 1.0}
    ss_cali = hank_model_ss.solve_steady_state(
        calibration, unknowns_ss, targets_ss, solver="broyden_custom"
    )
    ss = hank_model.steady_state(ss_cali)
    return hank_model, ss, rho_s, sigma_s


def run_ge(hank_model, ss):
    unknowns = ["w", "Y", "pi"]
    targets = ["asset_mkt", "goods_mkt", "nkpc_res"]
    T = 120

    J = hank_model.solve_jacobian(
        ss=ss,
        unknowns=unknowns,
        targets=targets,
        inputs=["rstar"],
        outputs=["C", "Y", "pi", "r", "w"],
        T=T,
    )

    drstar = 0.0025 * (0.7 ** np.arange(T))
    irf = hank_model.solve_impulse_linear(
        ss=ss,
        unknowns=unknowns,
        targets=targets,
        inputs={"rstar": drstar},
        outputs=["C", "Y", "pi", "r", "w"],
    )
    return J, irf


def save_outputs(ss, J, irf, rho_s, sigma_s):
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)
    RESULTS_REPORTS.mkdir(parents=True, exist_ok=True)

    irf_df = pd.DataFrame(
        {
            "t": np.arange(irf.T),
            "C": np.asarray(irf["C"]),
            "Y": np.asarray(irf["Y"]),
            "pi": np.asarray(irf["pi"]),
            "r": np.asarray(irf["r"]),
            "w": np.asarray(irf["w"]),
        }
    )
    irf_df.to_csv(RESULTS_TABLES / "hank_ssj_ge_irf.csv", index=False)

    Tj = np.asarray(J["C", "rstar"]).shape[0]
    jac_df = pd.DataFrame(
        {
            "t": np.arange(Tj),
            "dC_drstar_0": np.asarray(J["C", "rstar"])[:, 0],
            "dY_drstar_0": np.asarray(J["Y", "rstar"])[:, 0],
            "dpi_drstar_0": np.asarray(J["pi", "rstar"])[:, 0],
        }
    )
    jac_df.to_csv(RESULTS_TABLES / "hank_ssj_ge_jacobian_col0.csv", index=False)

    ss_fields = {
        "beta": float(ss["beta"]),
        "vphi": float(ss["vphi"]),
        "A": float(ss["A"]),
        "C": float(ss["C"]),
        "Y": float(ss["Y"]),
        "w": float(ss["w"]),
        "r": float(ss["r"]),
        "rho_s_used": float(rho_s),
        "sigma_s_used": float(sigma_s),
    }
    pd.DataFrame([ss_fields]).to_csv(
        RESULTS_TABLES / "hank_ssj_ge_steady_state.csv", index=False
    )

    note = {
        "status": "completed",
        "model": "sequence-jacobian one-asset HANK GE",
        "deliverables": [
            "hank_ssj_ge_steady_state.csv",
            "hank_ssj_ge_jacobian_col0.csv",
            "hank_ssj_ge_irf.csv",
        ],
        "data_gaps_for_full_brazil_calibration": [
            "No household consumption panel at monthly frequency (POF is repeated cross-section).",
            "No full micro-level balance-sheet maturity structure needed for URE-rich calibration.",
            "No direct mapping from Brazilian fiscal/tax incidence into model transfer rules in current repo artifacts.",
            "Model currently uses stylized macro block parameters (mu, kappa, phi, B) rather than Brazil-estimated structural moments.",
        ],
    }
    (RESULTS_REPORTS / "hank_ssj_ge_run_review.md").write_text(
        "# Full SSJ GE Run Review\n\n```json\n"
        + json.dumps(note, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )


def main():
    hank_model, ss, rho_s, sigma_s = build_and_solve()
    J, irf = run_ge(hank_model, ss)
    save_outputs(ss, J, irf, rho_s, sigma_s)
    print("Full SSJ GE solution completed.")
    print(f"Steady state: beta={ss['beta']:.6f}, A={ss['A']:.6f}, C={ss['C']:.6f}")
    print(f"IRF horizon: {irf.T}")


if __name__ == "__main__":
    main()
