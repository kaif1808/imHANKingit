from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class LPSpec:
    dataset: str
    path: Path


LP_SPECS = [
    LPSpec("lp_controls", Path("results/tables/lp_controls/irf_consumption_directional_dummies_twfe_dk.csv")),
    LPSpec("lp_income", Path("results/tables/lp_income/irf_income_directional_dummies_twfe_dk.csv")),
    LPSpec("lp_wealth", Path("results/tables/lp_wealth/irf_wealth_directional_dummies_twfe_dk.csv")),
]

TERM_SPECS = [
    {"term": "mp_pos_x_ph2m", "sign": 1.0, "group": "PH2M", "direction": "contractionary"},
    {"term": "mp_neg_x_ph2m", "sign": -1.0, "group": "PH2M", "direction": "expansionary"},
    {"term": "mp_pos_x_wh2m", "sign": 1.0, "group": "WH2M", "direction": "contractionary"},
    {"term": "mp_neg_x_wh2m", "sign": -1.0, "group": "WH2M", "direction": "expansionary"},
]


def _series_for(dataset: str, group: str, wealth_model_series: str) -> str:
    if dataset == "lp_wealth" and wealth_model_series != "c_based":
        return "wP" if group == "PH2M" else "wW"
    return "cP" if group == "PH2M" else "cW"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tune THRANK to DI-shock TWFE directional LP IRFs (joint objective)."
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=49,
        help="IRF length used in model simulation. Default 49 matches empirical LP horizons 0..48.",
    )
    parser.add_argument("--fit-max-h", type=int, default=24)
    parser.add_argument("--draws", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mp-shock-size", type=float, default=0.06769240782078953 / 100.0)
    parser.add_argument("--mp-neg-shock-size", type=float, default=0.06769240782078953 / 100.0)

    # Dataset-level weights
    parser.add_argument("--weight-lp-controls", type=float, default=1.00)
    parser.add_argument("--weight-lp-income", type=float, default=1.00)
    parser.add_argument("--weight-lp-wealth", type=float, default=0.35)

    # Term-level weights for stubborn mismatch blocks
    parser.add_argument("--weight-controls-wh2m", type=float, default=2.00)
    parser.add_argument("--weight-income-wh2m", type=float, default=1.50)
    parser.add_argument("--weight-wealth-ph2m", type=float, default=1.00)

    # Horizon-band weights
    parser.add_argument("--weight-h0-h3", type=float, default=1.60)
    parser.add_argument("--weight-h4-h12", type=float, default=1.00)
    parser.add_argument("--weight-h13-h24", type=float, default=0.85)

    # Extra penalties
    parser.add_argument("--h0-sign-mismatch-penalty", type=float, default=0.015)
    parser.add_argument("--wh2m-persistence-penalty", type=float, default=0.020)
    parser.add_argument(
        "--impact-sign-epsilon",
        type=float,
        default=0.005,
        help="Do not penalize sign mismatch when |H0 empirical impact| <= epsilon.",
    )
    parser.add_argument(
        "--wealth-model-series",
        type=str,
        default="c_based",
        choices=["c_based", "net_deposit", "wealth_measurement"],
        help=(
            "Mapping for lp_wealth targets: c_based uses cP/cW, "
            "net_deposit uses derived wP/wW = dP and dW-bW; "
            "wealth_measurement uses calibrated linear measurement equations."
        ),
    )

    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("THRANK/results/compare_baseline/tuned_overrides_joint_di_twfe.json"),
    )
    parser.add_argument(
        "--output-summary",
        type=Path,
        default=Path("THRANK/results/compare_baseline/tuning_summary_joint_di_twfe.csv"),
    )
    return parser.parse_args()


