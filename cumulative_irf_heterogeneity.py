from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Iterable
import math

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from statsmodels.stats.sandwich_covariance import cov_hac

try:
    from linearmodels.panel import PanelOLS
except Exception:  # pragma: no cover
    PanelOLS = None


BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "results"
TABLES_DIR = RESULTS_DIR / "tables"
PLOTS_DIR = RESULTS_DIR / "plots"
DIAG_DIR = RESULTS_DIR / "diagnostics"
DATASETS_DIR = RESULTS_DIR / "datasets"
REPORTS_DIR = RESULTS_DIR / "reports"

for p in [TABLES_DIR, PLOTS_DIR, DIAG_DIR, DATASETS_DIR, REPORTS_DIR]:
    p.mkdir(parents=True, exist_ok=True)

for p in [
    TABLES_DIR / "irf_state_level",
    TABLES_DIR / "irf_individual_monthly",
    TABLES_DIR / "irf_individual_quarterly",
    TABLES_DIR / "irf_group_tests",
    PLOTS_DIR / "irf_state_level",
    PLOTS_DIR / "irf_individual_monthly",
    PLOTS_DIR / "irf_individual_quarterly",
]:
    p.mkdir(parents=True, exist_ok=True)


STATE_REGION_MAP = {
    11: "North", 12: "North", 13: "North", 14: "North", 15: "North", 16: "North", 17: "North",
    21: "Northeast", 22: "Northeast", 23: "Northeast", 24: "Northeast", 25: "Northeast", 26: "Northeast", 27: "Northeast", 28: "Northeast", 29: "Northeast",
    31: "Southeast", 32: "Southeast", 33: "Southeast", 35: "Southeast",
    41: "South", 42: "South", 43: "South",
    50: "Center-West", 51: "Center-West", 52: "Center-West", 53: "Center-West",
}


@dataclass
class MergeLog:
    name: str
    left_rows: int
    right_rows: int
    merged_rows: int
    left_only: int
    right_only: int
    validate: str


def write_table(df: pd.DataFrame, rel_path: str) -> None:
    out = RESULTS_DIR / rel_path
    out.parent.mkdir(parents=True, exist_ok=True)

    if out.suffix == ".parquet":
        df_out = df.copy()
        for col in df_out.columns:
            if df_out[col].dtype == "object":
                types = {type(v) for v in df_out[col].dropna().head(200)}
                if len(types) > 1:
                    df_out[col] = df_out[col].astype(str)
        df_out.to_parquet(out, index=False)
    else:
        df.to_csv(out, index=False)


