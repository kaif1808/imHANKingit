from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LPSpec:
    dataset: str
    path: Path
    response_label: str


@dataclass(frozen=True)
class TermSpec:
    term: str
    group: str
    direction: str
    model_sign: float


LP_SPECS = [
    LPSpec(
        dataset="lp_controls",
        path=Path("results/tables/lp_controls/irf_consumption_directional_dummies_twfe_dk.csv"),
        response_label="consumption",
    ),
    LPSpec(
        dataset="lp_income",
        path=Path("results/tables/lp_income/irf_income_directional_dummies_twfe_dk.csv"),
        response_label="income",
    ),
    LPSpec(
        dataset="lp_wealth",
        path=Path("results/tables/lp_wealth/irf_wealth_directional_dummies_twfe_dk.csv"),
        response_label="wealth",
    ),
]

TERM_SPECS = [
    TermSpec(
        term="mp_pos_x_ph2m",
        group="PH2M",
        direction="contractionary",
        model_sign=1.0,
    ),
    TermSpec(
        term="mp_neg_x_ph2m",
        group="PH2M",
        direction="expansionary",
        model_sign=-1.0,
    ),
    TermSpec(
        term="mp_pos_x_wh2m",
        group="WH2M",
        direction="contractionary",
        model_sign=1.0,
    ),
    TermSpec(
        term="mp_neg_x_wh2m",
        group="WH2M",
        direction="expansionary",
        model_sign=-1.0,
    ),
]

EMPIRICAL_SCRIPT_PATHS = [
    Path("scripts/reporting/celina_lp_lpirfs_direction_dummy.r"),
    Path("scripts/reporting/celina_lp_income_lpirfs_direction_dummy.r"),
    Path("scripts/reporting/celina_lp_wealth_lpirfs_direction_dummy.r"),
]


def _series_for(dataset: str, group: str, wealth_model_series: str) -> str:
    if dataset == "lp_wealth" and wealth_model_series != "c_based":
        return "wP" if group == "PH2M" else "wW"
    return "cP" if group == "PH2M" else "cW"


