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
    from thrank_ssj_model import (
        EXOGENOUS_SHOCKS,
        REPORT_OUTPUTS,
        TARGETS,
        UNKNOWNS,
        build_model,
    )
else:
    from .thrank_calibration import make_default_calibration
    from .thrank_ssj_model import (
        EXOGENOUS_SHOCKS,
        REPORT_OUTPUTS,
        TARGETS,
        UNKNOWNS,
        build_model,
    )


def _build_shock_path(horizon: int, impact: float) -> np.ndarray:
    path = np.zeros(horizon, dtype=float)
    path[0] = impact
    return path


def _impulse_to_df(impulse, outputs: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame({"t": np.arange(impulse.T, dtype=int)})
    for out in outputs:
        frame[out] = impulse[out]
    return frame


def _cumulative_irf_df(irf_df: pd.DataFrame, outputs: list[str]) -> pd.DataFrame:
    cumulative = pd.DataFrame({"t": irf_df["t"].to_numpy()})
    for out in outputs:
        cumulative[out] = irf_df[out].cumsum()
    return cumulative


def _jacobian_impact_summary(jacobian, outputs: list[str], shocks: list[str]) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for output in outputs:
        for shock in shocks:
            matrix = jacobian[output, shock]
            rows.append(
                {
                    "output": output,
                    "shock": shock,
                    "impact_t0": float(matrix[0, 0]),
                    "peak_abs_col0": float(np.max(np.abs(matrix[:, 0]))),
                    "sum_col0": float(np.sum(matrix[:, 0])),
                }
            )
    return pd.DataFrame(rows)


def _steady_state_residual_report(ss: dict, targets: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "target": targets,
            "steady_state_value": [float(ss[t]) for t in targets],
            "abs_value": [float(abs(ss[t])) for t in targets],
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a tractable SSJ implementation of THRANK-BR and export IRFs/Jacobians."
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=49,
        help="IRF length. Default 49 matches empirical LP horizons 0..48.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("THRANK") / "results" / "baseline",
        help="Directory for generated outputs.",
    )
    parser.add_argument(
        "--mp-shock-size",
        type=float,
        default=0.06769240782078953 / 100.0,
        help=(
            "Impact size for e_R in model units (default uses data std converted from "
            "percentage points to decimal units)."
        ),
    )
    parser.add_argument(
        "--mp-neg-shock-size",
        type=float,
        default=0.06769240782078953 / 100.0,
        help="Impact size for e_R_neg (expansionary-direction shock) in model units.",
    )
    parser.add_argument(
        "--transfer-shock-size",
        type=float,
        default=0.05,
        help="Impact size for e_T transfer shock.",
    )
    parser.add_argument(
        "--plot-irfs",
        action="store_true",
        help="If provided, attempt to export a PNG panel of monetary IRFs.",
    )
    parser.add_argument(
        "--calibration-overrides",
        type=Path,
        default=None,
        help="Optional JSON file with calibration key/value overrides.",
    )
    return parser.parse_args()


def _plot_monetary_irfs(irf_df: pd.DataFrame, outpath: Path) -> None:
    import matplotlib.pyplot as plt

    variables = ["Y", "cR", "cW", "cP", "pi", "R", "r", "X", "q", "hW", "bW"]
    ncols = 3
    nrows = int(np.ceil(len(variables) / ncols))
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(12, 10), sharex=True)
    axes = np.array(axes).reshape(-1)

    t = irf_df["t"].to_numpy()
    for i, var in enumerate(variables):
        ax = axes[i]
        ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.5)
        ax.plot(t, irf_df[var].to_numpy(), linewidth=1.7)
        ax.set_title(var)
        ax.grid(alpha=0.25)

    for j in range(len(variables), len(axes)):
        axes[j].axis("off")

    fig.suptitle("THRANK Monetary Shock IRFs")
    fig.tight_layout()
    fig.savefig(outpath, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    calibration = make_default_calibration(repo_root)
    if args.calibration_overrides is not None:
        if not args.calibration_overrides.exists():
            raise FileNotFoundError(f"Missing calibration override file: {args.calibration_overrides}")
        overrides = json.loads(args.calibration_overrides.read_text(encoding="utf-8"))
        if not isinstance(overrides, dict):
            raise ValueError("Calibration overrides JSON must be an object.")
        calibration.update({k: float(v) for k, v in overrides.items()})
    model, unknowns, targets, exogenous, report_outputs = build_model()

    ss = model.steady_state(calibration)
    residual_table = _steady_state_residual_report(ss, targets)
    max_abs_resid = float(residual_table["abs_value"].max())

    zeros = np.zeros(args.horizon, dtype=float)

    mp_pos_inputs = {name: zeros.copy() for name in exogenous}
    mp_pos_inputs["e_R"] = _build_shock_path(args.horizon, args.mp_shock_size)
    irf_mp_pos = model.solve_impulse_linear(
        ss, unknowns, targets, mp_pos_inputs, outputs=report_outputs
    )

    mp_neg_inputs = {name: zeros.copy() for name in exogenous}
    mp_neg_inputs["e_R_neg"] = _build_shock_path(args.horizon, args.mp_neg_shock_size)
    irf_mp_neg = model.solve_impulse_linear(
        ss, unknowns, targets, mp_neg_inputs, outputs=report_outputs
    )

    transfer_inputs = {name: zeros.copy() for name in exogenous}
    transfer_inputs["e_T"] = _build_shock_path(args.horizon, args.transfer_shock_size)
    irf_transfer = model.solve_impulse_linear(
        ss, unknowns, targets, transfer_inputs, outputs=report_outputs
    )

    ge_jacobian = model.solve_jacobian(
        ss=ss,
        unknowns=unknowns,
        targets=targets,
        inputs=["e_R", "e_R_neg", "e_T"],
        outputs=report_outputs,
        T=args.horizon,
    )

    calibration_path = output_dir / "calibration.json"
    with calibration_path.open("w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, sort_keys=True)

    residual_table.to_csv(output_dir / "steady_state_residuals.csv", index=False)
    irf_mp_pos_df = _impulse_to_df(irf_mp_pos, report_outputs)
    irf_mp_pos_cum_df = _cumulative_irf_df(irf_mp_pos_df, report_outputs)
    irf_mp_pos_df.to_csv(output_dir / "irf_mp_pos_shock.csv", index=False)
    irf_mp_pos_cum_df.to_csv(output_dir / "irf_mp_pos_shock_cumulative.csv", index=False)

    # Backward-compatible aliases: mp_shock = contractionary (positive-rate) shock.
    irf_mp_pos_df.to_csv(output_dir / "irf_mp_shock.csv", index=False)
    irf_mp_pos_cum_df.to_csv(output_dir / "irf_mp_shock_cumulative.csv", index=False)

    irf_mp_neg_df = _impulse_to_df(irf_mp_neg, report_outputs)
    irf_mp_neg_cum_df = _cumulative_irf_df(irf_mp_neg_df, report_outputs)
    irf_mp_neg_df.to_csv(output_dir / "irf_mp_neg_shock.csv", index=False)
    irf_mp_neg_cum_df.to_csv(output_dir / "irf_mp_neg_shock_cumulative.csv", index=False)
    irf_transfer_df = _impulse_to_df(irf_transfer, report_outputs)
    irf_transfer_df.to_csv(output_dir / "irf_transfer_shock.csv", index=False)
    _cumulative_irf_df(irf_transfer_df, report_outputs).to_csv(
        output_dir / "irf_transfer_shock_cumulative.csv", index=False
    )
    _jacobian_impact_summary(
        ge_jacobian, outputs=report_outputs, shocks=["e_R", "e_R_neg", "e_T"]
    ).to_csv(output_dir / "jacobian_impact_summary.csv", index=False)

    run_summary = {
        "horizon": args.horizon,
        "mp_shock_size": args.mp_shock_size,
        "mp_neg_shock_size": args.mp_neg_shock_size,
        "transfer_shock_size": args.transfer_shock_size,
        "max_abs_ss_residual": max_abs_resid,
        "unknowns": unknowns,
        "targets": targets,
        "exogenous_shocks": exogenous,
        "report_outputs": report_outputs,
    }
    with (output_dir / "run_summary.json").open("w", encoding="utf-8") as f:
        json.dump(run_summary, f, indent=2, sort_keys=True)

    if args.plot_irfs:
        try:
            _plot_monetary_irfs(irf_mp_pos_df, output_dir / "irf_mp_shock.png")
        except Exception as exc:  # pragma: no cover - environment-dependent plotting
            print(f"IRF plot skipped due to plotting error: {exc}")

    print("THRANK run completed.")
    print(f"Output directory: {output_dir}")
    print(f"Max absolute steady-state residual: {max_abs_resid:.3e}")
    print("Generated files:")
    for generated in sorted(output_dir.glob("*")):
        print(f" - {generated.name}")


if __name__ == "__main__":
    main()
