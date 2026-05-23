from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


THRESHOLDS = {
    "controls_gap_max": 0.05,
    "income_gap_max": 0.05,
    "wealth_gap_max": 0.20,
    "controls_ci_hit_min": 0.20,
    "income_ci_hit_min": 0.30,
    "wealth_ci_hit_min": 0.50,
    "max_h0_sign_mismatches": 2,
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Review THRANK calibration runs against DI-TWFE diagnostics.")
    p.add_argument(
        "--baseline-diagnostics",
        type=Path,
        default=Path("THRANK/results/compare_baseline/thrank_lp_diagnostics.csv"),
    )
    p.add_argument(
        "--candidate-diagnostics",
        type=Path,
        default=Path("THRANK/results/compare_tuned_joint_di_twfe/thrank_lp_diagnostics.csv"),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("THRANK/results/compare_tuned_joint_di_twfe"),
    )
    p.add_argument(
        "--impact-sign-epsilon",
        type=float,
        default=0.005,
        help=(
            "Do not count H0 sign mismatch when |impact_h0_lp| <= epsilon "
            "(near-zero empirical impact)."
        ),
    )
    return p.parse_args()


def _run_metrics(df: pd.DataFrame, impact_sign_epsilon: float) -> dict[str, float]:
    d = {}
    d["controls_gap"] = float(df.loc[df["dataset"] == "lp_controls", "mean_abs_gap_h0_h24"].mean())
    d["income_gap"] = float(df.loc[df["dataset"] == "lp_income", "mean_abs_gap_h0_h24"].mean())
    d["wealth_gap"] = float(df.loc[df["dataset"] == "lp_wealth", "mean_abs_gap_h0_h24"].mean())

    d["controls_ci_hit"] = float(df.loc[df["dataset"] == "lp_controls", "ci_hit_share_h0_h24"].mean())
    d["income_ci_hit"] = float(df.loc[df["dataset"] == "lp_income", "ci_hit_share_h0_h24"].mean())
    d["wealth_ci_hit"] = float(df.loc[df["dataset"] == "lp_wealth", "ci_hit_share_h0_h24"].mean())

    lp = df["impact_h0_lp"].to_numpy()
    model = df["impact_h0_model"].to_numpy()
    near_zero = np.abs(lp) <= impact_sign_epsilon
    sign_match = np.sign(lp) == np.sign(model)
    d["h0_sign_mismatches"] = int((~sign_match & ~near_zero).sum())
    d["h0_near_zero_ignored"] = int(near_zero.sum())
    d["overall_corr"] = float(df["corr_h0_h24"].mean())
    return d


def _pass_flags(metrics: dict[str, float]) -> dict[str, bool]:
    return {
        "controls_gap_pass": metrics["controls_gap"] <= THRESHOLDS["controls_gap_max"],
        "income_gap_pass": metrics["income_gap"] <= THRESHOLDS["income_gap_max"],
        "wealth_gap_pass": metrics["wealth_gap"] <= THRESHOLDS["wealth_gap_max"],
        "controls_ci_pass": metrics["controls_ci_hit"] >= THRESHOLDS["controls_ci_hit_min"],
        "income_ci_pass": metrics["income_ci_hit"] >= THRESHOLDS["income_ci_hit_min"],
        "wealth_ci_pass": metrics["wealth_ci_hit"] >= THRESHOLDS["wealth_ci_hit_min"],
        "h0_sign_pass": metrics["h0_sign_mismatches"] <= THRESHOLDS["max_h0_sign_mismatches"],
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    base = pd.read_csv(args.baseline_diagnostics)
    cand = pd.read_csv(args.candidate_diagnostics)

    base_m = _run_metrics(base, args.impact_sign_epsilon)
    cand_m = _run_metrics(cand, args.impact_sign_epsilon)
    base_flags = _pass_flags(base_m)
    cand_flags = _pass_flags(cand_m)

    rows = []
    keys = [
        "controls_gap",
        "income_gap",
        "wealth_gap",
        "controls_ci_hit",
        "income_ci_hit",
        "wealth_ci_hit",
        "h0_sign_mismatches",
        "h0_near_zero_ignored",
        "overall_corr",
    ]
    for k in keys:
        rows.append(
            {
                "metric": k,
                "baseline": base_m[k],
                "candidate": cand_m[k],
                "delta_candidate_minus_baseline": cand_m[k] - base_m[k],
            }
        )

    pd.DataFrame(rows).to_csv(args.output_dir / "calibration_review_metrics.csv", index=False)

    lines = []
    lines.append("# THRANK Calibration Acceptance Review")
    lines.append("")
    lines.append("## Thresholds")
    for k, v in THRESHOLDS.items():
        lines.append(f"- `{k}`: `{v}`")
    lines.append(f"- `impact_sign_epsilon`: `{args.impact_sign_epsilon}`")
    lines.append("")
    lines.append("## Candidate vs Baseline")
    lines.append("|metric|baseline|candidate|delta|")
    lines.append("|---|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"|{r['metric']}|{r['baseline']:.4f}|{r['candidate']:.4f}|{r['delta_candidate_minus_baseline']:.4f}|"
        )

    lines.append("")
    lines.append("## Pass/Fail")
    for k, v in cand_flags.items():
        lines.append(f"- {k}: {'PASS' if v else 'FAIL'}")

    n_pass = int(sum(cand_flags.values()))
    lines.append("")
    lines.append(f"## Summary")
    lines.append(f"- Candidate passed `{n_pass}/{len(cand_flags)}` acceptance checks.")

    (args.output_dir / "calibration_acceptance_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote review outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
