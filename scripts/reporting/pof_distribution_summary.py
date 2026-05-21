#!/usr/bin/env python3
"""
Summarize POF household income and wealth distributions by agent type.

Outputs:
    results/tables/pof_distribution_summary_stats.csv
    results/plots/pof_income_distribution_boxplots.png
    results/plots/pof_wealth_distribution_boxplots.png
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
os.environ.setdefault("XDG_CACHE_HOME", str(PROJECT_ROOT / ".tmp-xdg-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".tmp-mpl-cache"))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from scripts.reporting.htm_classification import (
    AGENT_TYPES,
    H2M_NET_WORTH_SPLIT_QUANTILE,
    ORDERING_FALLBACK_MIN_HOUSEHOLDS,
    PENSION_MULT,
    POVERTY_LINE,
    SAVINGS_FRAC,
    SELIC_RATE,
    ALPHA_SMOOTH,
    classify_agent,
    classify_agent_classical,
    build_pof_household_frame,
)

warnings.filterwarnings("ignore")
RESULTS_DIR = PROJECT_ROOT / "results"
TABLES_DIR = RESULTS_DIR / "tables"
PLOTS_DIR = RESULTS_DIR / "plots"

OUT_TABLE = TABLES_DIR / "pof_distribution_summary_stats.csv"
OUT_MATCHED_TABLE = TABLES_DIR / "pof_distribution_summary_matched_summary.csv"
OUT_INCOME_PLOT = PLOTS_DIR / "pof_income_distribution_boxplots.png"
OUT_WEALTH_PLOT = PLOTS_DIR / "pof_wealth_distribution_boxplots.png"
BIN_COMPARE_TABLE = TABLES_DIR / "pof_group_wealth_income_summary_bin_units_compare.csv"

WEIGHT_COL = "PESO_FINAL"


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    values = pd.to_numeric(values, errors="coerce")
    weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    valid = values.notna() & weights.gt(0)
    if not valid.any():
        return np.nan
    return float(np.average(values.loc[valid], weights=weights.loc[valid]))


def weighted_quantile(values: pd.Series, weights: pd.Series, q: float) -> float:
    values = pd.to_numeric(values, errors="coerce")
    weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    valid = values.notna() & weights.gt(0)
    if not valid.any():
        return np.nan
    x = values.loc[valid].to_numpy()
    w = weights.loc[valid].to_numpy()
    order = np.argsort(x)
    x = x[order]
    w = w[order]
    cum = np.cumsum(w) / w.sum()
    idx = np.searchsorted(cum, q, side="left")
    idx = min(idx, len(x) - 1)
    return float(x[idx])


def weighted_std(values: pd.Series, weights: pd.Series) -> float:
    mu = weighted_mean(values, weights)
    values = pd.to_numeric(values, errors="coerce")
    weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    valid = values.notna() & weights.gt(0)
    if not valid.any() or not np.isfinite(mu):
        return np.nan
    x = values.loc[valid].to_numpy()
    w = weights.loc[valid].to_numpy()
    var = np.average((x - mu) ** 2, weights=w)
    return float(np.sqrt(var))


def format_brl(x: float, _pos: int | None = None) -> str:
    if not np.isfinite(x):
        return ""
    if x >= 1_000_000:
        return f"{x/1_000_000:.1f}M"
    if x >= 1_000:
        return f"{x/1_000:.1f}k"
    return f"{x:.0f}"


def classify_households() -> pd.DataFrame:
    hh = build_pof_household_frame()
    pof = hh.rename(columns={"hh_residents": "_hh_residents"}).copy()

    pof["monthly_income"] = pof["total_labor_income"] + pof["total_transfers"]
    pof["financial_income_annual"] = pof["financial_income"] * 12
    pof["fin_liquid"] = pof["financial_income_annual"] / SELIC_RATE
    pof["pen_liquid"] = pof["pension_income"] * PENSION_MULT
    pof["income_surplus"] = (pof["RENDA_TOTAL"] - pof["monthly_income"] * 12).clip(lower=0)
    pof["sav_liquid"] = pof["income_surplus"] * SAVINGS_FRAC
    pof.loc[pof["govt_transfers"] > 0, "sav_liquid"] = 0
    pof["liquid_assets"] = pof["fin_liquid"] + pof["pen_liquid"] + pof["sav_liquid"]
    pof["illiquid_assets"] = pof["real_estate_annual"] + pof["vehicle_value"].fillna(0)
    denom = pof["monthly_income"].where(pof["monthly_income"] > 0)
    pof["liquid_ratio"] = (pof["liquid_assets"] / denom).clip(upper=50.0)
    pof["illiquid_ratio"] = (pof["illiquid_assets"] / denom).clip(upper=20.0)
    pof["net_worth"] = pof["liquid_assets"] + pof["illiquid_assets"]

    invalid = (
        (pof["monthly_income"] <= 0)
        | pof["liquid_ratio"].isna()
        | pof["illiquid_ratio"].isna()
    )
    pof = pof.loc[~invalid].copy()

    weights = pd.to_numeric(pof[WEIGHT_COL], errors="coerce").fillna(0.0)
    pof["agent_type"] = pof.apply(classify_agent, axis=1)

    ph_mask = pof["agent_type"] == "PH2M"
    wh_mask = pof["agent_type"] == "WH2M"
    ph_income_mean = weighted_mean(pof.loc[ph_mask, "monthly_income"], weights.loc[ph_mask])
    wh_income_mean = weighted_mean(pof.loc[wh_mask, "monthly_income"], weights.loc[wh_mask])
    h2m_mask = pof["liquid_ratio"] <= 0.50
    fallback_cutoff = weighted_quantile(
        pof.loc[h2m_mask, "net_worth"],
        weights.loc[h2m_mask],
        q=H2M_NET_WORTH_SPLIT_QUANTILE,
    )
    if (
        len(pof) >= ORDERING_FALLBACK_MIN_HOUSEHOLDS
        and np.isfinite(ph_income_mean)
        and np.isfinite(wh_income_mean)
        and wh_income_mean <= ph_income_mean
    ):
        pof["agent_type"] = pof.apply(
            lambda r: classify_agent_classical(r, fallback_cutoff),
            axis=1,
        )

    return pof


def load_matched_summary() -> pd.DataFrame:
    if not BIN_COMPARE_TABLE.exists():
        raise FileNotFoundError(
            f"Matched summary table not found: {BIN_COMPARE_TABLE}. "
            "Run htm_classification.py first."
        )

    matched = pd.read_csv(BIN_COMPARE_TABLE)
    matched = matched.loc[matched["classification"] == "baseline"].copy()
    matched["mean_net_worth"] = matched["mean_liquid_assets"] + matched["mean_illiquid_assets"]
    matched = matched[
        [
            "agent_type",
            "mean_monthly_income",
            "mean_pc_income",
            "mean_liquid_assets",
            "mean_illiquid_assets",
            "mean_net_worth",
        ]
    ]
    return matched.sort_values("agent_type").reset_index(drop=True)


def summarize_distribution(pof: pd.DataFrame, metric: str) -> pd.DataFrame:
    rows: list[dict[str, float | str | int]] = []
    for agent_type in AGENT_TYPES:
        group = pof.loc[pof["agent_type"] == agent_type].copy()
        weights = pd.to_numeric(group[WEIGHT_COL], errors="coerce").fillna(0.0)
        values = pd.to_numeric(group[metric], errors="coerce")
        rows.append(
            {
                "agent_type": agent_type,
                "metric": metric,
                "n_obs": int(len(group)),
                "weighted_n": float(weights.sum()),
                "weighted_mean": weighted_mean(values, weights),
                "weighted_std": weighted_std(values, weights),
                "weighted_p10": weighted_quantile(values, weights, 0.10),
                "weighted_p25": weighted_quantile(values, weights, 0.25),
                "weighted_p50": weighted_quantile(values, weights, 0.50),
                "weighted_p75": weighted_quantile(values, weights, 0.75),
                "weighted_p90": weighted_quantile(values, weights, 0.90),
            }
        )
    return pd.DataFrame(rows)


def make_boxplot(
    pof: pd.DataFrame,
    metrics: list[str],
    title: str,
    subtitle: str,
    out_path: Path,
    overlay_summary: pd.DataFrame | None = None,
) -> None:
    colors = {"PH2M": "#d73027", "WH2M": "#4dac26", "Ricardian": "#2166ac"}
    cap_quantile = {
        "monthly_income": 0.995,
        "pc_income": 0.995,
        "liquid_assets": 0.95,
        "illiquid_assets": 0.995,
        "net_worth": 0.95,
    }
    fig, axes = plt.subplots(1, len(metrics), figsize=(6.0 * len(metrics), 6.0), sharey=False)
    if len(metrics) == 1:
        axes = [axes]

    for ax, metric in zip(axes, metrics):
        data = [
            pd.to_numeric(pof.loc[pof["agent_type"] == agent_type, metric], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
            .clip(lower=0)
            for agent_type in AGENT_TYPES
        ]
        box = ax.boxplot(
            data,
            labels=AGENT_TYPES,
            patch_artist=True,
            showfliers=False,
            widths=0.6,
        )
        for patch, agent_type in zip(box["boxes"], AGENT_TYPES):
            patch.set_facecolor(colors[agent_type])
            patch.set_alpha(0.35)
            patch.set_edgecolor(colors[agent_type])
            patch.set_linewidth(1.3)
        for key in ("whiskers", "caps", "medians"):
            for artist in box[key]:
                artist.set_color("#333333")
                artist.set_linewidth(1.0)

        if overlay_summary is not None:
            if metric == "monthly_income":
                summary_col = "mean_monthly_income"
            elif metric == "pc_income":
                summary_col = "mean_pc_income"
            elif metric == "liquid_assets":
                summary_col = "mean_liquid_assets"
            elif metric == "illiquid_assets":
                summary_col = "mean_illiquid_assets"
            elif metric == "net_worth":
                summary_col = "mean_net_worth"
            else:
                summary_col = None
            if summary_col is not None and summary_col in overlay_summary.columns:
                overlay_map = overlay_summary.set_index("agent_type")[summary_col].to_dict()
                for xpos, agent_type in enumerate(AGENT_TYPES, start=1):
                    if agent_type in overlay_map and np.isfinite(overlay_map[agent_type]):
                        ax.scatter(
                            xpos,
                            float(overlay_map[agent_type]),
                            marker="D",
                            s=52,
                            color=colors[agent_type],
                            edgecolor="black",
                            linewidth=0.7,
                            zorder=3,
                        )

        q = cap_quantile.get(metric, 0.995)
        upper = np.nanquantile(np.concatenate([series.to_numpy() for series in data]), q)
        if np.isfinite(upper) and upper > 0:
            ax.set_ylim(0, upper * 1.05)

        ax.set_title(metric.replace("_", " ").title(), fontsize=12, weight="bold")
        ax.set_xlabel("")
        ax.set_ylabel("BRL")
        ax.grid(True, axis="y", alpha=0.22, linewidth=0.6)

    fig.suptitle(title, fontsize=15, weight="bold", y=0.98)
    fig.text(0.5, 0.94, subtitle, ha="center", va="top", fontsize=10, color="#444444")
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    pof = classify_households()
    matched = load_matched_summary()

    summary_frames = []
    for metric in ["monthly_income", "pc_income", "liquid_assets", "illiquid_assets", "net_worth"]:
        summary_frames.append(summarize_distribution(pof, metric))
    summary = pd.concat(summary_frames, ignore_index=True)
    summary = summary[
        [
            "agent_type",
            "metric",
            "n_obs",
            "weighted_n",
            "weighted_mean",
            "weighted_std",
            "weighted_p10",
            "weighted_p25",
            "weighted_p50",
            "weighted_p75",
            "weighted_p90",
        ]
    ]
    summary = summary.sort_values(["metric", "agent_type"]).reset_index(drop=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_TABLE, index=False)
    matched.to_csv(OUT_MATCHED_TABLE, index=False)

    make_boxplot(
        pof,
        metrics=["monthly_income", "pc_income"],
        title="POF Income Distributions by Agent Type",
        subtitle="Household-level POF distributions after exclusion of nonpositive-income or invalid-ratio households; linear scale with upper-tail cap for readability",
        out_path=OUT_INCOME_PLOT,
        overlay_summary=matched,
    )
    make_boxplot(
        pof,
        metrics=["liquid_assets", "illiquid_assets", "net_worth"],
        title="POF Wealth Distributions by Agent Type",
        subtitle="Household-level POF wealth components and net worth; linear scale with upper-tail cap for readability",
        out_path=OUT_WEALTH_PLOT,
        overlay_summary=matched,
    )

    print("Saved:")
    print(f"  {OUT_TABLE}")
    print(f"  {OUT_MATCHED_TABLE}")
    print(f"  {OUT_INCOME_PLOT}")
    print(f"  {OUT_WEALTH_PLOT}")
    print("\nSummary preview:")
    print(summary.head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
