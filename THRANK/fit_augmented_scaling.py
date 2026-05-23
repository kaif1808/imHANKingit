from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


LP_FILES = {
    "lp_controls": Path("results/tables/lp_controls/irf_consumption_directional_dummies_twfe_dk.csv"),
    "lp_income": Path("results/tables/lp_income/irf_income_directional_dummies_twfe_dk.csv"),
    "lp_wealth": Path("results/tables/lp_wealth/irf_wealth_directional_dummies_twfe_dk.csv"),
}

GROUP_SERIES_STANDARD = {"PH2M": "cP", "WH2M": "cW"}
GROUP_SERIES_WEALTH = {"PH2M": "wP", "WH2M": "wW"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fit augmented scaling/asymmetry layer on top of THRANK IRFs.")
    p.add_argument("--thrank-dir", type=Path, default=Path("THRANK/results/tuned_joint_di_twfe"))
    p.add_argument("--fit-max-h", type=int, default=24)
    p.add_argument("--max-iter", type=int, default=100)
    p.add_argument("--tol", type=float, default=1e-10)
    p.add_argument("--output-dir", type=Path, default=Path("THRANK/results/compare_tuned_joint_di_twfe"))
    p.add_argument(
        "--wealth-model-series",
        type=str,
        default="c_based",
        choices=["c_based", "net_deposit", "wealth_measurement"],
        help=(
            "Mapping for lp_wealth targets used in structural baseline within this diagnostic layer."
        ),
    )
    return p.parse_args()


def _build_panel(
    thrank_dir: Path,
    fit_max_h: int,
    wealth_model_series: str,
) -> tuple[pd.DataFrame, float]:
    run = json.loads((thrank_dir / "run_summary.json").read_text(encoding="utf-8"))
    calibration = json.loads((thrank_dir / "calibration.json").read_text(encoding="utf-8"))
    mp_pos = float(run["mp_shock_size"])
    mp_neg = float(run.get("mp_neg_shock_size", mp_pos))

    pos_path = thrank_dir / "irf_mp_pos_shock_cumulative.csv"
    neg_path = thrank_dir / "irf_mp_neg_shock_cumulative.csv"
    legacy_path = thrank_dir / "irf_mp_shock_cumulative.csv"
    if pos_path.exists():
        irf_pos = pd.read_csv(pos_path)
    elif legacy_path.exists():
        irf_pos = pd.read_csv(legacy_path)
    else:
        raise FileNotFoundError("Missing THRANK pos cumulative IRF file.")
    if neg_path.exists():
        irf_neg = pd.read_csv(neg_path)
        neg_available = True
    else:
        irf_neg = irf_pos.copy()
        neg_available = False

    def _add_w(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if {"dP", "dW", "bW", "cP", "cW", "TP"}.issubset(out.columns):
            if wealth_model_series == "net_deposit":
                out["wP"] = out["dP"]
                out["wW"] = out["dW"] - out["bW"]
            elif wealth_model_series == "wealth_measurement":
                theta_wP_c = float(calibration.get("theta_wP_c", 1.0))
                theta_wP_d = float(calibration.get("theta_wP_d", 0.0))
                theta_wP_tp = float(calibration.get("theta_wP_tp", 0.0))
                theta_wW_c = float(calibration.get("theta_wW_c", 1.0))
                theta_wW_d = float(calibration.get("theta_wW_d", 0.0))
                theta_wW_b = float(calibration.get("theta_wW_b", 0.0))
                out["wP"] = theta_wP_c * out["cP"] + theta_wP_d * out["dP"] + theta_wP_tp * out["TP"]
                out["wW"] = theta_wW_c * out["cW"] + theta_wW_d * out["dW"] + theta_wW_b * out["bW"]
        return out

    irf_pos = _add_w(irf_pos)
    irf_neg = _add_w(irf_neg)

    rows = []
    for ds, lp_path in LP_FILES.items():
        lp = pd.read_csv(lp_path)
        lp = lp[lp["horizon"] <= fit_max_h].copy()

        if ds == "lp_wealth" and wealth_model_series == "net_deposit":
            series_map = GROUP_SERIES_WEALTH
        else:
            series_map = GROUP_SERIES_STANDARD
        for group, s in series_map.items():
            term_pos = "mp_pos_x_ph2m" if group == "PH2M" else "mp_pos_x_wh2m"
            term_neg = "mp_neg_x_ph2m" if group == "PH2M" else "mp_neg_x_wh2m"

            lpp = lp[lp["term"] == term_pos][["horizon", "estimate_1sd", "shock_sd"]].copy()
            lpn = lp[lp["term"] == term_neg][["horizon", "estimate_1sd", "shock_sd"]].copy()
            lpp = lpp.rename(columns={"estimate_1sd": "y_pos", "shock_sd": "sd_pos"})
            lpn = lpn.rename(columns={"estimate_1sd": "y_neg", "shock_sd": "sd_neg"})

            m = lpp.merge(lpn, on="horizon", how="inner")
            m = m.merge(
                irf_pos[["t", s]].rename(columns={"t": "horizon", s: "m_pos"}),
                on="horizon",
                how="inner",
            )
            m = m.merge(
                irf_neg[["t", s]].rename(columns={"t": "horizon", s: "m_neg"}),
                on="horizon",
                how="inner",
            )
            if m.empty:
                continue

            # Base term-level model mapping before gains/asymmetry.
            m["x_pos"] = (m["m_pos"] / mp_pos) * m["sd_pos"]
            if neg_available:
                m["x_neg"] = (m["m_neg"] / mp_neg) * m["sd_neg"]
            else:
                m["x_neg"] = -(m["m_pos"] / mp_pos) * m["sd_neg"]

            for _, r in m.iterrows():
                rows.append(
                    {
                        "dataset": ds,
                        "group": group,
                        "horizon": int(r["horizon"]),
                        "y_pos": float(r["y_pos"]),
                        "y_neg": float(r["y_neg"]),
                        "x_pos": float(r["x_pos"]),
                        "x_neg": float(r["x_neg"]),
                    }
                )

    panel = pd.DataFrame(rows)
    if panel.empty:
        raise ValueError("No panel rows built for augmented scaling fit.")
    return panel, mp_pos


def _fit_augmented(panel: pd.DataFrame, max_iter: int, tol: float) -> tuple[dict[tuple[str, str], float], dict[str, float]]:
    keys = sorted({(r.dataset, r.group) for r in panel.itertuples(index=False)})
    gains = {k: 1.0 for k in keys}
    chi = {"PH2M": 1.0, "WH2M": 1.0}

    for _ in range(max_iter):
        old = np.array([*gains.values(), chi["PH2M"], chi["WH2M"]], dtype=float)

        # Update gains given chi.
        for k in keys:
            ds, g = k
            s = panel[(panel["dataset"] == ds) & (panel["group"] == g)]
            c = chi[g]
            num = float((s["y_pos"] * s["x_pos"]).sum() + (s["y_neg"] * (c * s["x_neg"])).sum())
            den = float((s["x_pos"] ** 2).sum() + ((c * s["x_neg"]) ** 2).sum())
            gains[k] = num / den if den > 1e-12 else gains[k]

        # Update chi by group given gains.
        for g in ["PH2M", "WH2M"]:
            s = panel[panel["group"] == g].copy()
            s["gxneg"] = s.apply(lambda r: gains[(r["dataset"], r["group"])] * r["x_neg"], axis=1)
            num = float((s["y_neg"] * s["gxneg"]).sum())
            den = float((s["gxneg"] ** 2).sum())
            chi[g] = max(0.0, num / den) if den > 1e-12 else chi[g]

        new = np.array([*gains.values(), chi["PH2M"], chi["WH2M"]], dtype=float)
        if np.max(np.abs(new - old)) < tol:
            break

    return gains, chi


def _make_outputs(
    panel: pd.DataFrame,
    gains: dict[tuple[str, str], float],
    chi: dict[str, float],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    out = panel.copy()
    out["gain"] = out.apply(lambda r: gains[(r["dataset"], r["group"])], axis=1)
    out["chi"] = out["group"].map(chi)
    out["pred_pos_aug"] = out["gain"] * out["x_pos"]
    out["pred_neg_aug"] = out["gain"] * out["chi"] * out["x_neg"]
    out["err_pos_aug"] = out["pred_pos_aug"] - out["y_pos"]
    out["err_neg_aug"] = out["pred_neg_aug"] - out["y_neg"]

    # Baseline structural errors (gain=1, chi=1)
    out["err_pos_struct"] = out["x_pos"] - out["y_pos"]
    out["err_neg_struct"] = out["x_neg"] - out["y_neg"]

    out.to_csv(output_dir / "augmented_scaling_aligned.csv", index=False)

    summ_rows = []
    for ds in sorted(out["dataset"].unique()):
        s = out[out["dataset"] == ds]
        mae_struct = float(
            np.mean(
                np.concatenate(
                    [
                        np.abs(s["err_pos_struct"].to_numpy()),
                        np.abs(s["err_neg_struct"].to_numpy()),
                    ]
                )
            )
        )
        mae_aug = float(
            np.mean(
                np.concatenate(
                    [np.abs(s["err_pos_aug"].to_numpy()), np.abs(s["err_neg_aug"].to_numpy())]
                )
            )
        )
        summ_rows.append(
            {
                "dataset": ds,
                "mae_struct": mae_struct,
                "mae_augmented": mae_aug,
                "improvement": mae_struct - mae_aug,
            }
        )

    gains_rows = [
        {"dataset": ds, "group": g, "gain": float(v)} for (ds, g), v in sorted(gains.items())
    ]
    chi_rows = [{"group": k, "chi_expansionary": float(v)} for k, v in chi.items()]

    pd.DataFrame(summ_rows).to_csv(output_dir / "augmented_scaling_summary.csv", index=False)
    pd.DataFrame(gains_rows).to_csv(output_dir / "augmented_scaling_gains.csv", index=False)
    pd.DataFrame(chi_rows).to_csv(output_dir / "augmented_scaling_asymmetry.csv", index=False)

    lines = []
    lines.append("# Augmented Scaling Review")
    lines.append("")
    lines.append("This layer fits dataset/group gains and group-level expansionary asymmetry factors on top of THRANK IRFs.")
    lines.append("It does not change structural dynamics; it quantifies measurement/asymmetry gaps.")
    lines.append("")
    lines.append("## Fitted Asymmetry")
    for r in chi_rows:
        lines.append(f"- {r['group']}: chi_expansionary={r['chi_expansionary']:.4f}")
    lines.append("")
    lines.append("## Fitted Gains")
    for r in gains_rows:
        lines.append(f"- {r['dataset']} / {r['group']}: gain={r['gain']:.4f}")
    lines.append("")
    lines.append("## MAE Improvement")
    for r in summ_rows:
        lines.append(
            f"- {r['dataset']}: struct={r['mae_struct']:.4f}, augmented={r['mae_augmented']:.4f}, improvement={r['improvement']:.4f}"
        )

    (output_dir / "augmented_scaling_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    panel, _ = _build_panel(args.thrank_dir, args.fit_max_h, args.wealth_model_series)
    gains, chi = _fit_augmented(panel, args.max_iter, args.tol)
    _make_outputs(panel, gains, chi, args.output_dir)
    print(f"Wrote augmented scaling outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