def read_state_consumption(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", skiprows=1, decimal=",", encoding="utf-8")
    drop_cols = [c for c in df.columns if str(c).startswith("Unnamed") or str(c).strip() == ""]
    df = df.drop(columns=drop_cols, errors="ignore")

    id_cols = ["Sigla", "Código", "State"]
    value_cols = [c for c in df.columns if c not in id_cols]
    long = df.melt(id_vars=id_cols, value_vars=value_cols, var_name="year_month", value_name="consumption_index")

    long = long.rename(columns={"Código": "uf_code", "State": "state_name", "Sigla": "uf"})
    long["uf_code"] = pd.to_numeric(long["uf_code"], errors="coerce").astype("Int64")
    long["consumption_index"] = pd.to_numeric(long["consumption_index"], errors="coerce")

    ym = long["year_month"].str.extract(r"(?P<year>\d{4})\.(?P<month>\d{2})")
    long["year"] = pd.to_numeric(ym["year"], errors="coerce").astype("Int64")
    long["month"] = pd.to_numeric(ym["month"], errors="coerce").astype("Int64")
    long["date"] = pd.to_datetime(dict(year=long["year"], month=long["month"], day=1), errors="coerce")
    long["quarter"] = ((long["month"] - 1) // 3 + 1).astype("Int64")

    long = long[(long["year"] >= 2015) & (long["year"] <= 2020)]
    long = long.dropna(subset=["uf_code", "year", "month", "consumption_index"])
    return long


def read_shocks(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = pd.read_csv(path)
    date_col = s.columns[0]
    s = s.rename(columns={date_col: "raw_date", "DISurprise": "di_surprise"})
    s["raw_date"] = pd.to_datetime(s["raw_date"], errors="coerce")
    s = s.dropna(subset=["raw_date"])
    s["year"] = s["raw_date"].dt.year
    s["month"] = s["raw_date"].dt.month
    s["quarter"] = ((s["month"] - 1) // 3 + 1).astype(int)
    s["mp_shock_monthly"] = pd.to_numeric(s["di_surprise"], errors="coerce")

    q = (
        s.groupby(["year", "quarter"], as_index=False)
        .agg(mp_shock_quarterly=("mp_shock_monthly", "sum"), n_months=("mp_shock_monthly", "size"))
    )

    write_table(
        s[["raw_date", "year", "month", "quarter", "di_surprise", "mp_shock_monthly"]],
        "diagnostics/shock_transformation_log.csv",
    )
    return s, q


def merge_with_logging(
    left: pd.DataFrame,
    right: pd.DataFrame,
    on: list[str],
    how: str,
    validate: str,
    name: str,
) -> tuple[pd.DataFrame, MergeLog, pd.DataFrame]:
    merged = left.merge(right, on=on, how=how, validate=validate, indicator=True)
    merge_log = MergeLog(
        name=name,
        left_rows=len(left),
        right_rows=len(right),
        merged_rows=len(merged),
        left_only=int((merged["_merge"] == "left_only").sum()),
        right_only=int((merged["_merge"] == "right_only").sum()),
        validate=validate,
    )
    drops = merged.loc[merged["_merge"] != "both", on + ["_merge"]].copy()
    merged = merged.loc[merged["_merge"] != "right_only"].drop(columns=["_merge"])
    return merged, merge_log, drops


def build_schema_audit(paths: dict[str, Path]) -> None:
    rows = []
    for name, path in paths.items():
        if not path.exists():
            rows.append({"dataset": name, "exists": False, "n_cols": np.nan, "columns": ""})
            continue
        if path.suffix == ".csv":
            if name == "state_consumption":
                sample = pd.read_csv(path, sep=";", skiprows=1, nrows=3)
            else:
                sample = pd.read_csv(path, nrows=3)
            rows.append({"dataset": name, "exists": True, "n_cols": len(sample.columns), "columns": "|".join(sample.columns)})
        elif path.suffix == ".parquet":
            import pyarrow.parquet as pq
            schema = pq.read_schema(path)
            cols = schema.names
            rows.append({"dataset": name, "exists": True, "n_cols": len(cols), "columns": "|".join(cols)})
        else:
            rows.append({"dataset": name, "exists": True, "n_cols": np.nan, "columns": ""})

    write_table(pd.DataFrame(rows), "diagnostics/input_schema_audit.csv")


def build_state_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    state_consumption = read_state_consumption(BASE_DIR / "Data/state_data/state_consumption_2015_2020.csv")
    htm = pd.read_csv(BASE_DIR / "results/tables/state_quarter_htm_shares.csv")
    htm["uf_code"] = pd.to_numeric(htm["uf_code"], errors="coerce").astype("Int64")
    htm["year"] = pd.to_numeric(htm["year"], errors="coerce").astype("Int64")
    htm["quarter"] = pd.to_numeric(htm["quarter"], errors="coerce").astype("Int64")

    monthly_shocks, quarterly_shocks = read_shocks(BASE_DIR / "monetary_shocks.csv")

    merge_logs: list[MergeLog] = []
    drop_logs: list[pd.DataFrame] = []

    state_monthly = state_consumption.merge(
        monthly_shocks[["year", "month", "quarter", "mp_shock_monthly"]],
        on=["year", "month", "quarter"],
        how="left",
        validate="m:1",
    )

    monthly_cov = state_monthly.merge(
        htm,
        on=["uf_code", "year", "quarter"],
        how="left",
        validate="m:1",
        indicator=True,
    )
    drop_logs.append(
        monthly_cov.loc[monthly_cov["_merge"] != "both", ["uf_code", "year", "month", "quarter", "_merge"]].assign(step="state_monthly_htm")
    )
    monthly_cov = monthly_cov.drop(columns=["_merge"])

    state_quarterly = (
        state_consumption.groupby(["uf_code", "uf", "state_name", "year", "quarter"], as_index=False)
        .agg(consumption_index=("consumption_index", "mean"))
    )

    x, log1, drop1 = merge_with_logging(
        state_quarterly,
        htm,
        on=["uf_code", "year", "quarter"],
        how="left",
        validate="1:1",
        name="state_quarterly_plus_htm",
    )
    merge_logs.append(log1)
    drop_logs.append(drop1.assign(step=log1.name))

    y, log2, drop2 = merge_with_logging(
        x,
        quarterly_shocks[["year", "quarter", "mp_shock_quarterly"]],
        on=["year", "quarter"],
        how="left",
        validate="m:1",
        name="state_quarterly_plus_shock",
    )
    merge_logs.append(log2)
    drop_logs.append(drop2.assign(step=log2.name))

    y = y[(y["year"] >= 2015) & (y["year"] <= 2020)].copy()
    y["macro_region"] = y["uf_code"].map(STATE_REGION_MAP)
    y["t_index"] = y["year"].astype(str) + "Q" + y["quarter"].astype(str)
    y["t_order"] = y["year"] * 4 + y["quarter"]

    write_table(monthly_cov, "datasets/state_monthly_covariates.csv")
    write_table(y, "datasets/state_quarter_panel_2015_2020.csv")
    write_table(pd.DataFrame([m.__dict__ for m in merge_logs]), "diagnostics/key_cardinality_checks.csv")
    if drop_logs:
        write_table(pd.concat(drop_logs, ignore_index=True), "diagnostics/merge_drops_state.csv")

    coverage = y.groupby(["year", "quarter"], as_index=False).agg(n_states=("uf_code", "nunique"))
    write_table(coverage, "diagnostics/state_quarter_coverage.csv")
    return y, monthly_cov


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def lp_state_level(state_panel: pd.DataFrame, horizons: Iterable[int] = range(21)) -> tuple[pd.DataFrame, pd.DataFrame]:
    outcomes = ["consumption_index"]
    all_results = []
    all_state_results = []

    for outcome in outcomes:
        d = state_panel.copy().sort_values(["uf_code", "t_order"])
        d["log_y"] = np.log(d[outcome])
        d["lag_log_y"] = d.groupby("uf_code")["log_y"].shift(1)
        d["lag_shock"] = d.groupby("uf_code")["mp_shock_quarterly"].shift(1)
        shock_sd = float(d["mp_shock_quarterly"].std(skipna=True))

        for h in horizons:
            dd = d.copy()
            dd["y_resp"] = dd.groupby("uf_code")["log_y"].shift(-h) - dd["lag_log_y"]
            dd = dd.dropna(
                subset=["y_resp", "mp_shock_quarterly", "share_PH2M", "share_WH2M", "lag_log_y", "lag_shock", "uf_code", "t_order"]
            )

            if len(dd) < 60:
                continue

            if PanelOLS is not None:
                panel = dd.set_index(["uf_code", "t_order"]).sort_index()
                exog = panel[["mp_shock_quarterly", "share_PH2M", "share_WH2M", "lag_log_y", "lag_shock"]]
                mod = PanelOLS(panel["y_resp"], exog, entity_effects=True, time_effects=True)
                fit = mod.fit(cov_type="driscoll-kraay")
                beta = float(fit.params.get("mp_shock_quarterly", np.nan))
                se = float(fit.std_errors.get("mp_shock_quarterly", np.nan))
                inference = "driscoll-kraay"
            else:
                dd_reg = dd.copy()
                dd_reg["uf_code_cat"] = dd_reg["uf_code"].astype("int64").astype(str)
                dd_reg["t_order_cat"] = dd_reg["t_order"].astype("int64").astype(str)
                reg = smf.ols(
                    "y_resp ~ mp_shock_quarterly + share_PH2M + share_WH2M + lag_log_y + lag_shock + C(uf_code_cat) + C(t_order_cat)",
                    data=dd_reg,
                ).fit(cov_type="cluster", cov_kwds={"groups": dd_reg["uf_code_cat"]})
                beta = float(reg.params.get("mp_shock_quarterly", np.nan))
                se = float(reg.bse.get("mp_shock_quarterly", np.nan))
                inference = "cluster_uf_fallback"

            lo = beta - 1.96 * se
            hi = beta + 1.96 * se
            z = abs(beta / se) if pd.notna(se) and se > 0 else np.nan
            pval = 2 * (1 - norm_cdf(z)) if pd.notna(z) else np.nan

            all_results.append(
                {
                    "level": "state",
                    "frequency": "quarterly",
                    "group": "all_states",
                    "outcome": outcome,
                    "horizon": int(h),
                    "n_obs": int(len(dd)),
                    "estimate": beta,
                    "std_error": se,
                    "ci_low": lo,
                    "ci_high": hi,
                    "p_value": pval,
                    "shock_sd": shock_sd,
                    "irf_pos_1sd": beta * shock_sd,
                    "irf_neg_1sd": -beta * shock_sd,
                    "ci_low_pos_1sd": lo * shock_sd,
                    "ci_high_pos_1sd": hi * shock_sd,
                    "inference": inference,
                    "model_id": f"state_pooled_{outcome}",
                }
            )

            for uf_code, ds in dd.groupby("uf_code"):
                if len(ds) < 12:
                    continue
                try:
                    m = smf.ols(
                        "y_resp ~ mp_shock_quarterly + share_PH2M + share_WH2M + lag_log_y + lag_shock",
                        data=ds,
                    ).fit()
                    cov = cov_hac(m, nlags=max(1, h))
                    idx = list(m.params.index).index("mp_shock_quarterly")
                    b = float(m.params.iloc[idx])
                    s = float(np.sqrt(cov[idx, idx]))
                    z_s = abs(b / s) if s > 0 else np.nan
                    p_s = 2 * (1 - norm_cdf(z_s)) if pd.notna(z_s) else np.nan
                    all_state_results.append(
                        {
                            "level": "state",
                            "frequency": "quarterly",
                            "group": int(uf_code),
                            "outcome": outcome,
                            "horizon": int(h),
                            "n_obs": int(len(ds)),
                            "estimate": b,
                            "std_error": s,
                            "ci_low": b - 1.96 * s,
                            "ci_high": b + 1.96 * s,
                            "p_value": p_s,
                            "shock_sd": shock_sd,
                            "irf_pos_1sd": b * shock_sd,
                            "irf_neg_1sd": -b * shock_sd,
                            "inference": "newey-west",
                            "model_id": f"state_{int(uf_code)}_{outcome}",
                        }
                    )
                except Exception:
                    continue

    pooled_df = pd.DataFrame(all_results)
    by_state_df = pd.DataFrame(all_state_results)
    write_table(pooled_df, "tables/irf_state_level/irf_state_pooled_quarterly.csv")
    write_table(by_state_df, "tables/irf_state_level/irf_state_by_state_quarterly.csv")
    return pooled_df, by_state_df


def build_heterogeneity_summary(by_state_df: pd.DataFrame, state_panel: pd.DataFrame) -> pd.DataFrame:
    if by_state_df.empty:
        out = pd.DataFrame(columns=["group", "peak_h", "peak_abs_response", "n_significant_horizons"])
        write_table(out, "tables/irf_state_level/heterogeneity_summary.csv")
        return out

    sig = by_state_df.assign(sig=lambda x: (x["ci_low"] > 0) | (x["ci_high"] < 0))
    peak_idx = sig.groupby("group")["estimate"].apply(lambda s: s.abs().idxmax())
    peaks = sig.loc[peak_idx].copy()
    counts = sig.groupby("group", as_index=False)["sig"].sum().rename(columns={"sig": "n_significant_horizons"})

    out = peaks[["group", "horizon", "estimate", "irf_pos_1sd"]].rename(
        columns={"horizon": "peak_h", "estimate": "peak_response", "irf_pos_1sd": "peak_response_1sd"}
    )
    out = out.merge(counts, on="group", how="left")

    reg = state_panel[["uf_code", "macro_region"]].drop_duplicates().rename(columns={"uf_code": "group"})
    out = out.merge(reg, on="group", how="left")

    region_summary = (
        out.groupby("macro_region", as_index=False)
        .agg(
            mean_peak_response=("peak_response", "mean"),
            mean_peak_h=("peak_h", "mean"),
            mean_n_significant_horizons=("n_significant_horizons", "mean"),
        )
    )

    write_table(out, "tables/irf_state_level/heterogeneity_summary.csv")
    write_table(region_summary, "tables/irf_state_level/heterogeneity_summary_regions.csv")
    return out


def plot_state_irfs(pooled_df: pd.DataFrame, by_state_df: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    if not pooled_df.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        d = pooled_df.sort_values("horizon")
        ax.plot(d["horizon"], d["estimate"], color="#1f77b4")
        ax.fill_between(d["horizon"], d["ci_low"], d["ci_high"], color="#1f77b4", alpha=0.2)
        ax.axhline(0, color="gray", linestyle="--", linewidth=1)
        ax.set_title("State-level pooled cumulative IRF")
        ax.set_xlabel("Horizon (quarters)")
        ax.set_ylabel("Cumulative log response")
        fig.tight_layout()
        fig.savefig(PLOTS_DIR / "irf_state_level/irf_state_pooled_quarterly.png", dpi=200)
        plt.close(fig)

    for uf_code, d in by_state_df.groupby("group"):
        d = d.sort_values("horizon")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(d["horizon"], d["estimate"], color="#2a9d8f")
        ax.fill_between(d["horizon"], d["ci_low"], d["ci_high"], color="#2a9d8f", alpha=0.2)
        ax.axhline(0, color="gray", linestyle="--", linewidth=1)
        ax.set_title(f"UF {int(uf_code)} cumulative IRF")
        ax.set_xlabel("Horizon (quarters)")
        ax.set_ylabel("Cumulative log response")
        fig.tight_layout()
        fig.savefig(PLOTS_DIR / f"irf_state_level/irf_state_{int(uf_code)}.png", dpi=180)
        plt.close(fig)


def individual_part_gate(monthly_cov: pd.DataFrame) -> dict:
    import pyarrow.parquet as pq

    ind_path = BASE_DIR / "results/tables/individual_agent_types.parquet"
    schema = pq.read_schema(ind_path)
    cols = schema.names

    required_any_consumption = [
        "consumption",
        "consumption_index",
        "consumption_real",
        "individual_consumption",
        "c",
        "y_cons",
    ]
    consumption_col = next((c for c in required_any_consumption if c in cols), None)
    has_month = "month" in cols

    gate = {
        "individual_file": str(ind_path),
        "has_consumption_column": consumption_col is not None,
        "consumption_column": consumption_col,
        "has_month_key": has_month,
        "has_quarter_key": "quarter" in cols,
        "has_state_key": "uf_code" in cols,
        "has_type_key": "agent_type" in cols,
        "status": "pass" if (consumption_col is not None and has_month) else "fail",
    }

    if gate["status"] == "fail":
        lines = [
            "# Individual IRF data requirements",
            "",
            "Part 2 was not executed because required fields are missing in results/tables/individual_agent_types.parquet.",
            "",
            "## Required keys",
            "- `uf_code` (state)",
            "- `year`, `month` for monthly analysis and quarterly aggregation",
            "- `agent_type` in {PH2M, WH2M, Ricardian}",
            "",
            "## Required outcome",
            "- one individual consumption variable (e.g., `consumption_real`)",
            "",
            "## Detected schema summary",
            f"- has_state_key: {gate['has_state_key']}",
            f"- has_quarter_key: {gate['has_quarter_key']}",
            f"- has_month_key: {gate['has_month_key']}",
            f"- has_type_key: {gate['has_type_key']}",
            f"- has_consumption_column: {gate['has_consumption_column']}",
            "",
            "## Next step",
            "Provide individual consumption at monthly (preferred) or at least quarterly frequency in a mergeable file keyed by `id_ind`/`uf_code` and time.",
        ]
        (DIAG_DIR / "individual_data_requirements.md").write_text("\n".join(lines), encoding="utf-8")

    write_table(pd.DataFrame([gate]), "diagnostics/individual_gate_status.csv")
    return gate


def write_model_spec() -> None:
    spec = {
        "state_level": {
            "outcome_transform": "log(consumption_index)",
            "response": "log(y_{t+h}) - log(y_{t-1})",
            "horizons_quarterly": list(range(0, 21)),
            "controls": ["share_PH2M", "share_WH2M", "lag_log_y", "lag_shock"],
            "fixed_effects": ["state", "time"],
            "inference_primary": "driscoll-kraay (PanelOLS) or clustered fallback",
            "state_specific_inference": "newey-west HAC",
            "shock_scaling": "±1 sd of quarterly shock",
        },
        "shock_aggregation": {
            "monthly_from": "DISurprise",
            "quarterly_rule": "sum(monthly shocks in quarter)",
        },
        "part2": {
            "status": "gated by availability of individual consumption and month key",
            "clustered_se": ["individual", "state"],
        },
    }
    (DIAG_DIR / "model_specifications.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")


def build_master_results() -> None:
    parts = []
    for p in [
        TABLES_DIR / "irf_state_level/irf_state_pooled_quarterly.csv",
        TABLES_DIR / "irf_state_level/irf_state_by_state_quarterly.csv",
        TABLES_DIR / "irf_individual_monthly/irf_individual_monthly.csv",
        TABLES_DIR / "irf_individual_quarterly/irf_individual_quarterly.csv",
    ]:
        if p.exists():
            parts.append(pd.read_csv(p))
    master = pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
    write_table(master, "tables/irf_master_results.parquet")


def write_synthesis_stub(gate: dict) -> None:
    status_txt = "Part 2 executed." if gate.get("status") == "pass" else "Part 2 not executed due to missing individual consumption/month keys."
    lines = [
        "---",
        "title: \"IRF heterogeneity synthesis\"",
        "format: html",
        "---",
        "",
        "## Scope",
        "This report compares cumulative IRFs across state and individual levels, frequencies, and agent types.",
        "",
        "## Execution status",
        f"- {status_txt}",
        "- State-level quarterly IRFs were estimated for horizons 0 to 20.",
        "",
        "## Output files",
        "- `results/tables/irf_state_level/*`",
        "- `results/plots/irf_state_level/*`",
        "- `results/tables/irf_master_results.parquet`",
        "- `results/diagnostics/*`",
    ]
    (REPORTS_DIR / "irf_heterogeneity_synthesis.qmd").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    paths = {
        "state_consumption": BASE_DIR / "Data/state_data/state_consumption_2015_2020.csv",
        "state_quarter_htm_shares": BASE_DIR / "results/tables/state_quarter_htm_shares.csv",
        "monetary_shocks": BASE_DIR / "monetary_shocks.csv",
        "individual_agent_types": BASE_DIR / "results/tables/individual_agent_types.parquet",
    }
    build_schema_audit(paths)
    write_model_spec()

    state_panel, monthly_cov = build_state_panels()
    pooled_df, by_state_df = lp_state_level(state_panel, horizons=range(21))
    build_heterogeneity_summary(by_state_df, state_panel)
    plot_state_irfs(pooled_df, by_state_df)

    gate = individual_part_gate(monthly_cov)
    build_master_results()
    write_synthesis_stub(gate)


if __name__ == "__main__":
    main()