def _add_wealth_observables(
    thrank: pd.DataFrame,
    calibration: dict,
    wealth_model_series: str,
) -> pd.DataFrame:
    out = thrank.copy()
    # Always define wealth-observable placeholders for downstream uniform logic.
    out["wP"] = out["cP"]
    out["wW"] = out["cW"]
    if wealth_model_series == "net_deposit":
        out["wP"] = out["dP"]
        out["wW"] = out["dW"] - out["bW"]
        return out
    if wealth_model_series == "wealth_measurement":
        theta_wP_c = float(calibration.get("theta_wP_c", 1.0))
        theta_wP_d = float(calibration.get("theta_wP_d", 0.0))
        theta_wP_tp = float(calibration.get("theta_wP_tp", 0.0))
        theta_wW_c = float(calibration.get("theta_wW_c", 1.0))
        theta_wW_d = float(calibration.get("theta_wW_d", 0.0))
        theta_wW_b = float(calibration.get("theta_wW_b", 0.0))

        out["wP"] = theta_wP_c * out["cP"] + theta_wP_d * out["dP"] + theta_wP_tp * out["TP"]
        out["wW"] = theta_wW_c * out["cW"] + theta_wW_d * out["dW"] + theta_wW_b * out["bW"]
        return out
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare THRANK IRFs to empirical DI-shock TWFE LP IRFs.")
    parser.add_argument(
        "--thrank-dir",
        type=Path,
        default=Path("THRANK/results/baseline"),
        help="Directory containing THRANK outputs from run_thrank.py",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("THRANK/results/compare_baseline"),
        help="Directory for comparison outputs.",
    )
    parser.add_argument(
        "--lp-dataset-path",
        type=Path,
        default=Path("results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"),
        help="Path to LP state-month dataset for schema/provenance checks.",
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
    return parser.parse_args()


def _require_columns(df: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"{name} missing required columns: {sorted(missing)}")


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2 or len(b) < 2:
        return np.nan
    if np.allclose(np.std(a), 0) or np.allclose(np.std(b), 0):
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def _peak_info(h: np.ndarray, x: np.ndarray) -> tuple[int, float]:
    idx = int(np.argmax(np.abs(x)))
    return int(h[idx]), float(x[idx])


def _half_life(h: np.ndarray, x: np.ndarray) -> float:
    if len(x) == 0:
        return np.nan
    impact = abs(float(x[0]))
    if impact <= 1e-12:
        return np.nan
    thresh = 0.5 * impact
    for hi, xi in zip(h, x, strict=True):
        if abs(float(xi)) <= thresh:
            return float(hi)
    return np.nan


def _load_schema_note(lp_dataset_path: Path) -> dict[str, str | int | bool]:
    if not lp_dataset_path.exists():
        return {
            "dataset_path": str(lp_dataset_path),
            "exists": False,
            "has_mp_shock_di": False,
            "has_mp_shock": False,
            "n_columns": 0,
        }
    df = pd.read_csv(lp_dataset_path, nrows=3)
    cols = set(df.columns)
    return {
        "dataset_path": str(lp_dataset_path),
        "exists": True,
        "has_mp_shock_di": "mp_shock_di" in cols,
        "has_mp_shock": "mp_shock" in cols,
        "n_columns": len(cols),
    }


def _validate_lp_spec(lp: pd.DataFrame, dataset: str) -> None:
    _require_columns(
        lp,
        {
            "horizon",
            "term",
            "estimate_1sd",
            "ci_low_1sd",
            "ci_high_1sd",
            "shock_sd",
            "spec",
            "se_method",
            "response_type",
        },
        dataset,
    )

    specs = set(lp["spec"].dropna().unique())
    se_methods = set(lp["se_method"].dropna().unique())
    responses = set(lp["response_type"].dropna().unique())

    if specs != {"twfe_directional_dummies"}:
        raise ValueError(f"{dataset}: expected spec=twfe_directional_dummies, found {sorted(specs)}")
    if se_methods != {"driscoll_kraay"}:
        raise ValueError(f"{dataset}: expected se_method=driscoll_kraay, found {sorted(se_methods)}")
    if responses != {"cumulative"}:
        raise ValueError(f"{dataset}: expected response_type=cumulative, found {sorted(responses)}")


def _file_fingerprint(path: Path) -> dict[str, str | int | bool]:
    out: dict[str, str | int | bool] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return out
    stat = path.stat()
    out["size_bytes"] = int(stat.st_size)
    out["mtime_utc"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    out["sha256"] = h.hexdigest()
    return out


def _write_empirical_provenance(output_dir: Path) -> None:
    entries: list[dict[str, str | int | bool]] = []
    for script_path in EMPIRICAL_SCRIPT_PATHS:
        entries.append(_file_fingerprint(script_path))
    for lp in LP_SPECS:
        entries.append(_file_fingerprint(lp.path))

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Provenance for DI-shock TWFE empirical IRF targets used by THRANK comparison/tuning",
        "entries": entries,
    }
    (output_dir / "empirical_irf_provenance.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def build_comparison(
    thrank_dir: Path,
    output_dir: Path,
    lp_dataset_path: Path,
    wealth_model_series: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    run_summary_path = thrank_dir / "run_summary.json"
    thrank_pos_cum_path = thrank_dir / "irf_mp_pos_shock_cumulative.csv"
    thrank_neg_cum_path = thrank_dir / "irf_mp_neg_shock_cumulative.csv"
    thrank_legacy_cum_path = thrank_dir / "irf_mp_shock_cumulative.csv"
    calibration_path = thrank_dir / "calibration.json"

    if not run_summary_path.exists() or not calibration_path.exists():
        raise FileNotFoundError(
            "Missing THRANK files. Required: run_summary.json and calibration.json"
        )
    if not thrank_pos_cum_path.exists() and not thrank_legacy_cum_path.exists():
        raise FileNotFoundError(
            "Missing THRANK cumulative IRF files. Need irf_mp_pos_shock_cumulative.csv or irf_mp_shock_cumulative.csv."
        )

    run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    schema_note = _load_schema_note(lp_dataset_path)

    pos_path = thrank_pos_cum_path if thrank_pos_cum_path.exists() else thrank_legacy_cum_path
    neg_path = thrank_neg_cum_path if thrank_neg_cum_path.exists() else None

    thrank_pos = pd.read_csv(pos_path)
    _require_columns(thrank_pos, {"t", "cP", "cW", "dP", "dW", "bW", "TP"}, "THRANK pos cumulative IRF")
    thrank_pos = _add_wealth_observables(thrank_pos, calibration, wealth_model_series)

    neg_available = neg_path is not None
    if neg_available:
        thrank_neg = pd.read_csv(neg_path)
        _require_columns(thrank_neg, {"t", "cP", "cW", "dP", "dW", "bW", "TP"}, "THRANK neg cumulative IRF")
        thrank_neg = _add_wealth_observables(thrank_neg, calibration, wealth_model_series)
    else:
        thrank_neg = thrank_pos.copy()

    mp_pos_shock = float(run_summary["mp_shock_size"])
    mp_neg_shock = float(run_summary.get("mp_neg_shock_size", mp_pos_shock))
    if abs(mp_pos_shock) <= 1e-12:
        raise ValueError("mp_shock_size is zero; cannot rescale model IRFs to LP shock units.")
    if abs(mp_neg_shock) <= 1e-12:
        raise ValueError("mp_neg_shock_size is zero; cannot rescale model IRFs to LP shock units.")

    aligned_rows: list[dict[str, float | int | str | bool]] = []
    diag_rows: list[dict[str, float | int | str | bool]] = []
    diff_rows: list[dict[str, float | int | str | bool]] = []
    coverage_rows: list[dict[str, float | int | str | bool]] = []

    thrank_pos_small = thrank_pos[["t", "cP", "cW", "wP", "wW"]].copy().rename(columns={"t": "horizon"})
    thrank_neg_small = thrank_neg[["t", "cP", "cW", "wP", "wW"]].copy().rename(columns={"t": "horizon"})
    pos_horizons = set(thrank_pos_small["horizon"].astype(int).tolist())
    neg_horizons = set(thrank_neg_small["horizon"].astype(int).tolist())

    for spec in LP_SPECS:
        if not spec.path.exists():
            raise FileNotFoundError(f"Missing LP file: {spec.path}")

        lp = pd.read_csv(spec.path)
        _validate_lp_spec(lp, spec.dataset)
        lp_horizons = set(lp["horizon"].astype(int).tolist())

        for term_spec in TERM_SPECS:
            model_series = _series_for(spec.dataset, term_spec.group, wealth_model_series)
            is_expansionary = term_spec.direction == "expansionary"
            if is_expansionary:
                thrank_source = thrank_neg_small
                shock_size = mp_neg_shock
                sign_factor = 1.0 if neg_available else term_spec.model_sign
                model_horizons = neg_horizons
            else:
                thrank_source = thrank_pos_small
                shock_size = mp_pos_shock
                sign_factor = 1.0
                model_horizons = pos_horizons
            lp_t = lp[lp["term"] == term_spec.term].copy().sort_values("horizon")
            thrank_t = thrank_source[["horizon", model_series]].copy().rename(
                columns={model_series: "model_cum_response"}
            )

            merged = lp_t.merge(thrank_t, on="horizon", how="inner")
            if merged.empty:
                continue
            overlap_horizons = set(merged["horizon"].astype(int).tolist())
            missing_lp_in_model = sorted(lp_horizons - model_horizons)
            missing_model_in_lp = sorted(model_horizons - lp_horizons)
            coverage_rows.append(
                {
                    "dataset": spec.dataset,
                    "term": term_spec.term,
                    "direction": term_spec.direction,
                    "lp_h_min": int(min(lp_horizons)),
                    "lp_h_max": int(max(lp_horizons)),
                    "lp_n_h": int(len(lp_horizons)),
                    "model_h_min": int(min(model_horizons)),
                    "model_h_max": int(max(model_horizons)),
                    "model_n_h": int(len(model_horizons)),
                    "overlap_h_min": int(min(overlap_horizons)),
                    "overlap_h_max": int(max(overlap_horizons)),
                    "overlap_n_h": int(len(overlap_horizons)),
                    "lp_horizons_missing_in_model": ",".join(map(str, missing_lp_in_model)),
                    "model_horizons_missing_in_lp": ",".join(map(str, missing_model_in_lp)),
                }
            )

            shock_sd = float(merged["shock_sd"].mean())
            merged["model_per_unit_shock"] = merged["model_cum_response"] / shock_size
            merged["model_1sd_termshock"] = (
                sign_factor * merged["model_per_unit_shock"] * shock_sd
            )
            merged["gap_model_minus_lp"] = merged["model_1sd_termshock"] - merged["estimate_1sd"]
            merged["model_in_lp_ci"] = (
                (merged["model_1sd_termshock"] >= merged["ci_low_1sd"])
                & (merged["model_1sd_termshock"] <= merged["ci_high_1sd"])
            )
            merged["sign_match"] = np.sign(merged["model_1sd_termshock"]) == np.sign(merged["estimate_1sd"])

            for _, r in merged.iterrows():
                aligned_rows.append(
                    {
                        "dataset": spec.dataset,
                        "response_label": spec.response_label,
                        "group": term_spec.group,
                        "direction": term_spec.direction,
                        "term": term_spec.term,
                        "model_series": model_series,
                        "linear_sign_assumption": sign_factor,
                        "horizon": int(r["horizon"]),
                        "lp_estimate_1sd": float(r["estimate_1sd"]),
                        "lp_ci_low_1sd": float(r["ci_low_1sd"]),
                        "lp_ci_high_1sd": float(r["ci_high_1sd"]),
                        "lp_shock_sd": float(r["shock_sd"]),
                        "model_cum_response_at_model_shock": float(r["model_cum_response"]),
                        "model_1sd_termshock": float(r["model_1sd_termshock"]),
                        "gap_model_minus_lp": float(r["gap_model_minus_lp"]),
                        "model_in_lp_ci": bool(r["model_in_lp_ci"]),
                        "sign_match": bool(r["sign_match"]),
                    }
                )

            h = merged["horizon"].to_numpy(dtype=int)
            lp_x = merged["estimate_1sd"].to_numpy(dtype=float)
            m_x = merged["model_1sd_termshock"].to_numpy(dtype=float)
            mask_24 = h <= 24

            p_h, p_v = _peak_info(h, lp_x)
            m_h, m_v = _peak_info(h, m_x)
            h24_lp = (
                float(merged.loc[merged["horizon"] == 24, "estimate_1sd"].iloc[0])
                if (merged["horizon"] == 24).any()
                else np.nan
            )
            h24_m = (
                float(merged.loc[merged["horizon"] == 24, "model_1sd_termshock"].iloc[0])
                if (merged["horizon"] == 24).any()
                else np.nan
            )

            diag_rows.append(
                {
                    "dataset": spec.dataset,
                    "response_label": spec.response_label,
                    "group": term_spec.group,
                    "direction": term_spec.direction,
                    "term": term_spec.term,
                    "model_series": model_series,
                    "linear_sign_assumption": sign_factor,
                    "shock_sd_mean": float(shock_sd),
                    "corr_h0_h24": _safe_corr(lp_x[mask_24], m_x[mask_24]),
                    "sign_match_share_h0_h24": float(
                        (np.sign(lp_x[mask_24]) == np.sign(m_x[mask_24])).mean()
                    ),
                    "ci_hit_share_h0_h24": float(merged.loc[mask_24, "model_in_lp_ci"].mean()),
                    "impact_h0_lp": float(lp_x[0]),
                    "impact_h0_model": float(m_x[0]),
                    "peak_h_lp": p_h,
                    "peak_val_lp": p_v,
                    "peak_h_model": m_h,
                    "peak_val_model": m_v,
                    "h24_lp": h24_lp,
                    "h24_model": h24_m,
                    "mean_abs_gap_h0_h24": float(np.abs((m_x - lp_x)[mask_24]).mean()),
                    "half_life_lp": _half_life(h, lp_x),
                    "half_life_model": _half_life(h, m_x),
                }
            )

        # Differential PH2M-WH2M by direction.
        for direction, ph_term, wh_term in [
            ("contractionary", "mp_pos_x_ph2m", "mp_pos_x_wh2m"),
            ("expansionary", "mp_neg_x_ph2m", "mp_neg_x_wh2m"),
        ]:
            ph = lp[lp["term"] == ph_term][["horizon", "estimate_1sd", "shock_sd"]].copy()
            wh = lp[lp["term"] == wh_term][["horizon", "estimate_1sd", "shock_sd"]].copy()
            ph = ph.rename(columns={"estimate_1sd": "lp_ph", "shock_sd": "shock_sd_ph"})
            wh = wh.rename(columns={"estimate_1sd": "lp_wh", "shock_sd": "shock_sd_wh"})
            d = ph.merge(wh, on="horizon", how="inner").sort_values("horizon")
            if direction == "expansionary":
                t_use = thrank_neg_small
                shock_size = mp_neg_shock
                sign_factor = 1.0 if neg_available else -1.0
            else:
                t_use = thrank_pos_small
                shock_size = mp_pos_shock
                sign_factor = 1.0
            d = d.merge(t_use, on="horizon", how="inner")

            if d.empty:
                continue

            ph_series = _series_for(spec.dataset, "PH2M", wealth_model_series)
            wh_series = _series_for(spec.dataset, "WH2M", wealth_model_series)
            d["lp_diff_ph_minus_wh"] = d["lp_ph"] - d["lp_wh"]
            d["model_diff_ph_minus_wh"] = sign_factor * (
                (d[ph_series] / shock_size) * d["shock_sd_ph"]
                - (d[wh_series] / shock_size) * d["shock_sd_wh"]
            )
            for _, r in d.iterrows():
                diff_rows.append(
                    {
                        "dataset": spec.dataset,
                        "response_label": spec.response_label,
                        "direction": direction,
                        "horizon": int(r["horizon"]),
                        "lp_diff_ph_minus_wh": float(r["lp_diff_ph_minus_wh"]),
                        "model_diff_ph_minus_wh": float(r["model_diff_ph_minus_wh"]),
                        "gap_diff_model_minus_lp": float(
                            r["model_diff_ph_minus_wh"] - r["lp_diff_ph_minus_wh"]
                        ),
                    }
                )

    aligned = pd.DataFrame(aligned_rows)
    diagnostics = pd.DataFrame(diag_rows)
    differential = pd.DataFrame(diff_rows)
    horizon_coverage = pd.DataFrame(coverage_rows)

    aligned.to_csv(output_dir / "thrank_lp_aligned_series.csv", index=False)
    diagnostics.to_csv(output_dir / "thrank_lp_diagnostics.csv", index=False)
    differential.to_csv(output_dir / "thrank_lp_differential_series.csv", index=False)
    horizon_coverage.to_csv(output_dir / "thrank_lp_horizon_coverage.csv", index=False)
    _write_empirical_provenance(output_dir)

    _write_md_report(
        output_dir,
        diagnostics,
        differential,
        horizon_coverage,
        run_summary,
        calibration,
        schema_note,
        wealth_model_series,
        neg_available,
    )


def _fmt(v: float, nd: int = 4) -> str:
    if pd.isna(v):
        return "NA"
    return f"{v:.{nd}f}"


def _write_md_report(
    output_dir: Path,
    diagnostics: pd.DataFrame,
    differential: pd.DataFrame,
    horizon_coverage: pd.DataFrame,
    run_summary: dict,
    calibration: dict,
    schema_note: dict[str, str | int | bool],
    wealth_model_series: str,
    neg_available: bool,
) -> None:
    lines: list[str] = []
    lines.append("# THRANK vs Empirical LP IRFs (DI shock, TWFE)")
    lines.append("")
    lines.append("## Scope")
    lines.append("- Empirical references: `lp_controls`, `lp_income`, `lp_wealth` directional LP tables.")
    lines.append("- Required LP spec: `twfe_directional_dummies`, `driscoll_kraay`, `cumulative`.")
    lines.append("- THRANK reference: cumulative monetary-shock IRFs (`irf_mp_shock_cumulative.csv`).")
    lines.append(f"- Separate expansionary model shock file available: `{neg_available}`")
    lines.append("- Input fingerprints: `empirical_irf_provenance.json`")
    if wealth_model_series == "net_deposit":
        mapping_line = (
            "- Mapping: `lp_controls`/`lp_income` use PH2M->`cP`, WH2M->`cW`; "
            "`lp_wealth` uses PH2M->`wP`, WH2M->`wW`."
        )
    elif wealth_model_series == "wealth_measurement":
        mapping_line = (
            "- Mapping: `lp_controls`/`lp_income` use PH2M->`cP`, WH2M->`cW`; "
            "`lp_wealth` uses PH2M->`wP`, WH2M->`wW` from calibrated linear measurement equations."
        )
    else:
        mapping_line = "- Mapping: all datasets use PH2M->`cP`, WH2M->`cW`."
    lines.append(mapping_line)
    if neg_available:
        lines.append("- Expansionary terms use direct THRANK `e_R_neg` simulations (no sign inversion fallback).")
    else:
        lines.append("- Expansionary terms use sign inversion fallback because `irf_mp_neg_shock_cumulative.csv` is unavailable.")
    lines.append("")

    lines.append("## Data Schema Check")
    lines.append(f"- LP dataset path: `{schema_note['dataset_path']}`")
    lines.append(f"- Exists: `{schema_note['exists']}`")
    lines.append(f"- Has `mp_shock_di`: `{schema_note['has_mp_shock_di']}`")
    lines.append(f"- Has `mp_shock`: `{schema_note['has_mp_shock']}`")
    lines.append(f"- Number of columns: `{schema_note['n_columns']}`")
    lines.append("")

    lines.append("## Horizon Coverage")
    if horizon_coverage.empty:
        lines.append("- No overlap between LP and model horizons.")
    else:
        lines.append("|dataset|direction|lp_h_range|model_h_range|overlap_range|missing_lp_h_in_model|")
        lines.append("|---|---|---|---|---|---|")
        cov_small = (
            horizon_coverage[["dataset", "direction", "lp_h_min", "lp_h_max", "model_h_min", "model_h_max", "overlap_h_min", "overlap_h_max", "lp_horizons_missing_in_model"]]
            .drop_duplicates()
            .sort_values(["dataset", "direction"])
        )
        for _, r in cov_small.iterrows():
            lines.append(
                "|"
                + f"{r['dataset']}|{r['direction']}|{int(r['lp_h_min'])}-{int(r['lp_h_max'])}|"
                + f"{int(r['model_h_min'])}-{int(r['model_h_max'])}|{int(r['overlap_h_min'])}-{int(r['overlap_h_max'])}|"
                + f"{r['lp_horizons_missing_in_model'] or 'none'}|"
            )
    lines.append("")

    lines.append("## Calibration Snapshot Used")
    lines.append(f"- THRANK `mp_shock_size`: {_fmt(float(run_summary['mp_shock_size']), 6)}")
    lines.append(
        f"- `r_R`: {_fmt(float(calibration.get('r_R', np.nan)), 3)}, "
        f"`r_pi`: {_fmt(float(calibration.get('r_pi', np.nan)), 3)}, "
        f"`r_Y`: {_fmt(float(calibration.get('r_Y', np.nan)), 3)}"
    )
    lines.append(
        f"- `beta_R`: {_fmt(float(calibration.get('beta_R', np.nan)), 3)}, "
        f"`beta_W`: {_fmt(float(calibration.get('beta_W', np.nan)), 3)}, "
        f"`eta`: {_fmt(float(calibration.get('eta', np.nan)), 3)}"
    )
    lines.append("")

    lines.append("## Horizon Diagnostics (H0-H24)")
    lines.append(
        "|dataset|term|corr|sign_match_share|ci_hit_share|impact_lp_h0|impact_model_h0|h24_lp|h24_model|mean_abs_gap|"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    order_cols = ["dataset", "group", "direction"]
    for _, r in diagnostics.sort_values(order_cols).iterrows():
        term_lbl = f"{r['group']} {r['direction']}"
        lines.append(
            "|"
            + f"{r['dataset']}|{term_lbl}|{_fmt(r['corr_h0_h24'],3)}|{_fmt(r['sign_match_share_h0_h24'],3)}|"
            + f"{_fmt(r['ci_hit_share_h0_h24'],3)}|{_fmt(r['impact_h0_lp'],4)}|{_fmt(r['impact_h0_model'],4)}|"
            + f"{_fmt(r['h24_lp'],4)}|{_fmt(r['h24_model'],4)}|{_fmt(r['mean_abs_gap_h0_h24'],4)}|"
        )

    lines.append("")
    lines.append("## Differential (PH2M - WH2M) Summary")
    if differential.empty:
        lines.append("- No differential series generated.")
    else:
        for (dataset, direction), sub in differential[differential["horizon"] <= 24].groupby(
            ["dataset", "direction"]
        ):
            corr = _safe_corr(
                sub["lp_diff_ph_minus_wh"].to_numpy(),
                sub["model_diff_ph_minus_wh"].to_numpy(),
            )
            lines.append(
                f"- {dataset} ({direction}): corr={_fmt(corr,3)}, "
                f"mean_abs_gap={_fmt(float(np.mean(np.abs(sub['gap_diff_model_minus_lp']))),4)}"
            )

    lines.append("")
    lines.append("## Critical Interrogation")
    lines.append("- Expansionary and contractionary LP terms are estimated separately; THRANK now includes a separate expansionary shock (`e_R_neg`) but asymmetry is still low-dimensional (`chi_R_neg` scalar) relative to empirical shape differences.")
    lines.append("- Persistent low CI hit-share indicates structural mismatch in channels/persistence, not only shock scaling.")
    lines.append("- `lp_wealth` remains hardest to match because it is a proxy outcome (`asinh(net_liquid_proxy)`), and the current observable mapping is still reduced-form rather than a full balance-sheet block.")
    lines.append("")
    lines.append("## Recommended Upgrade Loop")
    lines.append("1. Replace reduced-form wealth observables (`wP`, `wW`) with richer structural balance-sheet blocks linked to deposits and debt by agent type.")
    lines.append("2. Add asymmetry in transmission if directional LP asymmetry is treated as a target moment.")
    lines.append("3. Use weighted calibration objective by LP uncertainty (SE/CI width) and horizon bands (H0-H3, H6-H24).")

    (output_dir / "THRANK_vs_empirical_lp_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    build_comparison(
        args.thrank_dir,
        args.output_dir,
        args.lp_dataset_path,
        args.wealth_model_series,
    )
    print(f"Wrote LP comparison outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