def _simulate_cumulative(
    cal: dict[str, float],
    model,
    unknowns,
    targets,
    exogenous,
    outputs,
    horizon: int,
    mp_shock: float,
    mp_neg_shock: float,
    wealth_model_series: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ss = model.steady_state(cal)
    shocks_pos = {name: np.zeros(horizon, dtype=float) for name in exogenous}
    shocks_pos["e_R"][0] = mp_shock
    irf_pos = model.solve_impulse_linear(ss, unknowns, targets, shocks_pos, outputs=outputs)

    shocks_neg = {name: np.zeros(horizon, dtype=float) for name in exogenous}
    shocks_neg["e_R_neg"][0] = mp_neg_shock
    irf_neg = model.solve_impulse_linear(ss, unknowns, targets, shocks_neg, outputs=outputs)

    df_pos = pd.DataFrame({"horizon": np.arange(horizon, dtype=int)})
    df_neg = pd.DataFrame({"horizon": np.arange(horizon, dtype=int)})
    for v in outputs:
        df_pos[v] = np.cumsum(irf_pos[v])
        df_neg[v] = np.cumsum(irf_neg[v])

    # Derived wealth observables used for lp_wealth matching.
    for df in [df_pos, df_neg]:
        if {"dP", "dW", "bW", "cP", "cW", "TP"}.issubset(df.columns):
            if wealth_model_series == "net_deposit":
                df["wP"] = df["dP"]
                df["wW"] = df["dW"] - df["bW"]
            elif wealth_model_series == "wealth_measurement":
                theta_wP_c = float(cal.get("theta_wP_c", 1.0))
                theta_wP_d = float(cal.get("theta_wP_d", 0.0))
                theta_wP_tp = float(cal.get("theta_wP_tp", 0.0))
                theta_wW_c = float(cal.get("theta_wW_c", 1.0))
                theta_wW_d = float(cal.get("theta_wW_d", 0.0))
                theta_wW_b = float(cal.get("theta_wW_b", 0.0))
                df["wP"] = theta_wP_c * df["cP"] + theta_wP_d * df["dP"] + theta_wP_tp * df["TP"]
                df["wW"] = theta_wW_c * df["cW"] + theta_wW_d * df["dW"] + theta_wW_b * df["bW"]
    return df_pos, df_neg


def _term_weight(dataset: str, group: str, args: argparse.Namespace) -> float:
    if dataset == "lp_controls" and group == "WH2M":
        return float(args.weight_controls_wh2m)
    if dataset == "lp_income" and group == "WH2M":
        return float(args.weight_income_wh2m)
    if dataset == "lp_wealth" and group == "PH2M":
        return float(args.weight_wealth_ph2m)
    return 1.0


def _horizon_weight(h: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    out = np.ones_like(h, dtype=float)
    out[h <= 3] = float(args.weight_h0_h3)
    out[(h >= 4) & (h <= 12)] = float(args.weight_h4_h12)
    out[(h >= 13) & (h <= 24)] = float(args.weight_h13_h24)
    return out


def _build_targets(
    fit_max_h: int,
    dataset_weights: dict[str, float],
    args: argparse.Namespace,
) -> list[dict[str, object]]:
    targets: list[dict[str, object]] = []

    for spec in LP_SPECS:
        if not spec.path.exists():
            raise FileNotFoundError(f"Missing empirical LP file: {spec.path}")

        lp = pd.read_csv(spec.path)
        required = {
            "horizon",
            "term",
            "estimate_1sd",
            "ci_low_1sd",
            "ci_high_1sd",
            "shock_sd",
            "spec",
            "se_method",
            "response_type",
        }
        missing = required.difference(lp.columns)
        if missing:
            raise ValueError(f"{spec.dataset} missing columns: {sorted(missing)}")

        if set(lp["spec"].dropna().unique()) != {"twfe_directional_dummies"}:
            raise ValueError(f"{spec.dataset} is not TWFE directional dummies output")
        if set(lp["se_method"].dropna().unique()) != {"driscoll_kraay"}:
            raise ValueError(f"{spec.dataset} is not Driscoll-Kraay output")
        if set(lp["response_type"].dropna().unique()) != {"cumulative"}:
            raise ValueError(f"{spec.dataset} is not cumulative output")

        for t in TERM_SPECS:
            model_series = _series_for(spec.dataset, t["group"], args.wealth_model_series)
            sub = (
                lp[(lp["term"] == t["term"]) & (lp["horizon"] <= fit_max_h)]
                .copy()
                .sort_values("horizon")
            )
            if sub.empty:
                continue

            h = sub["horizon"].to_numpy(dtype=int)
            ci_half = np.maximum(
                np.abs(sub["ci_high_1sd"].to_numpy() - sub["ci_low_1sd"].to_numpy()) / 2.0,
                1e-4,
            )

            w = (
                (1.0 / ci_half)
                * dataset_weights[spec.dataset]
                * _term_weight(spec.dataset, t["group"], args)
                * _horizon_weight(h, args)
            )

            targets.append(
                {
                    "dataset": spec.dataset,
                    "dataset_weight": dataset_weights[spec.dataset],
                    "term": t["term"],
                    "series": model_series,
                    "group": t["group"],
                    "direction": t["direction"],
                    "sign": float(t["sign"]),
                    "h": h,
                    "y": sub["estimate_1sd"].to_numpy(dtype=float),
                    "sd": sub["shock_sd"].to_numpy(dtype=float),
                    "w": w,
                }
            )

    return targets


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)

    repo_root = Path(__file__).resolve().parents[1]
    base = make_default_calibration(repo_root)
    model, unknowns, targets, exogenous, outputs = build_model()

    dataset_weights = {
        "lp_controls": float(args.weight_lp_controls),
        "lp_income": float(args.weight_lp_income),
        "lp_wealth": float(args.weight_lp_wealth),
    }
    lp_targets = _build_targets(args.fit_max_h, dataset_weights, args)
    if not lp_targets:
        raise ValueError("No LP targets loaded for tuning")

    param_bounds = {
        "r_R": (0.40, 0.95),
        "r_pi": (0.20, 1.90),
        "r_Y": (0.03, 0.40),
        "rho_A": (0.60, 0.99),
        "rho_j": (0.30, 0.98),
        "rho_u": (0.10, 0.95),
        "phi": (0.01, 0.25),
        "kappa": (0.04, 0.50),
        "chi_R_neg": (0.10, 2.50),
    }
    if args.wealth_model_series == "wealth_measurement":
        param_bounds.update(
            {
                "theta_wP_c": (-2.0, 2.0),
                "theta_wP_d": (-2.0, 2.0),
                "theta_wP_tp": (-2.0, 2.0),
                "theta_wW_c": (-2.0, 2.0),
                "theta_wW_d": (-2.0, 2.0),
                "theta_wW_b": (-2.0, 2.0),
            }
        )

    def eval_loss(cal: dict[str, float]) -> tuple[float, dict[str, float]]:
        sim_pos, sim_neg = _simulate_cumulative(
            cal,
            model,
            unknowns,
            targets,
            exogenous,
            outputs,
            args.horizon,
            args.mp_shock_size,
            args.mp_neg_shock_size,
            args.wealth_model_series,
        )

        total_wse = 0.0
        total_weight = 0.0
        sign_penalty = 0.0
        details = []

        for trg in lp_targets:
            if trg["direction"] == "expansionary":
                sub = sim_neg[sim_neg["horizon"].isin(trg["h"])].sort_values("horizon")
                shock_scale = args.mp_neg_shock_size
                sign_use = 1.0
            else:
                sub = sim_pos[sim_pos["horizon"].isin(trg["h"])].sort_values("horizon")
                shock_scale = args.mp_shock_size
                sign_use = 1.0
            m = sign_use * (sub[trg["series"]].to_numpy(dtype=float) / shock_scale) * trg["sd"]
            gap = m - trg["y"]
            w = trg["w"]

            wse = float(np.sum((gap**2) * w))
            wt = float(np.sum(w))
            total_wse += wse
            total_weight += wt
            details.append((trg["dataset"], trg["term"], float(np.mean(np.abs(gap)))))

            # Penalize mismatched impact sign at H0 for each directional term.
            if (
                len(m) > 0
                and abs(float(trg["y"][0])) > float(args.impact_sign_epsilon)
                and np.sign(m[0]) != np.sign(trg["y"][0])
            ):
                sign_penalty += float(args.h0_sign_mismatch_penalty)

        weighted_mse = total_wse / max(total_weight, 1e-9)

        # Soft penalty for very persistent WH2M responses at H24.
        wh24 = float(sim_pos.loc[sim_pos["horizon"] == min(24, args.horizon - 1), "cW"].iloc[0])
        persist_penalty = float(args.wh2m_persistence_penalty) * abs(wh24 / args.mp_shock_size)

        loss = weighted_mse + sign_penalty + persist_penalty

        maes = {
            "mae_lp_controls": float(np.mean([v for ds, _, v in details if ds == "lp_controls"])),
            "mae_lp_income": float(np.mean([v for ds, _, v in details if ds == "lp_income"])),
            "mae_lp_wealth": float(np.mean([v for ds, _, v in details if ds == "lp_wealth"])),
            "mae_term_controls_wh2m": float(
                np.mean([v for ds, term, v in details if ds == "lp_controls" and "wh2m" in term])
            ),
            "mae_term_controls_ph2m": float(
                np.mean([v for ds, term, v in details if ds == "lp_controls" and "ph2m" in term])
            ),
        }

        parts = {
            "weighted_mse": float(weighted_mse),
            "h0_sign_penalty": float(sign_penalty),
            "persistence_penalty": float(persist_penalty),
            "impact_cP": float(sim_pos.loc[sim_pos["horizon"] == 0, "cP"].iloc[0] / args.mp_shock_size),
            "impact_cW": float(sim_pos.loc[sim_pos["horizon"] == 0, "cW"].iloc[0] / args.mp_shock_size),
            **maes,
        }
        return float(loss), parts

    base_loss, base_parts = eval_loss(base)
    best_cal = dict(base)
    best_loss = base_loss
    best_parts = dict(base_parts)
    trials: list[dict[str, float]] = []

    for i in range(args.draws):
        cand = dict(base)
        local = (i % 6) != 0
        for p, (lo, hi) in param_bounds.items():
            if local:
                span = (hi - lo) * 0.15
                cand[p] = float(np.clip(base[p] + rng.normal(0.0, span), lo, hi))
            else:
                cand[p] = float(rng.uniform(lo, hi))

        try:
            loss, parts = eval_loss(cand)
        except Exception:
            continue

        row = {"draw": i, "loss": float(loss), **parts}
        row.update({p: cand[p] for p in param_bounds})
        trials.append(row)

        if loss < best_loss:
            best_loss = loss
            best_cal = cand
            best_parts = parts

    improvement = (base_loss - best_loss) / base_loss if base_loss != 0 else np.nan

    overrides = {k: float(best_cal[k]) for k in param_bounds}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    weight_meta = {
        "weight_lp_controls": dataset_weights["lp_controls"],
        "weight_lp_income": dataset_weights["lp_income"],
        "weight_lp_wealth": dataset_weights["lp_wealth"],
        "weight_controls_wh2m": float(args.weight_controls_wh2m),
        "weight_income_wh2m": float(args.weight_income_wh2m),
        "weight_wealth_ph2m": float(args.weight_wealth_ph2m),
        "weight_h0_h3": float(args.weight_h0_h3),
        "weight_h4_h12": float(args.weight_h4_h12),
        "weight_h13_h24": float(args.weight_h13_h24),
        "h0_sign_mismatch_penalty": float(args.h0_sign_mismatch_penalty),
        "impact_sign_epsilon": float(args.impact_sign_epsilon),
        "wh2m_persistence_penalty": float(args.wh2m_persistence_penalty),
        "wealth_model_series": args.wealth_model_series,
    }

    summary_rows = [
        {
            "label": "baseline",
            "loss": base_loss,
            **base_parts,
            **{k: base[k] for k in param_bounds},
            **weight_meta,
        },
        {
            "label": "tuned_best",
            "loss": best_loss,
            **best_parts,
            **{k: best_cal[k] for k in param_bounds},
            **weight_meta,
        },
        {
            "label": "relative_improvement",
            "loss": improvement,
            "weighted_mse": np.nan,
            "h0_sign_penalty": np.nan,
            "persistence_penalty": np.nan,
            "impact_cP": np.nan,
            "impact_cW": np.nan,
            "mae_lp_controls": np.nan,
            "mae_lp_income": np.nan,
            "mae_lp_wealth": np.nan,
            "mae_term_controls_wh2m": np.nan,
            "mae_term_controls_ph2m": np.nan,
            **{k: np.nan for k in param_bounds},
            **weight_meta,
        },
    ]
    pd.DataFrame(summary_rows).to_csv(args.output_summary, index=False)

    if trials:
        trial_path = args.output_summary.with_name("tuning_trials_joint_di_twfe.csv")
        pd.DataFrame(trials).sort_values("loss").to_csv(trial_path, index=False)

    print("Joint DI-TWFE tuning complete.")
    print(f"Baseline loss: {base_loss:.6f}")
    print(f"Best loss: {best_loss:.6f}")
    print(f"Relative improvement: {improvement:.2%}")
    print(f"Overrides written to: {args.output_json}")


if __name__ == "__main__":
    main()
