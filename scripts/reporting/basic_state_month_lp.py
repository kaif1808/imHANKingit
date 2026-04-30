"""
Build a matched state-month panel and run basic fixed-effect local projections.

Default inputs:
    Data/state_data/monthly_state_consumption.csv
    results/tables/state_month_htm_shares.parquet
    results/diagnostics/shock_transformation_log.csv

Default outputs:
    results/datasets/basic_state_month_lp/state_month_lp_dataset.csv
    results/tables/basic_state_month_lp/irf.csv
    results/tables/basic_state_month_lp/state_irf.csv
    results/plots/basic_state_month_lp/cumulative_irf.png
    results/plots/basic_state_month_lp/marginal_irf.png
    results/plots/basic_state_month_lp/state_regions/*.png
    results/diagnostics/basic_state_month_lp/merge_summary.csv
    results/diagnostics/basic_state_month_lp/time_fe_diagnostics.csv
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

os.environ.setdefault("XDG_CACHE_HOME", str(Path("/tmp") / "xdg-cache"))
os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


DATE_COLUMN_RE = re.compile(r"^\d{4}\.(0[1-9]|1[0-2])$")
SHARE_COLS = ["share_PH2M", "share_WH2M", "share_Ricardian"]
MATCH_REQUIRED_COLS = ["consumption_index", "mp_shock", *SHARE_COLS]
RESPONSE_TYPES = ("cumulative", "marginal")
SHOCK_VARIABLE = "mp_shock"
SHOCK_TYPE = "Monthly monetary-policy shock from DI surprise"
SHOCK_DIRECTIONS = {
    "positive": {
        "multiplier": 1.0,
        "direction": "positive signed shock",
        "unit": "one-unit increase in mp_shock; negative shocks enter as negative values",
        "plot_label": "Positive MP Shock",
    },
    "negative": {
        "multiplier": -1.0,
        "direction": "negative signed shock",
        "unit": "one-unit decrease in mp_shock; source mp_shock values are sign-flipped for this reported IRF",
        "plot_label": "Negative MP Shock",
    },
}

UF_NAMES = {
    11: "Rondonia",
    12: "Acre",
    13: "Amazonas",
    14: "Roraima",
    15: "Para",
    16: "Amapa",
    17: "Tocantins",
    21: "Maranhao",
    22: "Piaui",
    23: "Ceara",
    24: "Rio Grande do Norte",
    25: "Paraiba",
    26: "Pernambuco",
    27: "Alagoas",
    28: "Sergipe",
    29: "Bahia",
    31: "Minas Gerais",
    32: "Espirito Santo",
    33: "Rio de Janeiro",
    35: "Sao Paulo",
    41: "Parana",
    42: "Santa Catarina",
    43: "Rio Grande do Sul",
    50: "Mato Grosso do Sul",
    51: "Mato Grosso",
    52: "Goias",
    53: "Distrito Federal",
}

MACRO_REGIONS = {
    "North": [11, 12, 13, 14, 15, 16, 17],
    "Northeast": [21, 22, 23, 24, 25, 26, 27, 28, 29],
    "Southeast": [31, 32, 33, 35],
    "South": [41, 42, 43],
    "Center-West": [50, 51, 52, 53],
}
UF_TO_REGION = {uf: region for region, ufs in MACRO_REGIONS.items() for uf in ufs}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build matched state-month LP data and estimate a basic MP shock IRF."
    )
    parser.add_argument(
        "--consumption-csv",
        default="Data/state_data/monthly_state_consumption.csv",
        type=Path,
    )
    parser.add_argument(
        "--htm-shares",
        default="results/tables/state_month_htm_shares.parquet",
        type=Path,
    )
    parser.add_argument(
        "--shock-log",
        default="results/diagnostics/shock_transformation_log.csv",
        type=Path,
    )
    parser.add_argument("--max-horizon", default=24, type=int)
    parser.add_argument(
        "--shock-direction",
        choices=sorted(SHOCK_DIRECTIONS),
        default="negative",
        help="Orient reported mp_shock IRFs to a positive or negative signed shock.",
    )
    parser.add_argument(
        "--dataset-out",
        default="results/datasets/basic_state_month_lp/state_month_lp_dataset.csv",
        type=Path,
    )
    parser.add_argument(
        "--irf-out",
        default="results/tables/basic_state_month_lp/irf.csv",
        type=Path,
    )
    parser.add_argument(
        "--state-irf-out",
        default="results/tables/basic_state_month_lp/state_irf.csv",
        type=Path,
    )
    parser.add_argument(
        "--plot-dir",
        default="results/plots/basic_state_month_lp",
        type=Path,
    )
    parser.add_argument(
        "--state-plot-dir",
        default="results/plots/basic_state_month_lp/state_regions",
        type=Path,
    )
    parser.add_argument(
        "--summary-out",
        default="results/diagnostics/basic_state_month_lp/merge_summary.csv",
        type=Path,
    )
    parser.add_argument(
        "--time-fe-diagnostics-out",
        default="results/diagnostics/basic_state_month_lp/time_fe_diagnostics.csv",
        type=Path,
    )
    return parser.parse_args()


def _date_range_label(df: pd.DataFrame) -> tuple[str | None, str | None]:
    if df.empty:
        return None, None
    dates = pd.to_datetime(df["date"])
    return dates.min().strftime("%Y-%m"), dates.max().strftime("%Y-%m")


def read_consumption(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(
        path,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
        skiprows=1,
    )
    month_cols = [col for col in raw.columns if DATE_COLUMN_RE.match(str(col))]
    if not month_cols:
        raise ValueError(f"No YYYY.MM consumption columns found in {path}")

    id_cols = [col for col in ["Sigla", "Código", "State"] if col in raw.columns]
    long = raw[id_cols + month_cols].melt(
        id_vars=id_cols,
        value_vars=month_cols,
        var_name="period",
        value_name="consumption_index",
    )
    long = long.rename(
        columns={"Sigla": "uf_abbrev", "Código": "uf_code", "State": "state"}
    )
    if "uf_code" not in long.columns:
        raise ValueError(f"{path} must contain a state code column named 'Código'")

    long["uf_code"] = pd.to_numeric(long["uf_code"], errors="coerce").astype("Int64")
    long["year"] = long["period"].str.slice(0, 4).astype(int)
    long["month"] = long["period"].str.slice(5, 7).astype(int)
    long["date"] = pd.to_datetime(
        {"year": long["year"], "month": long["month"], "day": 1}
    )
    long["consumption_index"] = pd.to_numeric(
        long["consumption_index"], errors="coerce"
    )
    long = long.dropna(subset=["uf_code"]).copy()
    long["uf_code"] = long["uf_code"].astype(int)
    return long[
        [
            "uf_code",
            "uf_abbrev",
            "state",
            "year",
            "month",
            "date",
            "consumption_index",
        ]
    ].sort_values(["uf_code", "year", "month"])


def read_htm_shares(path: Path) -> pd.DataFrame:
    htm = pd.read_parquet(path)
    required = ["uf_code", "year", "month", *SHARE_COLS]
    missing = [col for col in required if col not in htm.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")

    htm = htm[required].copy()
    htm["uf_code"] = htm["uf_code"].astype(int)
    htm["year"] = htm["year"].astype(int)
    htm["month"] = htm["month"].astype(int)
    for col in SHARE_COLS:
        htm[col] = pd.to_numeric(htm[col], errors="coerce")
    htm["date"] = pd.to_datetime({"year": htm["year"], "month": htm["month"], "day": 1})
    return htm.sort_values(["uf_code", "year", "month"])


def read_shocks(path: Path) -> pd.DataFrame:
    shocks = pd.read_csv(path)
    required = ["year", "month", "mp_shock_monthly"]
    missing = [col for col in required if col not in shocks.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")

    shocks = shocks.rename(columns={"mp_shock_monthly": "mp_shock"}).copy()
    shocks["year"] = shocks["year"].astype(int)
    shocks["month"] = shocks["month"].astype(int)
    shocks["mp_shock"] = pd.to_numeric(shocks["mp_shock"], errors="coerce")
    shocks["date"] = pd.to_datetime(
        {"year": shocks["year"], "month": shocks["month"], "day": 1}
    )
    return shocks[["year", "month", "date", "mp_shock"]].sort_values(["year", "month"])


def _summary_row(
    source: str,
    df: pd.DataFrame,
    row_count: int | None = None,
    dropped_from_previous: int | None = None,
    note: str = "",
) -> dict[str, object]:
    min_date, max_date = _date_range_label(df)
    n_states = int(df["uf_code"].nunique()) if "uf_code" in df.columns and not df.empty else np.nan
    return {
        "source": source,
        "row_count": len(df) if row_count is None else row_count,
        "min_date": min_date,
        "max_date": max_date,
        "n_states": n_states,
        "dropped_from_previous": dropped_from_previous,
        "note": note,
    }


def build_matched_panel(
    consumption: pd.DataFrame,
    htm: pd.DataFrame,
    shocks: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows = [
        _summary_row("consumption_long", consumption),
        _summary_row("htm_shares", htm),
        _summary_row("shocks", shocks),
    ]

    consumption_htm = consumption.merge(
        htm[["uf_code", "year", "month", *SHARE_COLS]],
        on=["uf_code", "year", "month"],
        how="inner",
        validate="one_to_one",
    )
    summary_rows.append(
        _summary_row(
            "consumption_htm_inner",
            consumption_htm,
            dropped_from_previous=len(consumption) - len(consumption_htm),
            note="Inner join on uf_code, year, month.",
        )
    )

    matched = consumption_htm.merge(
        shocks[["year", "month", "mp_shock"]],
        on=["year", "month"],
        how="inner",
        validate="many_to_one",
    )
    rows_before_required_drop = len(matched)
    matched = matched.dropna(subset=MATCH_REQUIRED_COLS).copy()
    matched["log_consumption"] = np.log(matched["consumption_index"])
    matched = matched.sort_values(["uf_code", "year", "month"]).reset_index(drop=True)
    matched["t_index"] = matched["year"] * 12 + matched["month"]
    for lag in [1, 2]:
        matched = _merge_log_at_offset(
            matched,
            matched,
            offset=-lag,
            column_name=f"lag{lag}_log_consumption",
        )
    matched["uf_code_str"] = matched["uf_code"].astype(str)
    matched["date_str"] = matched["date"].dt.strftime("%Y-%m")
    matched["state_name"] = matched["uf_code"].map(UF_NAMES).fillna(matched["state"])
    matched["macro_region"] = matched["uf_code"].map(UF_TO_REGION)

    summary_rows.append(
        _summary_row(
            "fully_matched",
            matched,
            dropped_from_previous=rows_before_required_drop - len(matched),
            note=(
                "Inner joined shocks on year, month, then dropped rows missing "
                "consumption, shock, or HtM shares."
            ),
        )
    )
    return matched, pd.DataFrame(summary_rows)


def _merge_log_at_offset(
    base: pd.DataFrame,
    lookup_source: pd.DataFrame,
    offset: int,
    column_name: str,
) -> pd.DataFrame:
    lookup = lookup_source[["uf_code", "t_index", "log_consumption"]].copy()
    lookup["t_index"] = lookup["t_index"] - offset
    lookup = lookup.rename(columns={"log_consumption": column_name})
    return base.merge(
        lookup,
        on=["uf_code", "t_index"],
        how="left",
        validate="one_to_one",
    )


def validate_panel(panel: pd.DataFrame, max_horizon: int | None = None) -> None:
    if panel.empty:
        raise ValueError("Matched LP panel is empty.")
    missing = panel[MATCH_REQUIRED_COLS].isna().sum()
    bad_missing = missing[missing > 0]
    if not bad_missing.empty:
        raise ValueError(f"Matched panel has missing required fields: {bad_missing.to_dict()}")
    if (panel["consumption_index"] <= 0).any():
        raise ValueError("Consumption index must be positive for log responses.")
    share_sums = panel[SHARE_COLS].sum(axis=1)
    if not np.allclose(share_sums, 1.0, atol=1e-6):
        max_gap = float(np.nanmax(np.abs(share_sums - 1.0)))
        raise ValueError(f"HtM shares do not sum to one within tolerance; max gap={max_gap}")
    if max_horizon is not None:
        min_months = panel.groupby("uf_code").size().min()
        if min_months < max_horizon + 3:
            raise ValueError(
                f"Panel is too short for horizon {max_horizon} with two lags; "
                f"shortest state has {min_months} months."
            )


def make_lp_frame(panel: pd.DataFrame, horizon: int, response_type: str) -> pd.DataFrame:
    if response_type not in RESPONSE_TYPES:
        raise ValueError(f"Unknown response_type={response_type}")

    out = panel.copy()
    out = _merge_log_at_offset(
        out,
        panel,
        offset=horizon,
        column_name="lead_log_consumption",
    )
    if response_type == "cumulative":
        out["y_resp"] = out["lead_log_consumption"] - out["lag1_log_consumption"]
    elif horizon == 0:
        out["y_resp"] = out["lead_log_consumption"] - out["lag1_log_consumption"]
    else:
        out = _merge_log_at_offset(
            out,
            panel,
            offset=horizon - 1,
            column_name="prev_horizon_log_consumption",
        )
        out["y_resp"] = out["lead_log_consumption"] - out["prev_horizon_log_consumption"]
    return out


def _fit_one_lp(reg_df: pd.DataFrame, formula: str):
    return smf.ols(formula=formula, data=reg_df).fit(
        cov_type="cluster",
        cov_kwds={"groups": reg_df["uf_code"], "use_correction": True},
    )


def _fit_one_state_lp(reg_df: pd.DataFrame, formula: str):
    return smf.ols(formula=formula, data=reg_df).fit(cov_type="HC1")


def _shock_metadata(shock_direction: str) -> dict[str, object]:
    if shock_direction not in SHOCK_DIRECTIONS:
        raise ValueError(f"Unknown shock_direction={shock_direction}")
    meta = SHOCK_DIRECTIONS[shock_direction]
    return {
        "shock_variable": SHOCK_VARIABLE,
        "shock_type": SHOCK_TYPE,
        "shock_direction": meta["direction"],
        "shock_unit": meta["unit"],
        "shock_multiplier": meta["multiplier"],
        "shock_plot_label": meta["plot_label"],
    }


def _spec_definitions(include_time_fe: bool) -> dict[str, dict[str, object]]:
    specs = {
        "lag1": {
            "formula": (
                "y_resp ~ mp_shock + share_PH2M + share_WH2M "
                "+ lag1_log_consumption + C(uf_code_str)"
            ),
            "required": [
                "y_resp",
                "mp_shock",
                "share_PH2M",
                "share_WH2M",
                "lag1_log_consumption",
                "uf_code_str",
                "uf_code",
            ],
            "with_time_fe": False,
        },
        "lag2": {
            "formula": (
                "y_resp ~ mp_shock + share_PH2M + share_WH2M "
                "+ lag1_log_consumption + lag2_log_consumption + C(uf_code_str)"
            ),
            "required": [
                "y_resp",
                "mp_shock",
                "share_PH2M",
                "share_WH2M",
                "lag1_log_consumption",
                "lag2_log_consumption",
                "uf_code_str",
                "uf_code",
            ],
            "with_time_fe": False,
        },
    }

    if include_time_fe:
        specs.update(
            {
                "lag1_time_fe": {
                    "formula": (
                        "y_resp ~ share_PH2M + share_WH2M + lag1_log_consumption "
                        "+ C(uf_code_str) + C(date_str)"
                    ),
                    "required": [
                        "y_resp",
                        "share_PH2M",
                        "share_WH2M",
                        "lag1_log_consumption",
                        "uf_code_str",
                        "date_str",
                        "uf_code",
                    ],
                    "with_time_fe": True,
                },
                "lag2_time_fe": {
                    "formula": (
                        "y_resp ~ share_PH2M + share_WH2M + lag1_log_consumption "
                        "+ lag2_log_consumption + C(uf_code_str) + C(date_str)"
                    ),
                    "required": [
                        "y_resp",
                        "share_PH2M",
                        "share_WH2M",
                        "lag1_log_consumption",
                        "lag2_log_consumption",
                        "uf_code_str",
                        "date_str",
                        "uf_code",
                    ],
                    "with_time_fe": True,
                },
            }
        )
    return specs


def _state_spec_definitions() -> dict[str, dict[str, object]]:
    return {
        "lag1": {
            "formula": (
                "y_resp ~ mp_shock + share_PH2M + share_WH2M "
                "+ lag1_log_consumption"
            ),
            "required": [
                "y_resp",
                "mp_shock",
                "share_PH2M",
                "share_WH2M",
                "lag1_log_consumption",
            ],
        },
        "lag2": {
            "formula": (
                "y_resp ~ mp_shock + share_PH2M + share_WH2M "
                "+ lag1_log_consumption + lag2_log_consumption"
            ),
            "required": [
                "y_resp",
                "mp_shock",
                "share_PH2M",
                "share_WH2M",
                "lag1_log_consumption",
                "lag2_log_consumption",
            ],
        },
    }


def run_local_projections(
    panel: pd.DataFrame,
    max_horizon: int,
    include_time_fe: bool = True,
    shock_direction: str = "negative",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    specs = _spec_definitions(include_time_fe=include_time_fe)
    shock_meta = _shock_metadata(shock_direction)
    shock_multiplier = float(shock_meta["shock_multiplier"])
    records: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for response_type in RESPONSE_TYPES:
        for horizon in range(max_horizon + 1):
            horizon_df = make_lp_frame(panel, horizon, response_type=response_type)
            for spec, spec_def in specs.items():
                reg_df = horizon_df.dropna(subset=spec_def["required"]).copy()
                if reg_df.empty:
                    raise ValueError(
                        f"No observations available for {spec}, {response_type}, "
                        f"horizon {horizon}"
                    )
                fit = _fit_one_lp(reg_df, str(spec_def["formula"]))
                with_time_fe = bool(spec_def["with_time_fe"])
                if with_time_fe:
                    diagnostics.append(
                        {
                            "response_type": response_type,
                            "horizon": horizon,
                            "spec": spec,
                            "n_obs": int(fit.nobs),
                            "n_states": int(reg_df["uf_code"].nunique()),
                            "n_months": int(reg_df["date_str"].nunique()),
                            "mp_shock_identified": False,
                            "note": (
                                "mp_shock is common across states within month and is "
                                "exactly absorbed by month fixed effects."
                            ),
                        }
                    )
                for term in ["mp_shock", "share_PH2M", "share_WH2M"]:
                    identified = not (with_time_fe and term == "mp_shock")
                    note = ""
                    if identified:
                        estimate = float(fit.params.get(term, np.nan))
                        std_error = float(fit.bse.get(term, np.nan))
                        if term == "mp_shock":
                            estimate *= shock_multiplier
                        conf_low = estimate - 1.96 * std_error
                        conf_high = estimate + 1.96 * std_error
                        if np.isnan(estimate):
                            identified = False
                            note = "Term not present in fitted model."
                    else:
                        estimate = np.nan
                        std_error = np.nan
                        conf_low = np.nan
                        conf_high = np.nan
                        note = (
                            "Not identified: common monthly shock is collinear with "
                            "month fixed effects."
                        )
                    records.append(
                        {
                            "response_type": response_type,
                            **shock_meta,
                            "spec": spec,
                            "with_time_fe": with_time_fe,
                            "horizon": horizon,
                            "term": term,
                            "estimate": estimate,
                            "std_error": std_error,
                            "conf_low": conf_low,
                            "conf_high": conf_high,
                            "n_obs": int(fit.nobs),
                            "n_states": int(reg_df["uf_code"].nunique()),
                            "identified": identified,
                            "note": note,
                        }
                    )

    irf = pd.DataFrame(records)
    expected = pd.MultiIndex.from_product(
        [RESPONSE_TYPES, specs.keys(), range(max_horizon + 1)],
        names=["response_type", "spec", "horizon"],
    )
    actual = pd.MultiIndex.from_frame(
        irf[["response_type", "spec", "horizon"]].drop_duplicates()
    )
    missing = expected.difference(actual)
    if len(missing):
        raise ValueError(f"LP output is missing spec/horizon combinations: {list(missing)}")
    return irf, pd.DataFrame(diagnostics)


def run_state_local_projections(
    panel: pd.DataFrame,
    max_horizon: int,
    response_types: tuple[str, ...] = ("cumulative",),
    shock_direction: str = "negative",
) -> pd.DataFrame:
    specs = _state_spec_definitions()
    shock_meta = _shock_metadata(shock_direction)
    shock_multiplier = float(shock_meta["shock_multiplier"])
    records: list[dict[str, object]] = []
    for response_type in response_types:
        if response_type not in RESPONSE_TYPES:
            raise ValueError(f"Unknown response_type={response_type}")
        for horizon in range(max_horizon + 1):
            horizon_df = make_lp_frame(panel, horizon, response_type=response_type)
            for spec, spec_def in specs.items():
                for uf_code, state_df in horizon_df.groupby("uf_code", sort=True):
                    reg_df = state_df.dropna(subset=spec_def["required"]).copy()
                    if reg_df.empty:
                        continue
                    fit = _fit_one_state_lp(reg_df, str(spec_def["formula"]))
                    estimate = float(fit.params.get("mp_shock", np.nan)) * shock_multiplier
                    std_error = float(fit.bse.get("mp_shock", np.nan))
                    state_name = str(reg_df["state_name"].iloc[0])
                    macro_region = str(reg_df["macro_region"].iloc[0])
                    records.append(
                        {
                            "response_type": response_type,
                            **shock_meta,
                            "spec": spec,
                            "uf_code": int(uf_code),
                            "state_name": state_name,
                            "macro_region": macro_region,
                            "horizon": horizon,
                            "term": "mp_shock",
                            "estimate": estimate,
                            "std_error": std_error,
                            "conf_low": estimate - 1.96 * std_error,
                            "conf_high": estimate + 1.96 * std_error,
                            "n_obs": int(fit.nobs),
                            "identified": not np.isnan(estimate),
                            "se_type": "HC1",
                        }
                    )

    state_irf = pd.DataFrame(records)
    if state_irf.empty:
        raise ValueError("State-level LP output is empty.")
    return state_irf


def plot_irf(irf: pd.DataFrame, response_type: str, path: Path) -> None:
    mp = irf.loc[
        irf["term"].eq("mp_shock")
        & irf["identified"]
        & irf["response_type"].eq(response_type)
    ].copy()
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {"lag1": "#1f77b4", "lag2": "#d62728"}
    for spec, spec_df in mp.groupby("spec"):
        spec_df = spec_df.sort_values("horizon")
        x = spec_df["horizon"].to_numpy(dtype=float)
        estimate = spec_df["estimate"].to_numpy(dtype=float)
        low = spec_df["conf_low"].to_numpy(dtype=float)
        high = spec_df["conf_high"].to_numpy(dtype=float)
        ax.plot(x, estimate, label=spec, color=colors.get(spec))
        ax.fill_between(x, low, high, color=colors.get(spec), alpha=0.15, linewidth=0)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Horizon (months)")
    ylabel = (
        "Cumulative log response"
        if response_type == "cumulative"
        else "Marginal monthly log response"
    )
    ax.set_ylabel(ylabel)
    shock_label = mp["shock_plot_label"].dropna().iloc[0] if not mp.empty else "MP Shock"
    ax.set_title(f"State-Month {response_type.title()} LP IRF to {shock_label}")
    ax.legend(title="Spec")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def plot_state_region_irfs(state_irf: pd.DataFrame, state_plot_dir: Path) -> list[Path]:
    paths: list[Path] = []
    state_plot_dir.mkdir(parents=True, exist_ok=True)
    for response_type in sorted(state_irf["response_type"].unique()):
        for spec in ["lag1", "lag2"]:
            subset = state_irf.loc[
                state_irf["response_type"].eq(response_type)
                & state_irf["spec"].eq(spec)
                & state_irf["identified"]
            ].copy()
            for region, region_df in subset.groupby("macro_region", sort=False):
                region_df = region_df.sort_values(["uf_code", "horizon"])
                states = list(region_df[["uf_code", "state_name"]].drop_duplicates().itertuples(index=False))
                n_states = len(states)
                n_cols = 3
                n_rows = int(np.ceil(n_states / n_cols))
                fig, axes = plt.subplots(
                    n_rows,
                    n_cols,
                    figsize=(4.2 * n_cols, 2.8 * n_rows),
                    sharex=True,
                    sharey=True,
                )
                axes_arr = np.atleast_1d(axes).ravel()
                for ax, state in zip(axes_arr, states):
                    state_df = region_df.loc[region_df["uf_code"].eq(state.uf_code)]
                    x = state_df["horizon"].to_numpy(dtype=float)
                    estimate = state_df["estimate"].to_numpy(dtype=float)
                    low = state_df["conf_low"].to_numpy(dtype=float)
                    high = state_df["conf_high"].to_numpy(dtype=float)
                    ax.plot(x, estimate, color="#1f77b4", linewidth=1.4)
                    ax.fill_between(x, low, high, color="#1f77b4", alpha=0.14, linewidth=0)
                    ax.axhline(0, color="black", linewidth=0.7)
                    ax.set_title(f"{state.state_name} ({state.uf_code})", fontsize=9)
                    ax.tick_params(labelsize=8)
                for ax in axes_arr[n_states:]:
                    ax.set_visible(False)
                ylabel = (
                    "Cumulative log response"
                    if response_type == "cumulative"
                    else "Marginal monthly log response"
                )
                fig.suptitle(
                    f"{region}: state-level {response_type} IRFs to "
                    f"{region_df['shock_plot_label'].iloc[0]} ({spec})",
                    fontsize=13,
                )
                fig.supxlabel("Horizon (months)", fontsize=10)
                fig.supylabel(ylabel, fontsize=10)
                fig.tight_layout(rect=[0, 0, 1, 0.95])
                path = state_plot_dir / f"{_slug(response_type)}_{_slug(spec)}_{_slug(region)}.png"
                fig.savefig(path, dpi=200)
                plt.close(fig)
                paths.append(path)
    return paths


def write_outputs(
    panel: pd.DataFrame,
    irf: pd.DataFrame,
    state_irf: pd.DataFrame,
    time_fe_diagnostics: pd.DataFrame,
    summary: pd.DataFrame,
    dataset_out: Path,
    irf_out: Path,
    state_irf_out: Path,
    plot_dir: Path,
    state_plot_dir: Path,
    summary_out: Path,
    time_fe_diagnostics_out: Path,
) -> list[Path]:
    for path in [dataset_out, irf_out, state_irf_out, summary_out, time_fe_diagnostics_out]:
        path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(dataset_out, index=False)
    irf.to_csv(irf_out, index=False)
    state_irf.to_csv(state_irf_out, index=False)
    summary.to_csv(summary_out, index=False)
    time_fe_diagnostics.to_csv(time_fe_diagnostics_out, index=False)
    plot_irf(irf, "cumulative", plot_dir / "cumulative_irf.png")
    plot_irf(irf, "marginal", plot_dir / "marginal_irf.png")
    return plot_state_region_irfs(state_irf, state_plot_dir)


def main() -> None:
    args = parse_args()
    consumption = read_consumption(args.consumption_csv)
    htm = read_htm_shares(args.htm_shares)
    shocks = read_shocks(args.shock_log)
    panel, summary = build_matched_panel(consumption, htm, shocks)
    validate_panel(panel, max_horizon=args.max_horizon)
    irf, time_fe_diagnostics = run_local_projections(
        panel,
        max_horizon=args.max_horizon,
        include_time_fe=True,
        shock_direction=args.shock_direction,
    )
    state_irf = run_state_local_projections(
        panel,
        max_horizon=args.max_horizon,
        shock_direction=args.shock_direction,
    )
    state_plot_paths = write_outputs(
        panel,
        irf,
        state_irf,
        time_fe_diagnostics,
        summary,
        args.dataset_out,
        args.irf_out,
        args.state_irf_out,
        args.plot_dir,
        args.state_plot_dir,
        args.summary_out,
        args.time_fe_diagnostics_out,
    )

    min_date, max_date = _date_range_label(panel)
    print(
        f"Matched LP panel: {len(panel):,} rows, {panel['uf_code'].nunique()} states, "
        f"{min_date} to {max_date}."
    )
    print(f"Wrote dataset: {args.dataset_out}")
    print(f"Wrote IRF table: {args.irf_out}")
    print(f"Wrote state IRF table: {args.state_irf_out}")
    print(f"Wrote plots: {args.plot_dir}")
    print(f"Wrote {len(state_plot_paths)} state-region panel plots: {args.state_plot_dir}")
    print(f"Wrote merge summary: {args.summary_out}")
    print(f"Wrote time-FE diagnostics: {args.time_fe_diagnostics_out}")


if __name__ == "__main__":
    main()
