"""
Build a matched state-month panel and run basic fixed-effect local projections.

Default inputs:
    Data/state_data/monthly_state_consumption.csv
    results/tables/state_month_htm_shares.parquet
    results/tables/state_month_labour_market.parquet
    results/diagnostics/shock_transformation_log.csv

Default outputs:
    results/datasets/basic_state_month_lp/state_month_lp_dataset.csv
    results/tables/basic_state_month_lp/irf.csv
    results/tables/basic_state_month_lp/aggregate_irf.csv
    results/tables/basic_state_month_lp/state_irf.csv
    results/plots/basic_state_month_lp/cumulative_irf.png
    results/plots/basic_state_month_lp/marginal_irf.png
    results/plots/basic_state_month_lp/aggregate_cumulative_irf.png
    results/plots/basic_state_month_lp/aggregate_marginal_irf.png
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
LABOUR_COLS = [
    "unemployment_rate",
    "labour_force_participation_rate",
    "formal_share",
    "informal_share",
    "conta_propria_share",
    "population",
]
MATCH_REQUIRED_COLS = ["consumption_index", "mp_shock", *SHARE_COLS]
RESPONSE_TYPES = ("cumulative", "marginal")
SHOCK_VARIABLE = "mp_shock"
SHOCK_TYPE = "Monthly monetary-policy shock from DI surprise"
INTERACTION_TERMS = ["mp_shock_x_share_PH2M", "mp_shock_x_share_WH2M"]
AGGREGATE_TERM = "aggregate_response_at_mean_composition"
PREFERRED_SPECS = ["lag1_time_fe", "lag2_time_fe"]
DEFAULT_PLOT_SHARE_DELTA = 0.10
SHOCK_DIRECTIONS = {
    "contractionary_rate_surprise": {
        "multiplier": 1.0,
        "direction": "contractionary_rate_surprise",
        "unit": "one-unit positive DI/rate surprise; positive mp_shock is contractionary",
        "plot_label": "Contractionary Rate Surprise",
    },
    "expansionary_rate_surprise": {
        "multiplier": -1.0,
        "direction": "expansionary_rate_surprise",
        "unit": "one-unit negative DI/rate surprise; source mp_shock values are sign-flipped for this reported IRF",
        "plot_label": "Expansionary Rate Surprise",
    },
}
SHOCK_DIRECTION_ALIASES = {
    "positive": "contractionary_rate_surprise",
    "negative": "expansionary_rate_surprise",
}
SHOCK_DIRECTION_CHOICES = sorted(
    {*SHOCK_DIRECTIONS.keys(), *SHOCK_DIRECTION_ALIASES.keys(), "both"}
)

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
        "--labour-market",
        default="results/tables/state_month_labour_market.parquet",
        type=Path,
    )
    parser.add_argument(
        "--shock-log",
        default="results/diagnostics/shock_transformation_log.csv",
        type=Path,
    )
    parser.add_argument("--max-horizon", default=48, type=int)
    parser.add_argument(
        "--shock-direction",
        choices=SHOCK_DIRECTION_CHOICES,
        default="both",
        help=(
            "Orient reported mp_shock IRFs. Use contractionary_rate_surprise for "
            "positive DI/rate surprises, expansionary_rate_surprise for negative "
            "DI/rate surprises, or both. Legacy aliases positive/negative are accepted."
        ),
    )
    parser.add_argument(
        "--plot-share-delta",
        default=DEFAULT_PLOT_SHARE_DELTA,
        type=float,
        help=(
            "Household-share contrast used to scale plotted exposure IRFs. "
            "Default 0.10 plots the response to a 10 percentage point higher "
            "PH2M/WH2M share."
        ),
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
        "--aggregate-irf-out",
        default="results/tables/basic_state_month_lp/aggregate_irf.csv",
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
    # Prefer an existing date column; otherwise build from year/month if available.
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"])
    elif {"year", "month"}.issubset(df.columns):
        dates = pd.to_datetime(
            {"year": df["year"].astype(int), "month": df["month"].astype(int), "day": 1}
        )
    else:
        return None, None
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


def read_labour_market(path: Path) -> pd.DataFrame:
    labour = pd.read_parquet(path)
    required = ["uf_code", "year", "month", *LABOUR_COLS]
    missing = [col for col in required if col not in labour.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")

    labour = labour[required].copy()
    # Convert numeric columns safely (keep NA where present)
    labour["uf_code"] = pd.to_numeric(labour["uf_code"], errors="coerce")
    labour["year"] = pd.to_numeric(labour["year"], errors="coerce")
    labour["month"] = pd.to_numeric(labour["month"], errors="coerce")
    for col in LABOUR_COLS:
        labour[col] = pd.to_numeric(labour[col], errors="coerce")

    # Build a proper date column safely even when year/month contain NA
    def _make_date(row):
        y = row["year"]
        m = row["month"]
        if pd.isna(y) or pd.isna(m):
            return pd.NaT
        try:
            return pd.Timestamp(int(y), int(m), 1)
        except Exception:
            return pd.NaT

    labour["date"] = labour.apply(_make_date, axis=1)

    # Use pandas nullable integer dtype for keys
    labour["uf_code"] = labour["uf_code"].astype("Int64")
    labour["year"] = labour["year"].astype("Int64")
    labour["month"] = labour["month"].astype("Int64")

    return labour.sort_values(["uf_code", "year", "month"])


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
    labour: pd.DataFrame,
    shocks: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if shocks is None:
        shocks = labour
        labour = consumption[["uf_code", "year", "month"]].drop_duplicates().copy()
        for col in LABOUR_COLS:
            labour[col] = np.nan

    summary_rows = [
        _summary_row("consumption_long", consumption),
        _summary_row("htm_shares", htm),
        _summary_row("labour_market", labour),
        _summary_row("shocks", shocks),
    ]

    consumption_htm = consumption.merge(
        htm[["uf_code", "year", "month", *SHARE_COLS]],
        on=["uf_code", "year", "month"],
        how="inner",
        validate="one_to_one",
    )
    consumption_htm = consumption_htm.merge(
        labour[["uf_code", "year", "month", *LABOUR_COLS]],
        on=["uf_code", "year", "month"],
        how="left",
        validate="one_to_one",
    )
    summary_rows.append(
        _summary_row(
            "consumption_htm_labour_left",
            consumption_htm,
            dropped_from_previous=len(consumption) - len(consumption_htm),
            note="Inner join HtM shares, then left join labour-market metrics on uf_code, year, month.",
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
    for col in SHARE_COLS:
        matched[f"lag1_{col}"] = matched.groupby("uf_code", sort=False)[col].shift(1)
    matched["mp_shock_x_share_PH2M"] = matched["mp_shock"] * matched["lag1_share_PH2M"]
    matched["mp_shock_x_share_WH2M"] = matched["mp_shock"] * matched["lag1_share_WH2M"]
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


def _canonical_shock_direction(shock_direction: str) -> str:
    return SHOCK_DIRECTION_ALIASES.get(shock_direction, shock_direction)


def _selected_shock_directions(shock_direction: str) -> list[str]:
    if shock_direction == "both":
        return list(SHOCK_DIRECTIONS)
    canonical = _canonical_shock_direction(shock_direction)
    if canonical not in SHOCK_DIRECTIONS:
        raise ValueError(f"Unknown shock_direction={shock_direction}")
    return [canonical]


def _shock_metadata(shock_direction: str) -> dict[str, object]:
    canonical = _canonical_shock_direction(shock_direction)
    if canonical not in SHOCK_DIRECTIONS:
        raise ValueError(f"Unknown shock_direction={shock_direction}")
    meta = SHOCK_DIRECTIONS[canonical]
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
                "y_resp ~ mp_shock + mp_shock_x_share_PH2M + mp_shock_x_share_WH2M "
                "+ lag1_share_PH2M + lag1_share_WH2M "
                "+ lag1_log_consumption + C(uf_code_str)"
            ),
            "required": [
                "y_resp",
                "mp_shock",
                "mp_shock_x_share_PH2M",
                "mp_shock_x_share_WH2M",
                "lag1_share_PH2M",
                "lag1_share_WH2M",
                "lag1_log_consumption",
                "uf_code_str",
                "uf_code",
            ],
            "reported_terms": ["mp_shock", *INTERACTION_TERMS],
            "with_time_fe": False,
        },
        "lag2": {
            "formula": (
                "y_resp ~ mp_shock + mp_shock_x_share_PH2M + mp_shock_x_share_WH2M "
                "+ lag1_share_PH2M + lag1_share_WH2M "
                "+ lag1_log_consumption + lag2_log_consumption + C(uf_code_str)"
            ),
            "required": [
                "y_resp",
                "mp_shock",
                "mp_shock_x_share_PH2M",
                "mp_shock_x_share_WH2M",
                "lag1_share_PH2M",
                "lag1_share_WH2M",
                "lag1_log_consumption",
                "lag2_log_consumption",
                "uf_code_str",
                "uf_code",
            ],
            "reported_terms": ["mp_shock", *INTERACTION_TERMS],
            "with_time_fe": False,
        },
    }

    if include_time_fe:
        specs.update(
            {
                "lag1_time_fe": {
                    "formula": (
                        "y_resp ~ mp_shock_x_share_PH2M + mp_shock_x_share_WH2M "
                        "+ lag1_share_PH2M + lag1_share_WH2M + lag1_log_consumption "
                        "+ C(uf_code_str) + C(date_str)"
                    ),
                    "required": [
                        "y_resp",
                        "mp_shock_x_share_PH2M",
                        "mp_shock_x_share_WH2M",
                        "lag1_share_PH2M",
                        "lag1_share_WH2M",
                        "lag1_log_consumption",
                        "uf_code_str",
                        "date_str",
                        "uf_code",
                    ],
                    "reported_terms": INTERACTION_TERMS,
                    "with_time_fe": True,
                },
                "lag2_time_fe": {
                    "formula": (
                        "y_resp ~ mp_shock_x_share_PH2M + mp_shock_x_share_WH2M "
                        "+ lag1_share_PH2M + lag1_share_WH2M + lag1_log_consumption "
                        "+ lag2_log_consumption + C(uf_code_str) + C(date_str)"
                    ),
                    "required": [
                        "y_resp",
                        "mp_shock_x_share_PH2M",
                        "mp_shock_x_share_WH2M",
                        "lag1_share_PH2M",
                        "lag1_share_WH2M",
                        "lag1_log_consumption",
                        "lag2_log_consumption",
                        "uf_code_str",
                        "date_str",
                        "uf_code",
                    ],
                    "reported_terms": INTERACTION_TERMS,
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


def _term_metadata(term: str, with_time_fe: bool) -> dict[str, object]:
    if term == "mp_shock":
        return {
            "term_label": "Ricardian-baseline shock level effect",
            "term_role": "baseline_level_effect",
            "household_exposure": "Ricardian_baseline",
            "baseline_household_type": "Ricardian",
            "term_note": (
                "No Ricardian interaction is included; in non-time-FE specs, mp_shock "
                "is the omitted Ricardian-share baseline level effect."
            ),
        }
    if term == "mp_shock_x_share_PH2M":
        return {
            "term_label": "Shock x lagged PH2M share exposure",
            "term_role": "household_share_interaction",
            "household_exposure": "PH2M",
            "baseline_household_type": "Ricardian",
            "term_note": (
                "Interaction of mp_shock with lagged PH2M state share; Ricardian "
                "share interaction is the omitted baseline."
            ),
        }
    if term == "mp_shock_x_share_WH2M":
        return {
            "term_label": "Shock x lagged WH2M share exposure",
            "term_role": "household_share_interaction",
            "household_exposure": "WH2M",
            "baseline_household_type": "Ricardian",
            "term_note": (
                "Interaction of mp_shock with lagged WH2M state share; Ricardian "
                "share interaction is the omitted baseline."
            ),
        }
    if term == AGGREGATE_TERM:
        return {
            "term_label": "Aggregate response at mean household composition",
            "term_role": "aggregate_total_irf",
            "household_exposure": "sample_mean_composition",
            "baseline_household_type": "Ricardian",
            "term_note": (
                "Linear combination of mp_shock plus PH2M/WH2M shock-share "
                "interactions evaluated at the horizon-specific sample mean "
                "lagged household shares. This aggregate level effect is not "
                "identified in month-FE specifications."
            ),
        }
    return {
        "term_label": term,
        "term_role": "other",
        "household_exposure": "",
        "baseline_household_type": "Ricardian" if with_time_fe else "",
        "term_note": "",
    }


def _plus_months(dates: pd.Series, months: int) -> pd.Series:
    return dates + pd.offsets.DateOffset(months=months)


def _identification_diagnostic(
    reg_df: pd.DataFrame,
    fit,
    response_type: str,
    horizon: int,
    spec: str,
    with_time_fe: bool,
) -> dict[str, object]:
    nonzero = reg_df.loc[reg_df["mp_shock"].abs().gt(1e-12)].copy()
    if nonzero.empty:
        identifying_dates: list[str] = []
        identifying_rows = nonzero
    else:
        month_variation = (
            nonzero.groupby("date_str")
            .agg(
                ph2m_unique=("lag1_share_PH2M", "nunique"),
                wh2m_unique=("lag1_share_WH2M", "nunique"),
            )
            .reset_index()
        )
        identifying_dates = month_variation.loc[
            month_variation["ph2m_unique"].gt(1)
            | month_variation["wh2m_unique"].gt(1),
            "date_str",
        ].tolist()
        identifying_rows = nonzero.loc[nonzero["date_str"].isin(identifying_dates)].copy()

    outcome_dates = _plus_months(reg_df["date"], horizon)
    identifying_outcome_dates = (
        _plus_months(identifying_rows["date"], horizon)
        if not identifying_rows.empty
        else pd.Series(dtype="datetime64[ns]")
    )
    includes_2020_outcomes = bool(
        not identifying_outcome_dates.empty
        and identifying_outcome_dates.dt.year.ge(2020).any()
    )
    average_shock_note = (
        "Average mp_shock level effect is absorbed by month fixed effects; "
        "mp_shock x lagged household-share interactions remain identified from "
        "cross-state exposure variation."
        if with_time_fe
        else (
            "No month fixed effects; mp_shock is reported as the omitted "
            "Ricardian-share baseline level effect alongside share interactions."
        )
    )
    return {
        "response_type": response_type,
        "horizon": horizon,
        "spec": spec,
        "n_obs": int(fit.nobs),
        "n_states": int(reg_df["uf_code"].nunique()),
        "n_months": int(reg_df["date_str"].nunique()),
        "sample_min_date": reg_df["date"].min().strftime("%Y-%m"),
        "sample_max_date": reg_df["date"].max().strftime("%Y-%m"),
        "outcome_min_date": outcome_dates.min().strftime("%Y-%m"),
        "outcome_max_date": outcome_dates.max().strftime("%Y-%m"),
        "nonzero_shock_months": int(nonzero["date_str"].nunique()),
        "identifying_nonzero_shock_months": len(identifying_dates),
        "identifying_nonzero_shock_dates": ";".join(identifying_dates),
        "includes_2020_outcomes": includes_2020_outcomes,
        "with_time_fe": with_time_fe,
        "mp_shock_level_identified": not with_time_fe,
        "interaction_terms_identified": len(identifying_dates) > 0,
        "note": average_shock_note,
    }


def _linear_combo(fit, weights: dict[str, float]) -> tuple[float, float]:
    params = fit.params
    if any(term not in params.index for term in weights):
        return np.nan, np.nan

    estimate = float(sum(weight * params[term] for term, weight in weights.items()))
    cov = fit.cov_params()
    variance = 0.0
    for left, left_weight in weights.items():
        for right, right_weight in weights.items():
            variance += left_weight * right_weight * float(cov.loc[left, right])
    std_error = float(np.sqrt(max(variance, 0.0)))
    return estimate, std_error


def _mean_composition_weights(reg_df: pd.DataFrame) -> dict[str, float]:
    return {
        "mp_shock": 1.0,
        "mp_shock_x_share_PH2M": float(reg_df["lag1_share_PH2M"].mean()),
        "mp_shock_x_share_WH2M": float(reg_df["lag1_share_WH2M"].mean()),
    }


def run_local_projections(
    panel: pd.DataFrame,
    max_horizon: int,
    include_time_fe: bool = True,
    shock_direction: str = "both",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    specs = _spec_definitions(include_time_fe=include_time_fe)
    shock_metas = [_shock_metadata(direction) for direction in _selected_shock_directions(shock_direction)]
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
                diagnostics.append(
                    _identification_diagnostic(
                        reg_df,
                        fit,
                        response_type=response_type,
                        horizon=horizon,
                        spec=spec,
                        with_time_fe=with_time_fe,
                    )
                )
                for term in spec_def["reported_terms"]:
                    raw_estimate = float(fit.params.get(term, np.nan))
                    std_error = float(fit.bse.get(term, np.nan))
                    identified = not np.isnan(raw_estimate)
                    note = "" if identified else "Term not present in fitted model."
                    for shock_meta in shock_metas:
                        shock_multiplier = float(shock_meta["shock_multiplier"])
                        estimate = raw_estimate * shock_multiplier if identified else np.nan
                        conf_low = estimate - 1.96 * std_error if identified else np.nan
                        conf_high = estimate + 1.96 * std_error if identified else np.nan
                        records.append(
                            {
                                "response_type": response_type,
                                **shock_meta,
                                "spec": spec,
                                "with_time_fe": with_time_fe,
                                "horizon": horizon,
                                "term": term,
                                **_term_metadata(term, with_time_fe=with_time_fe),
                                "estimate": estimate,
                                "std_error": std_error if identified else np.nan,
                                "conf_low": conf_low,
                                "conf_high": conf_high,
                                "n_obs": int(fit.nobs),
                                "n_states": int(reg_df["uf_code"].nunique()),
                                "identified": identified,
                                "note": note,
                            }
                        )
                if not with_time_fe:
                    weights = _mean_composition_weights(reg_df)
                    raw_estimate, std_error = _linear_combo(fit, weights)
                    identified = not np.isnan(raw_estimate)
                    for shock_meta in shock_metas:
                        shock_multiplier = float(shock_meta["shock_multiplier"])
                        estimate = raw_estimate * shock_multiplier if identified else np.nan
                        conf_low = estimate - 1.96 * std_error if identified else np.nan
                        conf_high = estimate + 1.96 * std_error if identified else np.nan
                        records.append(
                            {
                                "response_type": response_type,
                                **shock_meta,
                                "spec": spec,
                                "with_time_fe": with_time_fe,
                                "horizon": horizon,
                                "term": AGGREGATE_TERM,
                                **_term_metadata(AGGREGATE_TERM, with_time_fe=with_time_fe),
                                "estimate": estimate,
                                "std_error": std_error if identified else np.nan,
                                "conf_low": conf_low,
                                "conf_high": conf_high,
                                "n_obs": int(fit.nobs),
                                "n_states": int(reg_df["uf_code"].nunique()),
                                "identified": identified,
                                "note": (
                                    "Aggregate total IRF evaluated at sample mean "
                                    f"lagged shares: PH2M={weights['mp_shock_x_share_PH2M']:.4f}, "
                                    f"WH2M={weights['mp_shock_x_share_WH2M']:.4f}."
                                ),
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
    shock_direction: str = "both",
) -> pd.DataFrame:
    specs = _state_spec_definitions()
    shock_metas = [_shock_metadata(direction) for direction in _selected_shock_directions(shock_direction)]
    state_share_means = (
        panel.groupby("uf_code", sort=True)[SHARE_COLS]
        .mean()
        .rename(columns={col: f"avg_{col}" for col in SHARE_COLS})
    )
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
                    raw_estimate = float(fit.params.get("mp_shock", np.nan))
                    std_error = float(fit.bse.get("mp_shock", np.nan))
                    state_name = str(reg_df["state_name"].iloc[0])
                    macro_region = str(reg_df["macro_region"].iloc[0])
                    avg_shares = state_share_means.loc[int(uf_code)]
                    for shock_meta in shock_metas:
                        shock_multiplier = float(shock_meta["shock_multiplier"])
                        estimate = raw_estimate * shock_multiplier
                        identified = not np.isnan(estimate)
                        records.append(
                            {
                                "response_type": response_type,
                                **shock_meta,
                                "spec": spec,
                                "uf_code": int(uf_code),
                                "state_name": state_name,
                                "macro_region": macro_region,
                                "avg_share_PH2M": float(avg_shares["avg_share_PH2M"]),
                                "avg_share_WH2M": float(avg_shares["avg_share_WH2M"]),
                                "avg_share_Ricardian": float(avg_shares["avg_share_Ricardian"]),
                                "horizon": horizon,
                                "term": "mp_shock",
                                "term_label": "State-level shock response",
                                "term_role": "descriptive_state_irf",
                                "household_exposure": "",
                                "baseline_household_type": "",
                                "term_note": (
                                    "Descriptive state-level spatial IRF; not a "
                                    "household-type IRF."
                                ),
                                "estimate": estimate,
                                "std_error": std_error if identified else np.nan,
                                "conf_low": estimate - 1.96 * std_error if identified else np.nan,
                                "conf_high": estimate + 1.96 * std_error if identified else np.nan,
                                "n_obs": int(fit.nobs),
                                "identified": identified,
                                "se_type": "HC1",
                                "note": "Descriptive state-level spatial IRF; not a household-type IRF.",
                            }
                        )

    state_irf = pd.DataFrame(records)
    if state_irf.empty:
        raise ValueError("State-level LP output is empty.")
    return state_irf


def add_scaled_exposure_effects(
    irf: pd.DataFrame,
    share_delta: float = DEFAULT_PLOT_SHARE_DELTA,
) -> pd.DataFrame:
    """Add plot-ready effects for a realistic household-share exposure contrast."""
    if share_delta <= 0:
        raise ValueError("plot_share_delta must be positive.")

    out = irf.copy()
    interaction = out["term"].isin(INTERACTION_TERMS)
    out["plot_share_delta"] = np.where(interaction, share_delta, np.nan)
    out["plot_share_delta_pp"] = np.where(interaction, share_delta * 100, np.nan)
    out["plot_estimate"] = np.where(interaction, out["estimate"] * share_delta, np.nan)
    out["plot_std_error"] = np.where(interaction, out["std_error"] * share_delta, np.nan)
    out["plot_conf_low"] = np.where(interaction, out["conf_low"] * share_delta, np.nan)
    out["plot_conf_high"] = np.where(interaction, out["conf_high"] * share_delta, np.nan)
    out["plot_effect_label"] = np.where(
        interaction,
        f"log response for +{share_delta * 100:g} pp household-share exposure",
        "",
    )
    return out


def plot_irf(
    irf: pd.DataFrame,
    response_type: str,
    path: Path,
    share_delta: float = DEFAULT_PLOT_SHARE_DELTA,
) -> None:
    if "plot_estimate" not in irf.columns:
        irf = add_scaled_exposure_effects(irf, share_delta=share_delta)
    hp = irf.loc[
        irf["term"].isin(INTERACTION_TERMS)
        & irf["identified"]
        & irf["response_type"].eq(response_type)
    ].copy()
    preferred = hp.loc[hp["spec"].isin(PREFERRED_SPECS)].copy()
    if not preferred.empty:
        hp = preferred
    terms = [term for term in INTERACTION_TERMS if term in set(hp["term"])]
    directions = [direction for direction in SHOCK_DIRECTIONS if direction in set(hp["shock_direction"])]
    if not directions:
        directions = sorted(hp["shock_direction"].dropna().unique())

    n_rows = max(1, len(terms))
    n_cols = max(1, len(directions))
    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=(4.8 * n_cols, 3.2 * n_rows),
        sharex=True,
        squeeze=False,
    )
    colors = {
        "lag1_time_fe": "#1f77b4",
        "lag2_time_fe": "#d62728",
        "lag1": "#2ca02c",
        "lag2": "#9467bd",
    }
    ylabel = (
        "Cumulative log response"
        if response_type == "cumulative"
        else "Marginal monthly log response"
    )
    if hp.empty:
        axes[0, 0].text(0.5, 0.5, "No identified household-exposure IRFs", ha="center")
        axes[0, 0].set_axis_off()
    else:
        for row_idx, term in enumerate(terms):
            for col_idx, direction in enumerate(directions):
                ax = axes[row_idx, col_idx]
                subset = hp.loc[
                    hp["term"].eq(term) & hp["shock_direction"].eq(direction)
                ].copy()
                for spec in [*PREFERRED_SPECS, "lag1", "lag2"]:
                    spec_df = subset.loc[subset["spec"].eq(spec)].sort_values("horizon")
                    if spec_df.empty:
                        continue
                    x = spec_df["horizon"].to_numpy(dtype=float)
                    estimate = spec_df["plot_estimate"].to_numpy(dtype=float)
                    low = spec_df["plot_conf_low"].to_numpy(dtype=float)
                    high = spec_df["plot_conf_high"].to_numpy(dtype=float)
                    ax.plot(x, estimate, label=spec, color=colors.get(spec))
                    ax.fill_between(
                        x,
                        low,
                        high,
                        color=colors.get(spec),
                        alpha=0.15,
                        linewidth=0,
                    )
                ax.axhline(0, color="black", linewidth=0.8)
                ax.set_title(
                    f"{subset['shock_plot_label'].iloc[0] if not subset.empty else direction}\n"
                    f"{_term_metadata(term, with_time_fe=True)['household_exposure']} exposure",
                    fontsize=10,
                )
                if row_idx == n_rows - 1:
                    ax.set_xlabel("Horizon (months)")
                if col_idx == 0:
                    ax.set_ylabel(f"{ylabel}\n(+{share_delta * 100:g} pp exposure)")
                ax.legend(title="Spec", fontsize=8)
    fig.suptitle(
        (
            f"State-Month {response_type.title()} Household-Exposure LP IRFs "
            f"(+{share_delta * 100:g} pp share)"
        ),
        fontsize=13,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def aggregate_irf_table(irf: pd.DataFrame) -> pd.DataFrame:
    aggregate = irf.loc[
        irf["term"].eq(AGGREGATE_TERM) & irf["identified"]
    ].copy()
    if aggregate.empty:
        raise ValueError("Aggregate IRF output is empty.")
    return aggregate.sort_values(["response_type", "shock_direction", "spec", "horizon"])


def plot_aggregate_irf(aggregate_irf: pd.DataFrame, response_type: str, path: Path) -> None:
    subset = aggregate_irf.loc[
        aggregate_irf["response_type"].eq(response_type)
        & aggregate_irf["identified"]
    ].copy()
    directions = [
        direction for direction in SHOCK_DIRECTIONS if direction in set(subset["shock_direction"])
    ]
    if not directions:
        directions = sorted(subset["shock_direction"].dropna().unique())

    n_cols = max(1, len(directions))
    fig, axes = plt.subplots(
        1,
        n_cols,
        figsize=(5.2 * n_cols, 3.6),
        sharex=True,
        sharey=True,
        squeeze=False,
    )
    colors = {"lag1": "#1f77b4", "lag2": "#d62728"}
    ylabel = (
        "Cumulative log response"
        if response_type == "cumulative"
        else "Marginal monthly log response"
    )
    if subset.empty:
        axes[0, 0].text(0.5, 0.5, "No aggregate IRF", ha="center")
        axes[0, 0].set_axis_off()
    else:
        for col_idx, direction in enumerate(directions):
            ax = axes[0, col_idx]
            direction_df = subset.loc[subset["shock_direction"].eq(direction)]
            for spec in ["lag1", "lag2"]:
                spec_df = direction_df.loc[direction_df["spec"].eq(spec)].sort_values("horizon")
                if spec_df.empty:
                    continue
                x = spec_df["horizon"].to_numpy(dtype=float)
                estimate = spec_df["estimate"].to_numpy(dtype=float)
                low = spec_df["conf_low"].to_numpy(dtype=float)
                high = spec_df["conf_high"].to_numpy(dtype=float)
                ax.plot(x, estimate, label=spec, color=colors.get(spec))
                ax.fill_between(x, low, high, color=colors.get(spec), alpha=0.15, linewidth=0)
            ax.axhline(0, color="black", linewidth=0.8)
            shock_label = (
                direction_df["shock_plot_label"].dropna().iloc[0]
                if not direction_df.empty
                else direction
            )
            ax.set_title(shock_label, fontsize=10)
            ax.set_xlabel("Horizon (months)")
            if col_idx == 0:
                ax.set_ylabel(ylabel)
            ax.legend(title="Spec", fontsize=8)
    fig.suptitle(
        f"Aggregate State-Month {response_type.title()} LP IRF at Mean Composition",
        fontsize=13,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _state_share_label(state_df: pd.DataFrame) -> str:
    row = state_df.iloc[0]
    return (
        f"PH2M {100 * row['avg_share_PH2M']:.1f}%, "
        f"WH2M {100 * row['avg_share_WH2M']:.1f}%, "
        f"Ric {100 * row['avg_share_Ricardian']:.1f}%"
    )


def plot_state_region_irfs(state_irf: pd.DataFrame, state_plot_dir: Path) -> list[Path]:
    paths: list[Path] = []
    state_plot_dir.mkdir(parents=True, exist_ok=True)
    for response_type in sorted(state_irf["response_type"].unique()):
        for shock_direction in [direction for direction in SHOCK_DIRECTIONS if direction in set(state_irf["shock_direction"])]:
            for spec in ["lag1", "lag2"]:
                subset = state_irf.loc[
                    state_irf["response_type"].eq(response_type)
                    & state_irf["shock_direction"].eq(shock_direction)
                    & state_irf["spec"].eq(spec)
                    & state_irf["identified"]
                ].copy()
                for region, region_df in subset.groupby("macro_region", sort=False):
                    region_df = region_df.sort_values(["uf_code", "horizon"])
                    states = list(region_df[["uf_code", "state_name"]].drop_duplicates().itertuples(index=False))
                    n_states = len(states)
                    n_cols = 3
                    n_rows = int(np.ceil(n_states / n_cols))
                    ylabel = (
                        "Cumulative log response"
                        if response_type == "cumulative"
                        else "Marginal monthly log response"
                    )
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
                        ax.set_title(
                            f"{state.state_name} ({state.uf_code})\n{_state_share_label(state_df)}",
                            fontsize=8.5,
                        )
                        ax.set_xlabel("Horizon (months)", fontsize=8)
                        ax.set_ylabel(ylabel, fontsize=8)
                        ax.tick_params(labelsize=8)
                    for ax in axes_arr[n_states:]:
                        ax.set_visible(False)
                    fig.suptitle(
                        f"{region}: descriptive state-level {response_type} IRFs to "
                        f"{region_df['shock_plot_label'].iloc[0]} ({spec})",
                        fontsize=13,
                    )
                    fig.tight_layout(rect=[0, 0, 1, 0.95])
                    path = (
                        state_plot_dir
                        / f"{_slug(response_type)}_{_slug(shock_direction)}_{_slug(spec)}_{_slug(region)}.png"
                    )
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
    aggregate_irf_out: Path,
    state_irf_out: Path,
    plot_dir: Path,
    state_plot_dir: Path,
    summary_out: Path,
    time_fe_diagnostics_out: Path,
    plot_share_delta: float = DEFAULT_PLOT_SHARE_DELTA,
) -> list[Path]:
    for path in [
        dataset_out,
        irf_out,
        aggregate_irf_out,
        state_irf_out,
        summary_out,
        time_fe_diagnostics_out,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
    irf = add_scaled_exposure_effects(irf, share_delta=plot_share_delta)
    aggregate_irf = aggregate_irf_table(irf)
    panel.to_csv(dataset_out, index=False)
    irf.to_csv(irf_out, index=False)
    aggregate_irf.to_csv(aggregate_irf_out, index=False)
    state_irf.to_csv(state_irf_out, index=False)
    summary.to_csv(summary_out, index=False)
    time_fe_diagnostics.to_csv(time_fe_diagnostics_out, index=False)
    plot_irf(irf, "cumulative", plot_dir / "cumulative_irf.png", share_delta=plot_share_delta)
    plot_irf(irf, "marginal", plot_dir / "marginal_irf.png", share_delta=plot_share_delta)
    plot_aggregate_irf(
        aggregate_irf,
        "cumulative",
        plot_dir / "aggregate_cumulative_irf.png",
    )
    plot_aggregate_irf(
        aggregate_irf,
        "marginal",
        plot_dir / "aggregate_marginal_irf.png",
    )
    return plot_state_region_irfs(state_irf, state_plot_dir)


def main() -> None:
    args = parse_args()
    consumption = read_consumption(args.consumption_csv)
    htm = read_htm_shares(args.htm_shares)
    labour = read_labour_market(args.labour_market)
    shocks = read_shocks(args.shock_log)
    # Ensure panel has a date column (fallback from year/month when missing)
    panel, summary = build_matched_panel(consumption, htm, labour, shocks)

    if "date" not in panel.columns:
        panel["date"] = pd.to_datetime(
            {"year": panel["year"].astype(int), "month": panel["month"].astype(int), "day": 1}
        )

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
        args.aggregate_irf_out,
        args.state_irf_out,
        args.plot_dir,
        args.state_plot_dir,
        args.summary_out,
        args.time_fe_diagnostics_out,
        args.plot_share_delta,
    )

    min_date, max_date = _date_range_label(panel)
    print(
        f"Matched LP panel: {len(panel):,} rows, {panel['uf_code'].nunique()} states, "
        f"{min_date} to {max_date}."
    )
    print(f"Wrote dataset: {args.dataset_out}")
    print(f"Wrote IRF table: {args.irf_out}")
    print(f"Wrote aggregate IRF table: {args.aggregate_irf_out}")
    print(f"Wrote state IRF table: {args.state_irf_out}")
    print(f"Wrote plots: {args.plot_dir}")
    print(f"Wrote {len(state_plot_paths)} state-region panel plots: {args.state_plot_dir}")
    print(f"Wrote merge summary: {args.summary_out}")
    print(f"Wrote time-FE diagnostics: {args.time_fe_diagnostics_out}")


if __name__ == "__main__":
    main()
