from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ is None or __package__ == "":
    THIS_DIR = Path(__file__).resolve().parent
    if str(THIS_DIR) not in sys.path:
        sys.path.insert(0, str(THIS_DIR))
    from thrank_calibration import make_default_calibration
    from thrank_ssj_model import build_model
else:
    from .thrank_calibration import make_default_calibration
    from .thrank_ssj_model import build_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune THRANK parameters to lp_controls directional IRFs.")
    parser.add_argument("--horizon", type=int, default=48)
    parser.add_argument("--fit-max-h", type=int, default=24)
    parser.add_argument("--draws", type=int, default=450)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mp-shock-size", type=float, default=0.06769240782078953 / 100.0)
    parser.add_argument("--output-json", type=Path, default=Path("THRANK/output_vs_lp/tuned_overrides_lp_controls.json"))
    parser.add_argument("--output-summary", type=Path, default=Path("THRANK/output_vs_lp/tuning_summary_lp_controls.csv"))
    return parser.parse_args()


def _simulate_cumulative(cal: dict[str, float], model, unknowns, targets, exogenous, outputs, horizon: int, mp_shock: float) -> pd.DataFrame:
    ss = model.steady_state(cal)
    shocks = {name: np.zeros(horizon, dtype=float) for name in exogenous}
    shocks["e_R"][0] = mp_shock
    irf = model.solve_impulse_linear(ss, unknowns, targets, shocks, outputs=outputs)
    df = pd.DataFrame({"horizon": np.arange(horizon)})
    for v in outputs:
        df[v] = irf[v]
    for v in outputs:
        df[v] = df[v].cumsum()
    return df


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)

    repo_root = Path(__file__).resolve().parents[1]
    lp_path = repo_root / "results" / "tables" / "lp_controls" / "irf_consumption_directional_dummies_twfe_dk.csv"
    lp = pd.read_csv(lp_path)

    ph = lp[(lp["term"] == "mp_pos_x_ph2m") & (lp["horizon"] <= args.fit_max_h)].sort_values("horizon")
    wh = lp[(lp["term"] == "mp_pos_x_wh2m") & (lp["horizon"] <= args.fit_max_h)].sort_values("horizon")

    h = ph["horizon"].to_numpy(dtype=int)
    ph_y = ph["estimate_1sd"].to_numpy(dtype=float)
    wh_y = wh["estimate_1sd"].to_numpy(dtype=float)
    ph_sd = float(ph["shock_sd"].mean())
    wh_sd = float(wh["shock_sd"].mean())

    base = make_default_calibration(repo_root)
    model, unknowns, targets, exogenous, outputs = build_model()

    param_bounds = {
        "r_R": (0.45, 0.93),
        "r_pi": (0.20, 1.80),
        "r_Y": (0.03, 0.35),
        "rho_A": (0.60, 0.98),
        "rho_j": (0.40, 0.96),
        "rho_u": (0.10, 0.90),
        "phi": (0.01, 0.22),
        "kappa": (0.05, 0.40),
    }

    def evaluate(cal: dict[str, float]) -> tuple[float, dict[str, float]]:
        sim = _simulate_cumulative(cal, model, unknowns, targets, exogenous, outputs, args.horizon, args.mp_shock_size)
        sub = sim[sim["horizon"].isin(h)].sort_values("horizon")
        m_ph = sub["cP"].to_numpy() / args.mp_shock_size * ph_sd
        m_wh = sub["cW"].to_numpy() / args.mp_shock_size * wh_sd

        err_ph = m_ph - ph_y
        err_wh = m_wh - wh_y
        mse = float(np.mean(err_ph**2) + np.mean(err_wh**2))
        sign_penalty = float((np.sign(m_ph[0]) != np.sign(ph_y[0])) * 0.02 + (np.sign(m_wh[0]) != np.sign(wh_y[0])) * 0.02)
        persistence_penalty = float(abs(m_wh[min(24, len(m_wh)-1)]) * 0.05)
        loss = mse + sign_penalty + persistence_penalty
        return loss, {
            "mse": mse,
            "sign_penalty": sign_penalty,
            "persistence_penalty": persistence_penalty,
            "impact_ph_model": float(m_ph[0]),
            "impact_wh_model": float(m_wh[0]),
        }

    # Baseline score
    base_loss, base_parts = evaluate(base)
    best_cal = dict(base)
    best_loss = base_loss
    best_parts = dict(base_parts)

    trials: list[dict[str, float]] = []

    for i in range(args.draws):
        cand = dict(base)
        # Mixture of global and local search
        local = (i % 5) != 0
        for p, (lo, hi) in param_bounds.items():
            if local:
                span = (hi - lo) * 0.18
                center = base[p]
                cand[p] = float(np.clip(center + rng.normal(0.0, span), lo, hi))
            else:
                cand[p] = float(rng.uniform(lo, hi))

        try:
            loss, parts = evaluate(cand)
        except Exception:
            continue

        row = {"draw": i, "loss": loss}
        row.update(parts)
        for p in param_bounds:
            row[p] = cand[p]
        trials.append(row)

        if loss < best_loss:
            best_loss = loss
            best_cal = cand
            best_parts = parts

    improvement = (base_loss - best_loss) / base_loss if base_loss != 0 else np.nan

    overrides = {k: best_cal[k] for k in param_bounds}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_rows = [
        {
            "label": "baseline",
            "loss": base_loss,
            **base_parts,
            **{k: base[k] for k in param_bounds},
        },
        {
            "label": "tuned_best",
            "loss": best_loss,
            **best_parts,
            **{k: best_cal[k] for k in param_bounds},
        },
        {
            "label": "relative_improvement",
            "loss": improvement,
            "mse": np.nan,
            "sign_penalty": np.nan,
            "persistence_penalty": np.nan,
            "impact_ph_model": np.nan,
            "impact_wh_model": np.nan,
            **{k: np.nan for k in param_bounds},
        },
    ]
    pd.DataFrame(summary_rows).to_csv(args.output_summary, index=False)

    if trials:
        trial_path = args.output_summary.with_name("tuning_trials_lp_controls.csv")
        pd.DataFrame(trials).sort_values("loss").to_csv(trial_path, index=False)

    print("Tuning complete.")
    print(f"Baseline loss: {base_loss:.6f}")
    print(f"Best loss: {best_loss:.6f}")
    print(f"Relative improvement: {improvement:.2%}")
    print(f"Overrides written to: {args.output_json}")


if __name__ == "__main__":
    main()
