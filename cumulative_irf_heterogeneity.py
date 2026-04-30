"""
Monthly state-level local projections with HtM interaction terms.

Specification (per horizon h):
    y_resp_h = β·shock + γ·(shock×PH2M) + δ·(shock×WH2M)
             + θ·PH2M + ρ·WH2M
             + λ₁·lag_log_y + λ₂·lag2_log_y + μ·lag_shock
             + α_i (state FE) + α_t (time FE) + ε

Outputs:
    results/datasets/state_monthly_covariates.csv
    results/tables/irf_state_level/irf_state_pooled_monthly.csv
    results/tables/irf_state_level/irf_state_by_state_monthly.csv
    results/tables/irf_state_level/irf_state_regional_monthly.csv
    results/plots/irf_state_level/*.png
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statspai as sp
import statsmodels.formula.api as smf
import warnings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UF_NAMES = {
    11: "Rondônia", 12: "Acre", 13: "Amazonas", 14: "Roraima",
    15: "Pará", 16: "Amapá", 17: "Tocantins",
    21: "Maranhão", 22: "Piauí", 23: "Ceará", 24: "Rio Grande do Norte",
    25: "Paraíba", 26: "Pernambuco", 27: "Alagoas", 28: "Sergipe", 29: "Bahia",
    31: "Minas Gerais", 32: "Espírito Santo", 33: "Rio de Janeiro", 35: "São Paulo",
    41: "Paraná", 42: "Santa Catarina", 43: "Rio Grande do Sul",
    50: "Mato Grosso do Sul", 51: "Mato Grosso", 52: "Goiás", 53: "Distrito Federal",
}

MACRO_REGIONS = {
    "North":       [11, 12, 13, 14, 15, 16, 17],
    "Northeast":   [21, 22, 23, 24, 25, 26, 27, 28, 29],
    "Southeast":   [31, 32, 33, 35],
    "South":       [41, 42, 43],
    "Center-West": [50, 51, 52, 53],
}

UF_TO_REGION = {uf: r for r, ufs in MACRO_REGIONS.items() for uf in ufs}

REGION_COLORS = {
    "North": "#1b9e77", "Northeast": "#d95f02", "Southeast": "#7570b3",
    "South": "#e7298a", "Center-West": "#66a61e",
}

COEF_COLORS = {"ricardian": "#2166ac", "ph2m_diff": "#d73027", "wh2m_diff": "#4dac26"}

TYPE_IRF_COLORS = {"Ricardian": "#2166ac", "PH2M": "#d73027", "WH2M": "#4dac26"}
TYPE_IRF_STYLES = {"Ricardian": "-",       "PH2M": "--",       "WH2M": "-."}

DATA_DIR    = Path("results/tables")
TABLE_DIR   = Path("results/tables/irf_state_level")
PLOT_DIR    = Path("results/plots/irf_state_level")
DATASET_DIR = Path("results/datasets")
HORIZONS    = range(25)

TERM_MAP = {
    "mp_shock":     "ricardian",
    "shock_x_ph2m": "ph2m_diff",
    "shock_x_wh2m": "wh2m_diff",
}


# ---------------------------------------------------------------------------
# Helper: convert raw (β, γ, δ) coefficients to consumption IRFs per type
# ---------------------------------------------------------------------------

def coefs_to_type_irfs(coef_df: pd.DataFrame, mean_ph2m: float, mean_wh2m: float) -> pd.DataFrame:
    """
    Predicted consumption IRF for each agent type at horizon h:
      Ricardian: β_h
      PH2M:      β_h + γ_h × mean_ph2m
      WH2M:      β_h + δ_h × mean_wh2m

    95% CIs via delta method, assuming Cov(β, γ) = Cov(β, δ) = 0 (conservative).
    """
    β = coef_df[coef_df["coefficient"] == "ricardian"].set_index("horizon")
    γ = coef_df[coef_df["coefficient"] == "ph2m_diff"].set_index("horizon")
    δ = coef_df[coef_df["coefficient"] == "wh2m_diff"].set_index("horizon")

    records = []
    for h in sorted(β.index):
        b = β.loc[h]

        records.append({
            "horizon": h, "agent_type": "Ricardian",
            "estimate": b["estimate"],
            "conf_low": b["conf_low"],
            "conf_high": b["conf_high"],
        })

        if h in γ.index:
            g = γ.loc[h]
            est = b["estimate"] + g["estimate"] * mean_ph2m
            se  = np.sqrt(b["std_error"]**2 + (mean_ph2m * g["std_error"])**2)
            records.append({
                "horizon": h, "agent_type": "PH2M",
                "estimate": est,
                "conf_low": est - 1.96 * se,
                "conf_high": est + 1.96 * se,
            })

        if h in δ.index:
            d = δ.loc[h]
            est = b["estimate"] + d["estimate"] * mean_wh2m
            se  = np.sqrt(b["std_error"]**2 + (mean_wh2m * d["std_error"])**2)
            records.append({
                "horizon": h, "agent_type": "WH2M",
                "estimate": est,
                "conf_low": est - 1.96 * se,
                "conf_high": est + 1.96 * se,
            })

    return pd.DataFrame(records)

# ---------------------------------------------------------------------------
# Step 1: interpolate quarterly HtM shares to monthly
# ---------------------------------------------------------------------------

def interpolate_htm_to_monthly(htm_path: Path) -> pd.DataFrame:
    htm = pd.read_csv(htm_path)
    htm["uf_code"] = htm["uf_code"].astype(int)
    htm["month_num"] = htm["quarter"].map({1: 2, 2: 5, 3: 8, 4: 11})

    target_idx = pd.date_range("2016-01-01", "2019-12-01", freq="MS")
    out_rows = []

    for uf, grp in htm.groupby("uf_code"):
        anchor_dates = pd.to_datetime(
            grp["year"].astype(str) + "-"
            + grp["month_num"].astype(str).str.zfill(2) + "-01"
        )
        grp = grp.set_index(anchor_dates).sort_index()
        share_cols = ["share_PH2M", "share_WH2M", "share_Ricardian"]
        for col in share_cols:
            grp[col] = pd.to_numeric(grp[col])

        combined_idx = grp.index.union(target_idx)
        interp = (
            grp[share_cols]
            .reindex(combined_idx)
            .interpolate(method="linear", limit_direction="both")
            .reindex(target_idx)
            .clip(0, 1)
        )
        row_sums = interp.sum(axis=1).replace(0, 1)
        interp = interp.div(row_sums, axis=0)

        interp["uf_code"] = uf
        interp["year"] = interp.index.year
        interp["month_num"] = interp.index.month
        out_rows.append(interp.reset_index(drop=True))

    return pd.concat(out_rows, ignore_index=True)


# ---------------------------------------------------------------------------
# Step 2: build enriched panel
# ---------------------------------------------------------------------------

def build_panel(panel_csv: Path, htm_monthly: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_csv(panel_csv)
    df["uf_code"] = df["uf_code"].astype(int)
    df = df.sort_values(["uf_code", "year", "month_num"]).reset_index(drop=True)

    df["log_y"] = np.log(df["consumption_index"])

    df["lag_log_y"]  = df.groupby("uf_code")["log_y"].shift(1)
    df["lag2_log_y"] = df.groupby("uf_code")["log_y"].shift(2)
    df["lag_shock"]  = df.groupby("uf_code")["mp_shock"].shift(1)

    df = df.merge(
        htm_monthly[["uf_code", "year", "month_num", "share_PH2M", "share_WH2M", "share_Ricardian"]],
        on=["uf_code", "year", "month_num"],
        how="left",
    )

    df["t_order"] = df["year"] * 12 + df["month_num"]
    df["uf_code_str"] = df["uf_code"].astype(str)
    df["t_order_str"] = df["t_order"].astype(str)
    df["region"] = df["uf_code"].map(UF_TO_REGION)

    df = df.dropna(subset=["lag_log_y", "lag2_log_y", "share_PH2M", "share_WH2M"]).reset_index(drop=True)

    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATASET_DIR / "state_monthly_covariates.csv", index=False)
    print(f"Panel: {len(df)} rows, {df['uf_code'].nunique()} states")
    return df


# ---------------------------------------------------------------------------
# Step 3: pooled LP with statspai feols
# ---------------------------------------------------------------------------

def lp_pooled(panel: pd.DataFrame, horizons=HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    # mp_shock is aggregate (same across states each month) so it is absorbed by
    # time FE. Use state FE only so the Ricardian β_shock is identified.
    fml = (
        "y_resp ~ mp_shock + shock_x_ph2m + shock_x_wh2m"
        " + share_PH2M + share_WH2M"
        " + lag_log_y + lag2_log_y + lag_shock"
        " | uf_code_str"
    )

    for h in horizons:
        dd = panel.copy()
        dd["y_resp"] = dd.groupby("uf_code")["log_y"].shift(-h) - dd["lag_log_y"]
        dd["shock_x_ph2m"] = dd["mp_shock"] * dd["share_PH2M"]
        dd["shock_x_wh2m"] = dd["mp_shock"] * dd["share_WH2M"]
        dd = dd.dropna(subset=["y_resp"])

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = sp.feols(fml, data=dd, vcov={"CRV1": "uf_code_str"})
            tidy = result.tidy()
            for orig, coef_name in TERM_MAP.items():
                row = tidy[tidy["term"] == orig]
                if row.empty:
                    continue
                r = row.iloc[0]
                records.append({
                    "horizon": h,
                    "coefficient": coef_name,
                    "estimate": r["estimate"],
                    "std_error": r["std_error"],
                    "conf_low": r["conf_low"],
                    "conf_high": r["conf_high"],
                })
        except Exception as e:
            print(f"  lp_pooled h={h}: {e}")

    coef_df = pd.DataFrame(records)
    coef_df.to_csv(TABLE_DIR / "irf_state_pooled_monthly.csv", index=False)

    mean_ph2m = panel["share_PH2M"].mean()
    mean_wh2m = panel["share_WH2M"].mean()
    type_df = coefs_to_type_irfs(coef_df, mean_ph2m, mean_wh2m)
    type_df.to_csv(TABLE_DIR / "irf_state_pooled_type_irfs.csv", index=False)

    print(f"Pooled IRF: {len(coef_df)} coef rows, {len(type_df)} type-IRF rows")
    return coef_df, type_df


# ---------------------------------------------------------------------------
# Step 4: by-state LP with statsmodels HAC
# ---------------------------------------------------------------------------

def lp_by_state(panel: pd.DataFrame, horizons=HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    fml = (
        "y_resp ~ mp_shock + shock_x_ph2m + shock_x_wh2m"
        " + share_PH2M + share_WH2M + lag_log_y + lag2_log_y + lag_shock"
    )

    # state-specific mean shares for evaluating type IRFs
    state_means = panel.groupby("uf_code")[["share_PH2M", "share_WH2M"]].mean()

    for uf in sorted(panel["uf_code"].unique()):
        state_df = panel[panel["uf_code"] == uf].copy()
        region = UF_TO_REGION.get(uf, "Unknown")

        for h in horizons:
            dd = state_df.copy()
            dd["y_resp"] = dd["log_y"].shift(-h) - dd["lag_log_y"]
            dd["shock_x_ph2m"] = dd["mp_shock"] * dd["share_PH2M"]
            dd["shock_x_wh2m"] = dd["mp_shock"] * dd["share_WH2M"]
            dd = dd.dropna(subset=["y_resp"])

            if len(dd) < 18:
                continue

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = smf.ols(fml, data=dd).fit(
                        cov_type="HAC",
                        cov_kwds={"maxlags": max(1, h)},
                    )
                for orig, coef_name in TERM_MAP.items():
                    if orig not in model.params:
                        continue
                    ci = model.conf_int().loc[orig]
                    records.append({
                        "uf_code": uf,
                        "region": region,
                        "horizon": h,
                        "coefficient": coef_name,
                        "estimate": model.params[orig],
                        "std_error": model.bse[orig],
                        "conf_low": ci[0],
                        "conf_high": ci[1],
                    })
            except Exception as e:
                print(f"  lp_by_state uf={uf} h={h}: {e}")

    coef_df = pd.DataFrame(records)
    coef_df.to_csv(TABLE_DIR / "irf_state_by_state_monthly.csv", index=False)

    # compute type IRFs per state using that state's mean shares
    type_rows = []
    for uf, grp in coef_df.groupby("uf_code"):
        region = grp["region"].iloc[0]
        s = state_means.loc[uf]
        t = coefs_to_type_irfs(grp, s["share_PH2M"], s["share_WH2M"])
        t["uf_code"] = uf
        t["region"] = region
        type_rows.append(t)

    type_df = pd.concat(type_rows, ignore_index=True) if type_rows else pd.DataFrame()
    type_df.to_csv(TABLE_DIR / "irf_state_by_state_type_irfs.csv", index=False)

    print(f"By-state IRF: {len(coef_df)} coef rows, {len(type_df)} type-IRF rows")
    return coef_df, type_df


# ---------------------------------------------------------------------------
# Step 5: regional LP with statspai feols
# ---------------------------------------------------------------------------

def lp_regional(panel: pd.DataFrame, horizons=HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    # Same aggregate-shock absorption issue as pooled: use state FE only.
    fml = (
        "y_resp ~ mp_shock + shock_x_ph2m + shock_x_wh2m"
        " + share_PH2M + share_WH2M"
        " + lag_log_y + lag2_log_y + lag_shock"
        " | uf_code_str"
    )

    region_means = panel.groupby("region")[["share_PH2M", "share_WH2M"]].mean()

    for region, ufs in MACRO_REGIONS.items():
        reg_df = panel[panel["uf_code"].isin(ufs)].copy()

        for h in horizons:
            dd = reg_df.copy()
            dd["y_resp"] = dd.groupby("uf_code")["log_y"].shift(-h) - dd["lag_log_y"]
            dd["shock_x_ph2m"] = dd["mp_shock"] * dd["share_PH2M"]
            dd["shock_x_wh2m"] = dd["mp_shock"] * dd["share_WH2M"]
            dd = dd.dropna(subset=["y_resp"])

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    result = sp.feols(fml, data=dd, vcov={"CRV1": "uf_code_str"})
                tidy = result.tidy()
                for orig, coef_name in TERM_MAP.items():
                    row = tidy[tidy["term"] == orig]
                    if row.empty:
                        continue
                    r = row.iloc[0]
                    records.append({
                        "region": region,
                        "horizon": h,
                        "coefficient": coef_name,
                        "estimate": r["estimate"],
                        "std_error": r["std_error"],
                        "conf_low": r["conf_low"],
                        "conf_high": r["conf_high"],
                    })
            except Exception as e:
                print(f"  lp_regional region={region} h={h}: {e}")

    coef_df = pd.DataFrame(records)
    coef_df.to_csv(TABLE_DIR / "irf_state_regional_monthly.csv", index=False)

    type_rows = []
    for region, grp in coef_df.groupby("region"):
        s = region_means.loc[region]
        t = coefs_to_type_irfs(grp, s["share_PH2M"], s["share_WH2M"])
        t["region"] = region
        type_rows.append(t)

    type_df = pd.concat(type_rows, ignore_index=True) if type_rows else pd.DataFrame()
    type_df.to_csv(TABLE_DIR / "irf_state_regional_type_irfs.csv", index=False)

    print(f"Regional IRF: {len(coef_df)} coef rows, {len(type_df)} type-IRF rows")
    return coef_df, type_df


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

def _irf_axes(ax, title=""):
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Horizon (months)", fontsize=9)
    ax.set_ylabel("Cumulative log response", fontsize=9)
    if title:
        ax.set_title(title, fontsize=9)


def _plot_type_irfs(ax, type_df: pd.DataFrame):
    for agent_type in ["Ricardian", "PH2M", "WH2M"]:
        sub = type_df[type_df["agent_type"] == agent_type].sort_values("horizon")
        if sub.empty:
            continue
        color = TYPE_IRF_COLORS[agent_type]
        ls = TYPE_IRF_STYLES[agent_type]
        ax.plot(sub["horizon"], sub["estimate"], color=color, linestyle=ls, label=agent_type)
        ax.fill_between(
            sub["horizon"], sub["conf_low"], sub["conf_high"],
            color=color, alpha=0.15,
        )


def plot_pooled_irf(type_df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(8, 5))
    _plot_type_irfs(ax, type_df)
    _irf_axes(ax)
    ax.set_title("Consumption IRF to DI Rate Surprise by Agent Type (Pooled)", fontsize=11)
    ax.legend(fontsize=9)
    fig.tight_layout()
    path = PLOT_DIR / "irf_state_pooled_monthly.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


def plot_state_irfs_by_region(type_df: pd.DataFrame):
    for region, ufs in MACRO_REGIONS.items():
        reg_data = type_df[type_df["uf_code"].isin(ufs)]
        n = len(ufs)
        ncols = min(3, n)
        nrows = (n + ncols - 1) // ncols
        fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), squeeze=False)

        for idx, uf in enumerate(sorted(ufs)):
            ax = axes[idx // ncols][idx % ncols]
            _plot_type_irfs(ax, reg_data[reg_data["uf_code"] == uf])
            _irf_axes(ax, title=f"{UF_NAMES.get(uf, str(uf))} ({uf})")
            ax.tick_params(labelsize=7)

        for idx in range(n, nrows * ncols):
            axes[idx // ncols][idx % ncols].set_visible(False)

        handles, labels = axes[0][0].get_legend_handles_labels()
        if handles:
            fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8,
                       bbox_to_anchor=(0.5, 0.01))

        fig.suptitle(
            f"Consumption IRF to DI Rate Surprise by Agent Type — {region} States",
            fontsize=12, y=1.01,
        )
        fig.tight_layout()
        safe_region = region.replace(" ", "_").replace("-", "_")
        path = PLOT_DIR / f"irf_states_{safe_region}.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved {path}")


def plot_regional_irf(type_df: pd.DataFrame):
    # One subplot per agent type, one line per region
    fig, axes = plt.subplots(1, 3, figsize=(15, 4), sharey=True)
    for ax, agent_type in zip(axes, ["Ricardian", "PH2M", "WH2M"]):
        for region in MACRO_REGIONS:
            sub = type_df[
                (type_df["region"] == region) & (type_df["agent_type"] == agent_type)
            ].sort_values("horizon")
            if sub.empty:
                continue
            color = REGION_COLORS[region]
            ax.plot(sub["horizon"], sub["estimate"], color=color, label=region)
            ax.fill_between(
                sub["horizon"], sub["conf_low"], sub["conf_high"],
                color=color, alpha=0.12,
            )
        _irf_axes(ax, title=f"{agent_type} Consumption IRF")
    axes[0].legend(fontsize=7)
    fig.suptitle("Consumption IRF to DI Rate Surprise — by Agent Type and Macro-Region", fontsize=11)
    fig.tight_layout()
    path = PLOT_DIR / "irf_regional_pooled_monthly.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Saved {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    print("Interpolating quarterly HtM shares to monthly...")
    htm_monthly = interpolate_htm_to_monthly(DATA_DIR / "state_quarter_htm_shares.csv")

    print("Building enriched panel...")
    panel = build_panel(DATA_DIR / "aggregate_state_monthly_shock_h2m.csv", htm_monthly)

    print("Running pooled LP (statspai feols)...")
    _, pooled_type_df = lp_pooled(panel)

    print("Running by-state LP (statsmodels HAC)...")
    _, state_type_df = lp_by_state(panel)

    print("Running regional LP (statspai feols)...")
    _, region_type_df = lp_regional(panel)

    print("Plotting...")
    plot_pooled_irf(pooled_type_df)
    plot_state_irfs_by_region(state_type_df)
    plot_regional_irf(region_type_df)

    print("Done.")


if __name__ == "__main__":
    main()
