#!/usr/bin/env python3
"""
HTM Agent Classification Pipeline
=================================

Classifies Brazilian households into three agent types following the
Kaplan-Violante-Weidner framework:

- PH2M: Poor Hand-to-Mouth
- WH2M: Wealthy Hand-to-Mouth
- Ricardian

The POF stage classifies households and builds demographic bin shares.
The PNADC stage streams a monthly matched parquet in batches, transfers
POF bin probabilities, and writes canonical state-month expected shares.
Monte Carlo state-month shares are written as a diagnostic.
"""

from __future__ import annotations

import argparse
import warnings
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")


# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
DATA_DIR = PROJECT_ROOT / "Data" / "Dados_20230713"
DICT_FILE = PROJECT_ROOT / "Data" / "Documentacao_20230713" / "Dicionarios de variaveis.xls"
RESULTS_DIR = PROJECT_ROOT / "results"
TABLES_DIR = RESULTS_DIR / "tables"
PLOTS_DIR = RESULTS_DIR / "plots"
DIAGNOSTICS_DIR = RESULTS_DIR / "diagnostics"

PNAD_MATCHED_DEFAULT = PROJECT_ROOT / "pnadc_matched_with_periods.parquet"

SELIC_RATE = 0.09
LIQUID_THRESH = 0.50
ILLIQUID_MULT = 3
POVERTY_LINE = 170.0
ILLIQUID_RATIO_CAP = 20.0
LIQUID_RATIO_CAP = 50.0
H2M_NET_WORTH_SPLIT_QUANTILE = 0.55
ORDERING_FALLBACK_MIN_HOUSEHOLDS = 5_000
PENSION_MULT = 1
SAVINGS_FRAC = 0.50
ALPHA_SMOOTH = 0.1
MIN_WEIGHTED_N = 30
RANDOM_SEED = 42
DEFAULT_BATCH_SIZE = 500_000
POF_REFERENCE_YEAR = 2018
VEHICLE_BASE_VALUE_2018_BRL = {"1403001": 30000.0, "1403101": 5000.0}
VEHICLE_DEPRECIATION_RATE = 0.08
VEHICLE_DEPRECIATION_FLOOR = 0.20
USE_VEHICLE_VALUATION = True

AGENT_TYPES = ["PH2M", "WH2M", "Ricardian"]
QUINTILE_LABELS = ["Q1", "Q2", "Q3", "Q4", "Q5"]
INCOME_BAND_EDGES = (-np.inf, 170.0, 700.0, 2000.0, 4000.0, np.inf)
INCOME_BAND_LABELS = ("B1", "B2", "B3", "B4", "B5")
BIN_STRATEGY = "A"
MONTHLY_KEYS = ["uf_code", "year", "month", "ref_month_yyyymm"]
FINAL_MONTHLY_COLUMNS = [
    "uf_code",
    "year",
    "month",
    "ref_month_yyyymm",
    "share_PH2M",
    "share_WH2M",
    "share_Ricardian",
    "share_H2M",
    "total_weight",
    "n_obs",
    "n_unmatched",
]

PNADC_REQUIRED_COLUMNS = [
    "UF",
    "V2009",
    "V2007",
    "VD3004",
    "V2001",
    "rendimento_habitual_real",
    "ref_month_yyyymm",
    "ref_month_in_year",
    "weight_monthly",
]
PNADC_ID_COLUMNS = ["id_rs", "id_ind"]
PNADC_OPTIONAL_COLUMNS = [
    "formal",
    "conta_propria",
    "informal",
    "ocupado",
    "desocupado",
    "fora_forca_trab",
    "Ano",
    "Trimestre",
    "V1028",
    "Habitual",
]
PNADC_BATCH_COLUMNS = PNADC_REQUIRED_COLUMNS + PNADC_ID_COLUMNS + PNADC_OPTIONAL_COLUMNS


class BinStrategy(str, Enum):
    A = "A"
    G = "G"
    BOTH = "both"


# ============================================================================
# POF helpers
# ============================================================================


def _vehicle_value(*, code: str, acquisition_year: int | float) -> float:
    """Conservative depreciated value proxy for POF vehicle inventory items."""
    code_str = str(code).strip()
    code_num = pd.to_numeric(pd.Series([code]), errors="coerce").iloc[0]
    if pd.notna(code_num):
        code_str = str(int(code_num))
    if code_str not in VEHICLE_BASE_VALUE_2018_BRL:
        return 0.0

    base_value = VEHICLE_BASE_VALUE_2018_BRL[code_str]
    year = pd.to_numeric(pd.Series([acquisition_year]), errors="coerce").iloc[0]
    if pd.isna(year):
        remaining = VEHICLE_DEPRECIATION_FLOOR
    else:
        age = max(0.0, float(POF_REFERENCE_YEAR - year))
        remaining = max(VEHICLE_DEPRECIATION_FLOOR, 1.0 - VEHICLE_DEPRECIATION_RATE * age)
    return float(base_value * remaining)


def read_pof_table(txt_filename: str, sheet_name: str) -> pd.DataFrame:
    """Read a POF fixed-width text file using positions from the dictionary."""
    print(f"  Reading POF table: {txt_filename} (sheet={sheet_name})")
    layout = pd.read_excel(DICT_FILE, sheet_name=sheet_name, skiprows=3)
    layout = layout.dropna(subset=["Código da variável"])
    layout = layout.dropna(subset=["Posição Inicial", "Tamanho"])
    layout = layout[["Posição Inicial", "Tamanho", "Código da variável"]].copy()
    layout.columns = ["start", "width", "var_name"]
    layout["start"] = layout["start"].astype(int)
    layout["width"] = layout["width"].astype(int)

    colspecs = [
        (row["start"] - 1, row["start"] - 1 + row["width"])
        for _, row in layout.iterrows()
    ]
    names = layout["var_name"].tolist()
    return pd.read_fwf(DATA_DIR / txt_filename, colspecs=colspecs, names=names, dtype=str)


def uf_to_macroregion(uf: pd.Series) -> pd.Series:
    """Map UF code to one of the five Brazilian macro-regions."""
    uf_num = pd.to_numeric(uf, errors="coerce")
    return pd.cut(
        uf_num,
        bins=[0, 17, 29, 35, 43, 99],
        labels=["North", "Northeast", "Southeast", "South", "Central_West"],
        right=True,
    ).astype(str)


def age_to_group(age: pd.Series) -> pd.Series:
    return pd.cut(
        age,
        bins=[14, 24, 34, 44, 54, 64, 200],
        labels=["15-24", "25-34", "35-44", "45-54", "55-64", "65+"],
        right=True,
    ).astype(str)


def pof_education_group(nivel: pd.Series) -> pd.Series:
    """Map POF NIVEL_INSTRUCAO codes to coarse education groups."""
    nivel_num = pd.to_numeric(nivel, errors="coerce")
    mapping = {
        1: "no_education",
        2: "primary",
        3: "primary",
        4: "secondary",
        5: "secondary",
        6: "tertiary",
        7: "tertiary",
    }
    return nivel_num.map(mapping).fillna("unknown")


def pnadc_education_group(vd3004: pd.Series) -> pd.Series:
    """Map PNADC VD3004 codes to coarse education groups."""
    vd = pd.to_numeric(vd3004, errors="coerce")
    mapping = {
        1: "no_education",
        2: "primary",
        3: "primary",
        4: "secondary",
        5: "secondary",
        6: "tertiary",
        7: "tertiary",
    }
    return vd.map(mapping).fillna("unknown")


def pof_labor_status(row: pd.Series) -> str:
    """Derive labour status from POF income and occupation flags."""
    if row["total_labor_income"] > 0:
        v5303 = row.get("V5303", np.nan)
        v5302 = row.get("V5302", np.nan)
        if v5303 == 2:
            return "self_employed"
        if v5302 == 1:
            return "formal"
        return "informal"
    if 15 <= row["age"] < 65:
        return "unemployed"
    return "inactive"


def classify_agent(row: pd.Series) -> str:
    """Kaplan-Violante-Weidner two-threshold classification."""
    if row["liquid_ratio"] > LIQUID_THRESH:
        return "Ricardian"
    if row["illiquid_ratio"] >= ILLIQUID_MULT:
        return "WH2M"
    return "PH2M"


def _classify_with_exclusion(row: pd.Series) -> str:
    """KVW classifier with exclusion for nonpositive-income or invalid-ratio rows."""
    monthly_income = float(row.get("monthly_income", 0.0))
    if (
        monthly_income <= 0.0
        or pd.isna(row.get("liquid_ratio"))
        or pd.isna(row.get("illiquid_ratio"))
    ):
        return "inactive_excluded"
    if row["liquid_ratio"] > LIQUID_THRESH:
        return "Ricardian"
    if row["illiquid_ratio"] >= ILLIQUID_MULT:
        return "WH2M"
    return "PH2M"


def classify_agent_poverty_split(row: pd.Series) -> str:
    """
    Parallel classification:
    - Ricardian if liquid ratio above threshold
    - Otherwise H2M split by poverty status
    """
    if row["liquid_ratio"] > LIQUID_THRESH:
        return "Ricardian"
    return "PH2M" if bool(row["is_poor"]) else "WH2M"


def classify_agent_classical(row: pd.Series, net_worth_cutoff: float) -> str:
    """
    Classical H2M-style parallel classification:
    - Ricardian: liquid ratio above threshold
    - H2M: liquid ratio below/equal threshold, split by net-worth cutoff
      into poor (below cutoff) and wealthy (above/equal cutoff).
    """
    if row["liquid_ratio"] > LIQUID_THRESH:
        return "Ricardian"
    return "WH2M" if row["net_worth"] >= net_worth_cutoff else "PH2M"


def _smoothed_shares(
    *,
    weighted_ph2m: float | pd.Series,
    weighted_wh2m: float | pd.Series,
    weighted_ric: float | pd.Series,
    total_weight: float | pd.Series,
    pof_national: dict[str, float],
    alpha: float,
) -> tuple[float | pd.Series, float | pd.Series, float | pd.Series]:
    """Empirical-Bayes Dirichlet smoothing around POF national shares."""
    if alpha <= 0:
        raise ValueError("alpha must be > 0 for Dirichlet smoothing")

    denom = total_weight + alpha
    if np.any(np.asarray(denom) <= 0):
        raise ValueError("invalid smoothing denominator: total_weight + alpha must be > 0")

    p_ph2m = (weighted_ph2m + alpha * pof_national["p_ph2m"]) / denom
    p_wh2m = (weighted_wh2m + alpha * pof_national["p_wh2m"]) / denom
    p_ric = (weighted_ric + alpha * pof_national["p_ric"]) / denom
    return p_ph2m, p_wh2m, p_ric


def _component_metrics() -> list[str]:
    return [
        "monthly_income",
        "pc_income",
        "total_labor_income",
        "total_transfers",
        "pension_income",
        "govt_transfers",
        "financial_income",
        "other_labor_inc",
        "liquid_assets",
        "illiquid_assets",
        "liquid_ratio",
        "illiquid_ratio",
    ]


def _weighted_group_component_summary(
    pof: pd.DataFrame,
    *,
    agent_col: str = "agent_type",
) -> pd.DataFrame:
    """Weighted means of income/wealth components by group label in agent_col."""
    metrics = [
        *_component_metrics(),
    ]

    def _summarize(group: pd.DataFrame) -> pd.Series:
        w = pd.to_numeric(group["PESO_FINAL"], errors="coerce").fillna(0.0)
        out: dict[str, float] = {
            "weighted_n": float(w.sum()),
            "n_obs": int(len(group)),
        }
        for metric in metrics:
            vals = pd.to_numeric(group[metric], errors="coerce")
            valid = vals.notna() & w.gt(0)
            out[f"mean_{metric}"] = (
                float(np.average(vals.loc[valid], weights=w.loc[valid])) if valid.any() else np.nan
            )
        return pd.Series(out)

    return (
        pof.groupby(agent_col, as_index=False)
        .apply(_summarize)
        .reset_index(drop=True)
        .rename(columns={agent_col: "agent_type"})
        .sort_values("agent_type")
        .reset_index(drop=True)
    )


def _bin_unit_expected_summary(
    pof: pd.DataFrame,
    *,
    agent_col: str,
    bin_col: str = "bin_key",
) -> pd.DataFrame:
    """
    Final-bin comparison: each bin is a unit, aggregated via expected group mass.
    Weight for group g in bin b = bin_weight_b * prob(g|b).
    """
    metrics = _component_metrics()

    def _bin_wavg(group: pd.DataFrame, metric: str) -> float:
        vals = pd.to_numeric(group[metric], errors="coerce")
        w = pd.to_numeric(group["PESO_FINAL"], errors="coerce").fillna(0.0)
        valid = vals.notna() & w.gt(0)
        if not valid.any():
            return np.nan
        return float(np.average(vals.loc[valid], weights=w.loc[valid]))

    rows: list[dict[str, float | str]] = []
    for bk, g in pof.groupby(bin_col):
        bin_w = pd.to_numeric(g["PESO_FINAL"], errors="coerce").fillna(0.0)
        row: dict[str, float | str] = {"bin_key": bk, "bin_weight": float(bin_w.sum())}
        for metric in metrics:
            row[f"bin_mean_{metric}"] = _bin_wavg(g, metric)
        rows.append(row)
    bin_means = pd.DataFrame(rows)

    weighted = (
        pof.pivot_table(index=bin_col, columns=agent_col, values="PESO_FINAL", aggfunc="sum", fill_value=0)
        .reset_index()
    )
    for agent in AGENT_TYPES:
        if agent not in weighted.columns:
            weighted[agent] = 0.0
    weighted["bin_weight"] = weighted[AGENT_TYPES].sum(axis=1)
    denom = weighted["bin_weight"].replace(0, np.nan)
    weighted["p_ph2m"] = (weighted["PH2M"] / denom).fillna(0.0)
    weighted["p_wh2m"] = (weighted["WH2M"] / denom).fillna(0.0)
    weighted["p_ric"] = (weighted["Ricardian"] / denom).fillna(0.0)

    bin_level = bin_means.merge(weighted[[bin_col, "p_ph2m", "p_wh2m", "p_ric"]], on=bin_col, how="left")
    prob_map = {"PH2M": "p_ph2m", "WH2M": "p_wh2m", "Ricardian": "p_ric"}

    out_rows: list[dict[str, float | str | int]] = []
    for agent_type, prob_col in prob_map.items():
        w = (bin_level["bin_weight"] * bin_level[prob_col]).fillna(0.0)
        rec: dict[str, float | str | int] = {
            "agent_type": agent_type,
            "effective_bin_weight": float(w.sum()),
            "n_bins": int((w > 0).sum()),
        }
        for metric in metrics:
            x = pd.to_numeric(bin_level[f"bin_mean_{metric}"], errors="coerce")
            valid = x.notna() & w.gt(0)
            rec[f"mean_{metric}"] = float(np.average(x.loc[valid], weights=w.loc[valid])) if valid.any() else np.nan
        out_rows.append(rec)

    return pd.DataFrame(out_rows).sort_values("agent_type").reset_index(drop=True)


def _weighted_quantile(values: pd.Series, weights: pd.Series, q: float) -> float:
    """Weighted quantile for q in [0, 1]."""
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    mask = v.notna() & w.notna() & (w > 0)
    if not mask.any():
        return np.nan
    x = v.loc[mask].to_numpy()
    wt = w.loc[mask].to_numpy()
    order = np.argsort(x)
    x = x[order]
    wt = wt[order]
    cum = np.cumsum(wt) / wt.sum()
    idx = np.searchsorted(cum, q, side="left")
    idx = min(idx, len(x) - 1)
    return float(x[idx])


def build_pof_household_frame() -> pd.DataFrame:
    """Return one row per (COD_UPA, NUM_DOM, NUM_UC) with head demographics."""
    print("=" * 72)
    print("STEP 1a: BUILD HOUSEHOLD-LEVEL POF FRAME (head = V0306 == 1)")
    print("=" * 72)

    df_dom = read_pof_table("DOMICILIO.txt", "Domicílio")
    for col in ["COD_UPA", "NUM_DOM", "UF", "PESO_FINAL"]:
        df_dom[col] = pd.to_numeric(df_dom[col], errors="coerce")
    df_dom = df_dom[["COD_UPA", "NUM_DOM", "UF", "PESO_FINAL"]].copy()

    df_mor = read_pof_table("MORADOR.txt", "Morador")
    for col in [
        "COD_UPA",
        "NUM_DOM",
        "NUM_UC",
        "COD_INFORMANTE",
        "V0306",
        "V0403",
        "V0404",
        "NIVEL_INSTRUCAO",
        "RENDA_TOTAL",
    ]:
        df_mor[col] = pd.to_numeric(df_mor[col], errors="coerce")
    df_mor.rename(columns={"V0403": "age", "V0404": "sex"}, inplace=True)

    hh_residents = (
        df_mor.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"], as_index=False)
        .size()
        .rename(columns={"size": "hh_residents"})
    )
    heads_all = df_mor.loc[
        df_mor["V0306"] == 1,
        [
            "COD_UPA",
            "NUM_DOM",
            "NUM_UC",
            "COD_INFORMANTE",
            "age",
            "sex",
            "NIVEL_INSTRUCAO",
            "RENDA_TOTAL",
        ],
    ].copy()
    hh_keys = ["COD_UPA", "NUM_DOM", "NUM_UC"]
    multi_head_counts = heads_all.groupby(hh_keys, as_index=False).size().rename(columns={"size": "n_heads"})
    n_multi_head_hh = int((multi_head_counts["n_heads"] > 1).sum())
    print(f"  Households with multiple head candidates (V0306==1): {n_multi_head_hh:,}")
    # Deterministic head selection when multiple candidates exist.
    heads = (
        heads_all.sort_values(hh_keys + ["COD_INFORMANTE"], kind="mergesort")
        .drop_duplicates(hh_keys, keep="first")
        .copy()
    )

    df_inc = read_pof_table("RENDIMENTO_TRABALHO.txt", "Rendimento do Trabalho")
    for col in ["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE", "V8500_DEFLA", "V5302", "V5303"]:
        df_inc[col] = pd.to_numeric(df_inc[col], errors="coerce")
    inc_hh = (
        df_inc.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"], as_index=False)
        .agg(
            total_labor_income=("V8500_DEFLA", "sum"),
            household_V5302=("V5302", "first"),
            household_V5303=("V5303", "first"),
        )
    )

    df_oth = read_pof_table("OUTROS_RENDIMENTOS.txt", "Outros Rendimentos")
    for col in ["COD_UPA", "NUM_DOM", "NUM_UC", "QUADRO", "V8500_DEFLA"]:
        df_oth[col] = pd.to_numeric(df_oth[col], errors="coerce")
    trans_hh = (
        df_oth.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"], as_index=False)
        .apply(
            lambda g: pd.Series(
                {
                    "pension_income": g.loc[g.QUADRO == 55, "V8500_DEFLA"].sum(),
                    "govt_transfers": g.loc[g.QUADRO == 56, "V8500_DEFLA"].sum(),
                    "financial_income": g.loc[g.QUADRO == 57, "V8500_DEFLA"].sum(),
                    "other_labor_inc": g.loc[g.QUADRO == 54, "V8500_DEFLA"].sum(),
                    "total_transfers": g["V8500_DEFLA"].sum(),
                }
            )
        )
    )

    df_alug = read_pof_table("ALUGUEL_ESTIMADO.txt", "Aluguel Estimado")
    for col in ["COD_UPA", "NUM_DOM", "NUM_UC", "V8000_DEFLA"]:
        df_alug[col] = pd.to_numeric(df_alug[col], errors="coerce")
    alug_hh = df_alug.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"], as_index=False).agg(
        estimated_rent=("V8000_DEFLA", "sum")
    )
    alug_hh["real_estate_annual"] = alug_hh["estimated_rent"] * 12

    if USE_VEHICLE_VALUATION:
        df_inv = read_pof_table("INVENTARIO.txt", "Inventário")
        for col in ["COD_UPA", "NUM_DOM", "NUM_UC", "V9001", "V1404", "V9005"]:
            if col in df_inv.columns:
                df_inv[col] = pd.to_numeric(df_inv[col], errors="coerce")
        if not {"COD_UPA", "NUM_DOM", "NUM_UC"}.issubset(df_inv.columns):
            veh_hh = pd.DataFrame(columns=["COD_UPA", "NUM_DOM", "NUM_UC", "vehicle_value"])
        else:
            code = df_inv["V9001"] if "V9001" in df_inv.columns else pd.Series(index=df_inv.index, dtype="float64")
            acq_year = df_inv["V1404"] if "V1404" in df_inv.columns else pd.Series(index=df_inv.index, dtype="float64")
            df_inv["vehicle_unit_value"] = [
                _vehicle_value(code=str(c) if pd.notna(c) else "", acquisition_year=y)
                for c, y in zip(code, acq_year)
            ]
            qty = (
                df_inv["V9005"]
                if "V9005" in df_inv.columns
                else pd.Series(index=df_inv.index, dtype="float64")
            )
            qty_num = pd.to_numeric(qty, errors="coerce")
            df_inv["vehicle_qty"] = np.where(qty_num.isna(), 1.0, np.where(qty_num <= 0, 0.0, qty_num))
            df_inv["total_value"] = df_inv["vehicle_unit_value"] * df_inv["vehicle_qty"]
            veh_hh = (
                df_inv.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"], as_index=False)
                .agg(vehicle_value=("total_value", "sum"))
            )
    else:
        veh_hh = pd.DataFrame(columns=["COD_UPA", "NUM_DOM", "NUM_UC", "vehicle_value"])

    print("\n  Merging POF tables ...")
    head_inc = (
        df_inc.sort_values(hh_keys + ["COD_INFORMANTE"], kind="mergesort")
        .groupby(hh_keys + ["COD_INFORMANTE"], as_index=False)
        .agg(V5302=("V5302", "first"), V5303=("V5303", "first"))
    )

    hh = (
        heads.merge(df_dom, on=["COD_UPA", "NUM_DOM"], how="left")
        .merge(hh_residents, on=["COD_UPA", "NUM_DOM", "NUM_UC"], how="left")
        .merge(inc_hh, on=["COD_UPA", "NUM_DOM", "NUM_UC"], how="left")
        .merge(head_inc, on=["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE"], how="left")
        .merge(trans_hh, on=["COD_UPA", "NUM_DOM", "NUM_UC"], how="left")
        .merge(alug_hh, on=["COD_UPA", "NUM_DOM", "NUM_UC"], how="left")
        .merge(veh_hh, on=["COD_UPA", "NUM_DOM", "NUM_UC"], how="left")
    )

    fill_cols = [
        "total_labor_income",
        "pension_income",
        "govt_transfers",
        "financial_income",
        "other_labor_inc",
        "total_transfers",
        "estimated_rent",
        "real_estate_annual",
        "vehicle_value",
    ]
    hh[fill_cols] = hh[fill_cols].fillna(0)
    hh["monthly_income"] = hh["total_labor_income"] + hh["total_transfers"]
    hh["pc_income"] = hh["monthly_income"] / hh["hh_residents"].clip(lower=1)
    missing_head_hh = int(hh["COD_INFORMANTE"].isna().sum())
    if missing_head_hh > 0:
        print(f"  Households without a head candidate (V0306==1): {missing_head_hh:,} -> dropped")
    hh = hh[hh["COD_INFORMANTE"].notna()].copy()
    if hh.duplicated(hh_keys).any():
        raise ValueError("build_pof_household_frame produced duplicate household keys after head selection")
    print(f"  POF households: {len(hh):,}")
    return hh


def build_pof_bin_shares(
    tables_dir: Path = TABLES_DIR,
    *,
    diagnostics_dir: Path | None = None,
    write_outputs: bool = True,
    bin_strategy: str | BinStrategy | None = None,
) -> tuple[pd.DataFrame, np.ndarray, dict[str, float]]:
    """
    Classify POF records and compute smoothed demographic bin probabilities.

    Returns:
        bin_shares: one row per bin_key with p_ph2m, p_wh2m, p_ric.
        pof_quintile_edges: POF per-capita income quintile cut-points.
        pof_national: national weighted probabilities for fallback matching.
    """
    print("=" * 72)
    print("STEP 1: LOAD & CLASSIFY POF HOUSEHOLDS")
    print("=" * 72)
    if diagnostics_dir is None:
        diagnostics_dir = DIAGNOSTICS_DIR
    strategy = BIN_STRATEGY if bin_strategy is None else (
        bin_strategy.value if isinstance(bin_strategy, BinStrategy) else bin_strategy
    )
    hh = build_pof_household_frame()
    pof = hh.rename(columns={"hh_residents": "_hh_residents"}).copy()

    pof["monthly_income"] = pof["total_labor_income"] + pof["total_transfers"]
    # NOTE: do NOT clip(lower=1). See validity review §4.
    pof["financial_income_annual"] = pof["financial_income"] * 12
    pof["fin_liquid"] = pof["financial_income_annual"] / SELIC_RATE
    pof["pen_liquid"] = pof["pension_income"] * PENSION_MULT
    pof["income_surplus"] = (pof["RENDA_TOTAL"] - pof["monthly_income"] * 12).clip(lower=0)
    pof["sav_liquid"] = pof["income_surplus"] * SAVINGS_FRAC
    pof.loc[pof["govt_transfers"] > 0, "sav_liquid"] = 0
    pof["liquid_assets"] = pof["fin_liquid"] + pof["pen_liquid"] + pof["sav_liquid"]
    pof["illiquid_assets"] = pof["real_estate_annual"] + pof["vehicle_value"].fillna(0)

    denom = pof["monthly_income"].where(pof["monthly_income"] > 0)
    pof["liquid_ratio"] = (pof["liquid_assets"] / denom).clip(upper=LIQUID_RATIO_CAP)
    pof["illiquid_ratio"] = (pof["illiquid_assets"] / denom).clip(upper=ILLIQUID_RATIO_CAP)
    reason_parts: list[pd.Series] = []
    reason_parts.append(
        pd.Series(
            np.where(pof["monthly_income"] <= 0.0, "nonpositive_monthly_income", ""),
            index=pof.index,
            dtype="object",
        )
    )
    reason_parts.append(
        pd.Series(
            np.where(pof["liquid_ratio"].isna(), "invalid_liquid_ratio", ""),
            index=pof.index,
            dtype="object",
        )
    )
    reason_parts.append(
        pd.Series(
            np.where(pof["illiquid_ratio"].isna(), "invalid_illiquid_ratio", ""),
            index=pof.index,
            dtype="object",
        )
    )
    pof["exclusion_reason"] = reason_parts[0]
    for extra in reason_parts[1:]:
        pof["exclusion_reason"] = np.where(
            (pof["exclusion_reason"] != "") & (extra != ""),
            pof["exclusion_reason"] + "|" + extra,
            np.where(extra != "", extra, pof["exclusion_reason"]),
        )
    pof["exclusion_reason"] = pof["exclusion_reason"].replace("", np.nan)
    pof["net_worth"] = pof["liquid_assets"] + pof["illiquid_assets"]
    pof["is_poor"] = pof["pc_income"] <= POVERTY_LINE
    pof["agent_type_exclusion"] = pof.apply(_classify_with_exclusion, axis=1)

    excluded_mask = pof["agent_type_exclusion"] == "inactive_excluded"
    excluded_count = int(excluded_mask.sum())
    excluded_weight = float(pof.loc[excluded_mask, "PESO_FINAL"].sum())
    excluded_diag_reason = (
        pof.loc[excluded_mask]
        .groupby(["exclusion_reason"], dropna=False)
        .agg(n=("PESO_FINAL", "size"), weight=("PESO_FINAL", "sum"))
        .reset_index()
        .assign(age=np.nan, sex=np.nan, breakdown="reason_total")
    )
    excluded_diag_age_sex = (
        pof.loc[excluded_mask]
        .groupby(["exclusion_reason", "age", "sex"], dropna=False)
        .agg(n=("PESO_FINAL", "size"), weight=("PESO_FINAL", "sum"))
        .reset_index()
        .assign(breakdown="reason_age_sex")
    )
    excluded_diag = pd.concat([excluded_diag_reason, excluded_diag_age_sex], ignore_index=True)
    if write_outputs:
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        excluded_diag.to_csv(
            diagnostics_dir / "pof_zero_income_excluded.csv", index=False
        )
    pof = pof.loc[~excluded_mask].copy()
    h2m_mask = pof["liquid_ratio"] <= LIQUID_THRESH
    classical_cutoff = _weighted_quantile(
        pof.loc[h2m_mask, "net_worth"],
        pof.loc[h2m_mask, "PESO_FINAL"],
        q=0.5,
    )
    fallback_cutoff = _weighted_quantile(
        pof.loc[h2m_mask, "net_worth"],
        pof.loc[h2m_mask, "PESO_FINAL"],
        q=H2M_NET_WORTH_SPLIT_QUANTILE,
    )
    # Baseline remains KVW two-threshold after excluding invalid/inactive rows.
    pof["agent_type"] = pof.apply(classify_agent, axis=1)
    pof["agent_type_poverty_split"] = pof.apply(classify_agent_poverty_split, axis=1)
    pof["agent_type_classical"] = pof.apply(
        lambda r: classify_agent_classical(r, classical_cutoff),
        axis=1,
    )

    weights = pd.to_numeric(pof["PESO_FINAL"], errors="coerce").fillna(0.0)
    ph_mask = pof["agent_type"] == "PH2M"
    wh_mask = pof["agent_type"] == "WH2M"
    ph_income_mean = float(
        np.average(pof.loc[ph_mask, "monthly_income"], weights=weights.loc[ph_mask])
    ) if ph_mask.any() else np.nan
    wh_income_mean = float(
        np.average(pof.loc[wh_mask, "monthly_income"], weights=weights.loc[wh_mask])
    ) if wh_mask.any() else np.nan
    fallback_applied = False
    if (
        len(pof) >= ORDERING_FALLBACK_MIN_HOUSEHOLDS
        and np.isfinite(ph_income_mean)
        and np.isfinite(wh_income_mean)
        and wh_income_mean <= ph_income_mean
    ):
        # Enforce validity-review ordering target WH2M income > PH2M income.
        pof["agent_type"] = pof.apply(
            lambda r: classify_agent_classical(r, fallback_cutoff),
            axis=1,
        )
        fallback_applied = True

    msg = (
        f"  Excluded {excluded_count:,} rows (nonpositive income and/or invalid ratios) "
        f"(weighted = {excluded_weight:.0f})."
    )
    if fallback_applied:
        msg += (
            f" Applied classical H2M fallback at quantile={H2M_NET_WORTH_SPLIT_QUANTILE:.2f} "
            f"(cutoff={fallback_cutoff:.2f}) to restore WH2M>PH2M ordering."
        )
    if write_outputs:
        msg += f" Diagnostic -> {diagnostics_dir / 'pof_zero_income_excluded.csv'}"
    print(msg)

    weights = pof["PESO_FINAL"]
    total_w = weights.sum()
    pof_national_agent = {
        agent_type: weights[pof["agent_type"] == agent_type].sum() / total_w
        for agent_type in AGENT_TYPES
    }
    pof_national = {
        "p_ph2m": pof_national_agent["PH2M"],
        "p_wh2m": pof_national_agent["WH2M"],
        "p_ric": pof_national_agent["Ricardian"],
    }

    print("\n  POF national weighted type shares")
    print(
        f"    PH2M={pof_national_agent['PH2M']:.4f}  "
        f"WH2M={pof_national_agent['WH2M']:.4f}  "
        f"Ricardian={pof_national_agent['Ricardian']:.4f}  "
        f"N={len(pof):,}"
    )
    validity = {
        "negative_monthly_income_rows": int((pof["monthly_income"] < 0).sum()),
        "negative_liquid_assets_rows": int((pof["liquid_assets"] < 0).sum()),
        "negative_illiquid_assets_rows": int((pof["illiquid_assets"] < 0).sum()),
    }
    print(
        "  Internal validity checks:"
        f" neg_monthly_income={validity['negative_monthly_income_rows']},"
        f" neg_liquid_assets={validity['negative_liquid_assets_rows']},"
        f" neg_illiquid_assets={validity['negative_illiquid_assets_rows']}"
    )

    component_summary = _weighted_group_component_summary(pof, agent_col="agent_type")
    component_summary_poverty_split = _weighted_group_component_summary(
        pof, agent_col="agent_type_poverty_split"
    )
    component_summary_classical = _weighted_group_component_summary(
        pof, agent_col="agent_type_classical"
    )
    summary_path = tables_dir / "pof_group_wealth_income_summary.csv"
    summary_path_parallel = tables_dir / "pof_group_wealth_income_summary_poverty_split.csv"
    summary_path_classical = tables_dir / "pof_group_wealth_income_summary_classical.csv"
    if write_outputs:
        tables_dir.mkdir(parents=True, exist_ok=True)
        component_summary.to_csv(summary_path, index=False)
        component_summary_poverty_split.to_csv(summary_path_parallel, index=False)
        component_summary_classical.to_csv(summary_path_classical, index=False)
        print(f"  Saved weighted wealth/income component summary -> {summary_path}")
        print(f"  Saved weighted wealth/income component summary (poverty split) -> {summary_path_parallel}")
        print(
            f"  Saved weighted wealth/income component summary (classical H2M, "
            f"median H2M net worth cutoff={classical_cutoff:.2f}) -> {summary_path_classical}"
        )

    print("\n" + "=" * 72)
    print("STEP 2: BUILD POF DEMOGRAPHIC BINS & WEIGHTED TYPE SHARES")
    print("=" * 72)

    pof["macro_region"] = uf_to_macroregion(pof["UF"])
    pof["age_group"] = age_to_group(pof["age"])
    pof["gender"] = pof["sex"].map({1: "male", 2: "female"}).fillna("unknown")
    pof["education_group"] = pof_education_group(pof["NIVEL_INSTRUCAO"])
    pof["labor_status"] = pof.apply(pof_labor_status, axis=1)
    pof["labor_status_3way"] = _labor_status_3way(
        pof.assign(
            formal=(pof["labor_status"] == "formal").astype(int),
            conta_propria=(pof["labor_status"] == "self_employed").astype(int),
            informal=(pof["labor_status"] == "informal").astype(int),
            desocupado=(pof["labor_status"] == "unemployed").astype(int),
        )
    )
    pof["pc_income_quintile"], pof_quintile_edges = pd.qcut(
        pof["pc_income"], q=5, labels=QUINTILE_LABELS, retbins=True
    )
    pof["pc_income_quintile"] = pof["pc_income_quintile"].astype(str)
    pof["income_band_absolute"] = _income_band_absolute(pof["pc_income"])
    pof["bin_key"] = _build_bin_key(pof, strategy=strategy)

    bin_unit_baseline = _bin_unit_expected_summary(pof, agent_col="agent_type", bin_col="bin_key")
    bin_unit_parallel = _bin_unit_expected_summary(
        pof, agent_col="agent_type_poverty_split", bin_col="bin_key"
    )
    bin_unit_classical = _bin_unit_expected_summary(
        pof, agent_col="agent_type_classical", bin_col="bin_key"
    )
    bin_unit_baseline["classification"] = "baseline"
    bin_unit_parallel["classification"] = "poverty_split"
    bin_unit_classical["classification"] = "classical_h2m"
    bin_compare = pd.concat([bin_unit_baseline, bin_unit_parallel, bin_unit_classical], ignore_index=True)
    bin_compare_path = tables_dir / "pof_group_wealth_income_summary_bin_units_compare.csv"
    if write_outputs:
        bin_compare.to_csv(bin_compare_path, index=False)
        print(
            "  Saved bin-unit comparison summary "
            "(baseline vs poverty split vs classical_h2m) -> "
            f"{bin_compare_path}"
        )

    grouped = pof.groupby("bin_key")
    weighted = pof.pivot_table(
        index="bin_key",
        columns="agent_type",
        values="PESO_FINAL",
        aggfunc="sum",
        fill_value=0,
    )
    for agent_type in AGENT_TYPES:
        if agent_type not in weighted.columns:
            weighted[agent_type] = 0.0
    total = grouped["PESO_FINAL"].sum()
    raw_n = grouped.size()
    p_ph2m, p_wh2m, p_ric = _smoothed_shares(
        weighted_ph2m=weighted["PH2M"],
        weighted_wh2m=weighted["WH2M"],
        weighted_ric=weighted["Ricardian"],
        total_weight=total,
        pof_national=pof_national,
        alpha=ALPHA_SMOOTH,
    )

    bin_shares = pd.DataFrame(
        {
            "bin_key": total.index,
            "p_ph2m": p_ph2m,
            "p_wh2m": p_wh2m,
            "p_ric": p_ric,
            "weighted_n": total,
            "raw_n": raw_n,
            "small_bin_flag": (total < MIN_WEIGHTED_N).astype(int),
        }
    ).reset_index(drop=True)
    bin_shares.attrs["pof_national"] = pof_national

    if write_outputs:
        tables_dir.mkdir(parents=True, exist_ok=True)
        out_name = "pof_bin_shares.csv" if strategy == "A" else f"pof_bin_shares_{strategy}.csv"
        out_path_bins = tables_dir / out_name
        bin_shares.to_csv(out_path_bins, index=False)
        print(f"\n  Saved {len(bin_shares):,} bins -> {out_path_bins}")
    print(
        f"  Bins with < {MIN_WEIGHTED_N} weighted obs: "
        f"{int(bin_shares['small_bin_flag'].sum()):,}"
    )

    return bin_shares, pof_quintile_edges, pof_national


# ============================================================================
# PNADC batch preparation
# ============================================================================


def _numeric_column(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(default, index=df.index, dtype="float64")


def _parse_ref_month_yyyymm(series: pd.Series) -> pd.Series:
    """Return nullable integer YYYYMM keys from strings, numbers, or datetimes."""
    if pd.api.types.is_datetime64_any_dtype(series):
        key = series.dt.year * 100 + series.dt.month
        return key.astype("Int64")

    digits = (
        series.astype("string")
        .str.replace(r"\D", "", regex=True)
        .str.slice(0, 6)
    )
    key = pd.to_numeric(digits, errors="coerce")
    return key.astype("Int64")


def _income_quintiles_from_pof_edges(income: pd.Series, pof_quintile_edges: np.ndarray) -> pd.Series:
    bins_extended = np.concatenate([[-np.inf], np.asarray(pof_quintile_edges)[1:-1], [np.inf]])
    q = pd.cut(
        income,
        bins=bins_extended,
        labels=QUINTILE_LABELS,
        include_lowest=True,
    )
    return pd.Series(q, index=income.index).astype("object").where(pd.notna(q), "Q3").astype(str)


def _labor_status_3way(df: pd.DataFrame) -> pd.Series:
    """Collapse detailed labour status to employed/unemployed/inactive."""
    formal = pd.to_numeric(df.get("formal", 0), errors="coerce").fillna(0)
    conta = pd.to_numeric(df.get("conta_propria", 0), errors="coerce").fillna(0)
    informal = pd.to_numeric(df.get("informal", 0), errors="coerce").fillna(0)
    desoc = pd.to_numeric(df.get("desocupado", 0), errors="coerce").fillna(0)
    out = pd.Series("inactive", index=df.index, dtype="object")
    out.loc[desoc == 1] = "unemployed"
    out.loc[(formal == 1) | (conta == 1) | (informal == 1)] = "employed"
    return out


def _income_band_absolute(income: pd.Series) -> pd.Series:
    """Bucket monthly income into documented absolute BRL bands."""
    return pd.cut(
        income,
        bins=list(INCOME_BAND_EDGES),
        labels=list(INCOME_BAND_LABELS),
        right=True,
        include_lowest=True,
    ).astype(str)


def _build_bin_key(df: pd.DataFrame, *, strategy: str | BinStrategy) -> pd.Series:
    strategy_value = strategy.value if isinstance(strategy, BinStrategy) else strategy
    if strategy_value == "G":
        return (
            df["macro_region"]
            + "|"
            + df["age_group"]
            + "|"
            + df["gender"]
            + "|"
            + df["education_group"]
            + "|"
            + df["income_band_absolute"]
            + "|"
            + df["labor_status_3way"]
        )
    if strategy_value != "A":
        raise ValueError(f"unknown bin strategy: {strategy!r}")
    return (
        df["macro_region"]
        + "|"
        + df["age_group"]
        + "|"
        + df["gender"]
        + "|"
        + df["education_group"]
        + "|"
        + df["pc_income_quintile"]
        + "|"
        + df["labor_status"]
    )


def _per_quarter_quintiles(df: pd.DataFrame) -> pd.Series:
    """Legacy option: rank within the current batch's year-quarter cells."""
    out = pd.Series("Q3", index=df.index, dtype="object")
    quarter = ((df["month"].astype(int) - 1) // 3 + 1).astype(int)
    tmp = df.assign(_quarter=quarter)

    def assign_group(group: pd.DataFrame) -> pd.Series:
        if group["pc_income_pnadc"].notna().sum() < 5:
            return pd.Series("Q3", index=group.index, dtype="object")
        return pd.qcut(
            group["pc_income_pnadc"].rank(method="first"),
            q=5,
            labels=QUINTILE_LABELS,
        ).astype("object")

    for _, group in tmp.groupby(["year", "_quarter"], dropna=False):
        out.loc[group.index] = assign_group(group)
    return out.astype(str)


def _pnadc_labor_status_vectorized(df: pd.DataFrame) -> pd.Series:
    formal = _numeric_column(df, "formal", 0).fillna(0)
    conta_propria = _numeric_column(df, "conta_propria", 0).fillna(0)
    informal = _numeric_column(df, "informal", 0).fillna(0)
    ocupado = _numeric_column(df, "ocupado", 0).fillna(0)
    desocupado = _numeric_column(df, "desocupado", 0).fillna(0)

    status = pd.Series("inactive", index=df.index, dtype="object")
    status.loc[desocupado == 1] = "unemployed"
    status.loc[(informal == 1) | (ocupado == 1)] = "informal"
    status.loc[conta_propria == 1] = "self_employed"
    status.loc[formal == 1] = "formal"
    return status


def _fallback_probabilities(bin_shares: pd.DataFrame) -> dict[str, float]:
    attrs = bin_shares.attrs.get("pof_national")
    if attrs is not None:
        return {
            "p_ph2m": float(attrs["p_ph2m"]),
            "p_wh2m": float(attrs["p_wh2m"]),
            "p_ric": float(attrs["p_ric"]),
        }

    if "weighted_n" in bin_shares.columns:
        weights = pd.to_numeric(bin_shares["weighted_n"], errors="coerce").fillna(0)
        if weights.sum() > 0:
            return {
                "p_ph2m": float(np.average(bin_shares["p_ph2m"], weights=weights)),
                "p_wh2m": float(np.average(bin_shares["p_wh2m"], weights=weights)),
                "p_ric": float(np.average(bin_shares["p_ric"], weights=weights)),
            }

    return {
        "p_ph2m": float(bin_shares["p_ph2m"].mean()),
        "p_wh2m": float(bin_shares["p_wh2m"].mean()),
        "p_ric": float(bin_shares["p_ric"].mean()),
    }


def deterministic_uniform(ids: pd.Series, random_seed: int = RANDOM_SEED) -> np.ndarray:
    """Stable per-id U(0, 1) draw independent of batch order."""
    payload = ids.astype("string").fillna("") + f"|{random_seed}"
    hashed = pd.util.hash_pandas_object(payload, index=False).to_numpy(dtype=np.uint64)
    return hashed.astype("float64") / float(2**64)


def _stable_missing_id_fallback(df: pd.DataFrame) -> pd.Series:
    """
    Build a deterministic row key when both panel IDs are missing.

    This is only for the Monte Carlo diagnostic. Expected monthly shares are
    unaffected by MC labels, and the fallback avoids dropping otherwise valid
    monthly observations because of incomplete identifier fields.
    """
    key_cols = [
        "UF",
        "UPA",
        "V1008",
        "V1014",
        "V2003",
        "V2007",
        "V2008",
        "V20081",
        "V20082",
        "V2009",
        "ref_month_yyyymm",
        "ref_month_in_year",
    ]
    available = [col for col in key_cols if col in df.columns]
    if not available:
        return pd.Series("fallback-row-" + df.index.astype("string"), index=df.index)

    key = df[available].astype("string").fillna("<NA>").agg("|".join, axis=1)
    return "fallback-fields|" + key


def _deterministic_agent_type(df: pd.DataFrame, random_seed: int) -> pd.Series:
    if "id_rs" in df.columns:
        ids = df["id_rs"].copy()
        if "id_ind" in df.columns:
            ids = ids.where(ids.notna(), df["id_ind"])
    elif "id_ind" in df.columns:
        ids = df["id_ind"].copy()
    else:
        raise ValueError("PNADC batch must contain id_rs or id_ind for deterministic MC draws.")

    if ids.isna().any():
        ids = ids.where(ids.notna(), _stable_missing_id_fallback(df))

    u = deterministic_uniform(ids, random_seed=random_seed)
    return pd.Series(
        np.where(
            u <= df["p_ph2m"].to_numpy(),
            "PH2M",
            np.where(
                u <= (df["p_ph2m"] + df["p_wh2m"]).to_numpy(),
                "WH2M",
                "Ricardian",
            ),
        ),
        index=df.index,
        dtype="object",
    )


def _exclusions_by_month(ref_key: pd.Series, weight_missing: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "ref_month_yyyymm": ref_key,
            "excluded_missing_weight": weight_missing.astype(int),
            "raw_rows_with_known_month": ref_key.notna().astype(int),
        }
    )
    frame = frame[frame["ref_month_yyyymm"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "ref_month_yyyymm",
                "year",
                "month",
                "excluded_missing_weight",
                "raw_rows_with_known_month",
            ]
        )

    out = (
        frame.groupby("ref_month_yyyymm", as_index=False)
        .agg(
            excluded_missing_weight=("excluded_missing_weight", "sum"),
            raw_rows_with_known_month=("raw_rows_with_known_month", "sum"),
        )
    )
    key_num = out["ref_month_yyyymm"].astype("int64")
    out["year"] = (key_num // 100).astype(int)
    out["month"] = (key_num % 100).astype(int)
    return out


def prepare_pnadc_batch(
    batch_df: pd.DataFrame,
    bin_shares: pd.DataFrame,
    pof_quintile_edges: np.ndarray,
    *,
    per_quarter_quintiles: bool = False,
    random_seed: int = RANDOM_SEED,
    bin_strategy: str | BinStrategy | None = None,
) -> pd.DataFrame:
    """
    Prepare one PNADC parquet batch for monthly aggregation.

    The returned DataFrame contains only age-eligible rows with non-missing
    monthly keys, non-missing monthly weights, and non-missing UF codes.
    Exclusion and match diagnostics are stored in returned.attrs["diagnostics"].
    """
    df = batch_df.copy()
    raw_n = len(df)
    strategy = BIN_STRATEGY if bin_strategy is None else (
        bin_strategy.value if isinstance(bin_strategy, BinStrategy) else bin_strategy
    )

    ref_key = _parse_ref_month_yyyymm(df["ref_month_yyyymm"])
    month_in_year = pd.to_numeric(df["ref_month_in_year"], errors="coerce")
    weight_monthly = pd.to_numeric(df["weight_monthly"], errors="coerce")
    age = pd.to_numeric(df["V2009"], errors="coerce")
    uf_code = pd.to_numeric(df["UF"], errors="coerce")

    missing_ref = ref_key.isna()
    missing_weight = weight_monthly.isna()
    age_eligible = age >= 15
    missing_uf = uf_code.isna()

    keep = age_eligible & ~missing_ref & ~missing_weight & ~missing_uf
    diagnostics: dict[str, Any] = {
        "n_raw": int(raw_n),
        "n_missing_ref_month": int(missing_ref.sum()),
        "n_missing_weight_monthly": int(missing_weight.sum()),
        "n_excluded_monthly": int((missing_ref | missing_weight).sum()),
        "n_under_15_or_missing_age": int((~age_eligible).sum()),
        "n_missing_uf": int(missing_uf.sum()),
        "excluded_by_month": _exclusions_by_month(ref_key, missing_weight),
    }

    df = df.loc[keep].copy()
    if df.empty:
        diagnostics["n_included"] = 0
        diagnostics["n_unmatched"] = 0
        df.attrs["diagnostics"] = diagnostics
        return df

    ref_kept = ref_key.loc[keep].astype("int64")
    month_from_key = (ref_kept % 100).astype(int)
    month_kept = month_in_year.loc[keep].where(month_in_year.loc[keep].between(1, 12), month_from_key)

    df["ref_month_yyyymm"] = ref_kept.astype(int)
    df["year"] = (ref_kept // 100).astype(int)
    df["month"] = month_kept.astype(int)
    df["uf_code"] = uf_code.loc[keep].astype(int)
    df["age"] = age.loc[keep].astype(float)
    df["sex_code"] = pd.to_numeric(df["V2007"], errors="coerce")
    df["vd3004"] = pd.to_numeric(df["VD3004"], errors="coerce")
    df["weight_monthly"] = weight_monthly.loc[keep].astype(float)

    # V2001 = household member count including children; mirrors POF hh_residents.
    hh_size = pd.to_numeric(df["V2001"], errors="coerce").clip(lower=1).fillna(1)
    rendimento = pd.to_numeric(df["rendimento_habitual_real"], errors="coerce").fillna(0)
    df["pc_income_pnadc"] = rendimento / hh_size

    df["macro_region"] = uf_to_macroregion(df["uf_code"])
    df["age_group"] = age_to_group(df["age"])
    df["gender"] = df["sex_code"].map({1: "male", 2: "female"}).fillna("unknown")
    df["education_group"] = pnadc_education_group(df["vd3004"])
    df["labor_status"] = _pnadc_labor_status_vectorized(df)
    df["labor_status_3way"] = _labor_status_3way(df)

    if per_quarter_quintiles:
        df["pc_income_quintile"] = _per_quarter_quintiles(df)
    else:
        df["pc_income_quintile"] = _income_quintiles_from_pof_edges(
            df["pc_income_pnadc"], pof_quintile_edges
        )

    df["income_band_absolute"] = _income_band_absolute(df["pc_income_pnadc"])
    df["bin_key"] = _build_bin_key(df, strategy=strategy)

    merge_cols = ["bin_key", "p_ph2m", "p_wh2m", "p_ric"]
    dup_mask = bin_shares["bin_key"].duplicated(keep=False)
    if dup_mask.any():
        dup_keys = (
            bin_shares.loc[dup_mask, "bin_key"]
            .drop_duplicates()
            .astype(str)
            .head(5)
            .tolist()
        )
        raise ValueError(
            f"bin_shares has duplicate bin_key values; sample duplicates: {dup_keys}"
        )
    df = df.merge(bin_shares[merge_cols], on="bin_key", how="left")
    df["_unmatched_bin"] = df["p_ph2m"].isna()

    fallback = _fallback_probabilities(bin_shares)
    df["p_ph2m"] = df["p_ph2m"].fillna(fallback["p_ph2m"])
    df["p_wh2m"] = df["p_wh2m"].fillna(fallback["p_wh2m"])
    df["p_ric"] = df["p_ric"].fillna(fallback["p_ric"])

    prob_sum = df["p_ph2m"] + df["p_wh2m"] + df["p_ric"]
    non_unit = prob_sum.notna() & ~np.isclose(prob_sum, 1.0)
    if non_unit.any():
        df.loc[non_unit, ["p_ph2m", "p_wh2m", "p_ric"]] = df.loc[
            non_unit, ["p_ph2m", "p_wh2m", "p_ric"]
        ].div(prob_sum.loc[non_unit], axis=0)

    df["agent_type"] = _deterministic_agent_type(df, random_seed=random_seed)

    diagnostics["n_included"] = int(len(df))
    diagnostics["n_unmatched"] = int(df["_unmatched_bin"].sum())
    df.attrs["diagnostics"] = diagnostics
    return df


# ============================================================================
# Monthly aggregation
# ============================================================================


def _safe_share(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return (numerator / denominator.replace(0, np.nan)).fillna(0.0)


def _monthly_partial_columns() -> list[str]:
    return MONTHLY_KEYS + [
        "total_weight",
        "n_obs",
        "n_unmatched",
        "_w_ph2m",
        "_w_wh2m",
        "_w_ric",
        "share_PH2M",
        "share_WH2M",
        "share_Ricardian",
        "share_H2M",
    ]


def _empty_monthly_partial() -> pd.DataFrame:
    return pd.DataFrame(columns=_monthly_partial_columns())


def _add_share_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["share_PH2M"] = _safe_share(df["_w_ph2m"], df["total_weight"])
    df["share_WH2M"] = _safe_share(df["_w_wh2m"], df["total_weight"])
    df["share_Ricardian"] = _safe_share(df["_w_ric"], df["total_weight"])
    df["share_H2M"] = df["share_PH2M"] + df["share_WH2M"]
    return df


def aggregate_monthly_expected(batch_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate expected probability-weighted state-month shares for one batch."""
    if batch_df.empty:
        return _empty_monthly_partial()

    tmp = batch_df.copy()
    tmp["_w_ph2m"] = tmp["weight_monthly"] * tmp["p_ph2m"]
    tmp["_w_wh2m"] = tmp["weight_monthly"] * tmp["p_wh2m"]
    tmp["_w_ric"] = tmp["weight_monthly"] * tmp["p_ric"]

    out = (
        tmp.groupby(MONTHLY_KEYS, as_index=False)
        .agg(
            total_weight=("weight_monthly", "sum"),
            n_obs=("weight_monthly", "size"),
            n_unmatched=("_unmatched_bin", "sum"),
            _w_ph2m=("_w_ph2m", "sum"),
            _w_wh2m=("_w_wh2m", "sum"),
            _w_ric=("_w_ric", "sum"),
        )
    )
    out["n_obs"] = out["n_obs"].astype(int)
    out["n_unmatched"] = out["n_unmatched"].astype(int)
    return _add_share_columns(out)


def aggregate_monthly_mc(batch_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate realised deterministic Monte Carlo state-month shares for one batch."""
    if batch_df.empty:
        return _empty_monthly_partial()

    tmp = batch_df.copy()
    tmp["_w_ph2m"] = tmp["weight_monthly"] * (tmp["agent_type"] == "PH2M").astype(float)
    tmp["_w_wh2m"] = tmp["weight_monthly"] * (tmp["agent_type"] == "WH2M").astype(float)
    tmp["_w_ric"] = tmp["weight_monthly"] * (tmp["agent_type"] == "Ricardian").astype(float)

    out = (
        tmp.groupby(MONTHLY_KEYS, as_index=False)
        .agg(
            total_weight=("weight_monthly", "sum"),
            n_obs=("weight_monthly", "size"),
            n_unmatched=("_unmatched_bin", "sum"),
            _w_ph2m=("_w_ph2m", "sum"),
            _w_wh2m=("_w_wh2m", "sum"),
            _w_ric=("_w_ric", "sum"),
        )
    )
    out["n_obs"] = out["n_obs"].astype(int)
    out["n_unmatched"] = out["n_unmatched"].astype(int)
    return _add_share_columns(out)


def _combine_monthly_partials(partials: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [p for p in partials if p is not None and not p.empty]
    if not frames:
        return pd.DataFrame(columns=FINAL_MONTHLY_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    out = (
        combined.groupby(MONTHLY_KEYS, as_index=False)
        .agg(
            total_weight=("total_weight", "sum"),
            n_obs=("n_obs", "sum"),
            n_unmatched=("n_unmatched", "sum"),
            _w_ph2m=("_w_ph2m", "sum"),
            _w_wh2m=("_w_wh2m", "sum"),
            _w_ric=("_w_ric", "sum"),
        )
    )
    out = _add_share_columns(out)
    out["n_obs"] = out["n_obs"].astype(int)
    out["n_unmatched"] = out["n_unmatched"].astype(int)
    out = out[FINAL_MONTHLY_COLUMNS]
    return out.sort_values(["year", "month", "uf_code"]).reset_index(drop=True)


def _national_monthly_from_state_month(monthly: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty:
        return pd.DataFrame(
            columns=[
                "ref_month_yyyymm",
                "year",
                "month",
                "n_obs",
                "n_unmatched",
                "total_weight",
                "national_share_PH2M",
                "national_share_WH2M",
                "national_share_Ricardian",
                "national_share_H2M",
            ]
        )

    tmp = monthly.copy()
    tmp["_w_ph2m"] = tmp["share_PH2M"] * tmp["total_weight"]
    tmp["_w_wh2m"] = tmp["share_WH2M"] * tmp["total_weight"]
    tmp["_w_ric"] = tmp["share_Ricardian"] * tmp["total_weight"]
    out = (
        tmp.groupby(["ref_month_yyyymm", "year", "month"], as_index=False)
        .agg(
            n_obs=("n_obs", "sum"),
            n_unmatched=("n_unmatched", "sum"),
            total_weight=("total_weight", "sum"),
            _w_ph2m=("_w_ph2m", "sum"),
            _w_wh2m=("_w_wh2m", "sum"),
            _w_ric=("_w_ric", "sum"),
        )
    )
    out["national_share_PH2M"] = _safe_share(out["_w_ph2m"], out["total_weight"])
    out["national_share_WH2M"] = _safe_share(out["_w_wh2m"], out["total_weight"])
    out["national_share_Ricardian"] = _safe_share(out["_w_ric"], out["total_weight"])
    out["national_share_H2M"] = out["national_share_PH2M"] + out["national_share_WH2M"]
    return out.drop(columns=["_w_ph2m", "_w_wh2m", "_w_ric"])


def _combine_exclusions_by_month(diagnostics: list[dict[str, Any]]) -> pd.DataFrame:
    frames = [
        d.get("excluded_by_month")
        for d in diagnostics
        if d is not None and d.get("excluded_by_month") is not None and not d["excluded_by_month"].empty
    ]
    if not frames:
        return pd.DataFrame(
            columns=[
                "ref_month_yyyymm",
                "year",
                "month",
                "excluded_missing_weight",
                "raw_rows_with_known_month",
            ]
        )

    combined = pd.concat(frames, ignore_index=True)
    out = (
        combined.groupby(["ref_month_yyyymm", "year", "month"], as_index=False)
        .agg(
            excluded_missing_weight=("excluded_missing_weight", "sum"),
            raw_rows_with_known_month=("raw_rows_with_known_month", "sum"),
        )
    )
    return out


def _build_monthly_coverage(
    expected_monthly: pd.DataFrame,
    diagnostics: list[dict[str, Any]],
) -> pd.DataFrame:
    coverage = _national_monthly_from_state_month(expected_monthly)
    exclusions = _combine_exclusions_by_month(diagnostics)

    if coverage.empty and not exclusions.empty:
        coverage = exclusions[["ref_month_yyyymm", "year", "month"]].copy()
    elif not exclusions.empty:
        coverage = coverage.merge(exclusions, on=["ref_month_yyyymm", "year", "month"], how="outer")

    if "excluded_missing_weight" not in coverage.columns:
        coverage["excluded_missing_weight"] = 0
    if "raw_rows_with_known_month" not in coverage.columns:
        coverage["raw_rows_with_known_month"] = 0

    for col in [
        "n_obs",
        "n_unmatched",
        "total_weight",
        "national_share_PH2M",
        "national_share_WH2M",
        "national_share_Ricardian",
        "national_share_H2M",
    ]:
        if col not in coverage.columns:
            coverage[col] = 0
    coverage[
        [
            "n_obs",
            "n_unmatched",
            "excluded_missing_weight",
            "raw_rows_with_known_month",
        ]
    ] = coverage[
        [
            "n_obs",
            "n_unmatched",
            "excluded_missing_weight",
            "raw_rows_with_known_month",
        ]
    ].fillna(0).astype(int)
    coverage["total_weight"] = coverage["total_weight"].fillna(0.0)

    totals = {
        "raw_rows_total": sum(int(d.get("n_raw", 0)) for d in diagnostics),
        "included_rows_total": sum(int(d.get("n_included", 0)) for d in diagnostics),
        "missing_ref_month_total": sum(int(d.get("n_missing_ref_month", 0)) for d in diagnostics),
        "missing_weight_monthly_total": sum(
            int(d.get("n_missing_weight_monthly", 0)) for d in diagnostics
        ),
        "excluded_monthly_total": sum(int(d.get("n_excluded_monthly", 0)) for d in diagnostics),
        "under_15_or_missing_age_total": sum(
            int(d.get("n_under_15_or_missing_age", 0)) for d in diagnostics
        ),
        "missing_uf_total": sum(int(d.get("n_missing_uf", 0)) for d in diagnostics),
        "unmatched_rows_total": sum(int(d.get("n_unmatched", 0)) for d in diagnostics),
        "n_batches": len(diagnostics),
    }
    for col, value in totals.items():
        coverage[col] = value

    coverage["unmatched_share"] = (
        coverage["n_unmatched"] / coverage["n_obs"].replace(0, np.nan)
    ).fillna(0.0)
    coverage["covid_q2q3_2020"] = (
        coverage["ref_month_yyyymm"].astype("Int64").between(202004, 202007).astype(int)
    )
    coverage = coverage.sort_values(["year", "month"]).reset_index(drop=True)
    ordered = [
        "ref_month_yyyymm",
        "year",
        "month",
        "n_obs",
        "n_unmatched",
        "unmatched_share",
        "total_weight",
        "national_share_PH2M",
        "national_share_WH2M",
        "national_share_Ricardian",
        "national_share_H2M",
        "excluded_missing_weight",
        "raw_rows_with_known_month",
        "raw_rows_total",
        "included_rows_total",
        "missing_ref_month_total",
        "missing_weight_monthly_total",
        "excluded_monthly_total",
        "under_15_or_missing_age_total",
        "missing_uf_total",
        "unmatched_rows_total",
        "n_batches",
        "covid_q2q3_2020",
    ]
    return coverage[ordered]


def write_temporal_trend_summary(
    monthly: pd.DataFrame,
    diagnostics_dir: Path = DIAGNOSTICS_DIR,
    *,
    suffix: str = "",
) -> Path:
    """Write annual weight-weighted national HtM shares from state-month output."""
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / f"national_htm_trend_yearly{suffix}.csv"
    if monthly.empty:
        pd.DataFrame(
            columns=[
                "year",
                "total_weight",
                "national_PH2M",
                "national_WH2M",
                "national_Ricardian",
                "national_H2M",
            ]
        ).to_csv(path, index=False)
        return path

    tmp = monthly.dropna(subset=["total_weight"]).copy()
    tmp["_w_ph2m"] = tmp["share_PH2M"] * tmp["total_weight"]
    tmp["_w_wh2m"] = tmp["share_WH2M"] * tmp["total_weight"]
    tmp["_w_ric"] = tmp["share_Ricardian"] * tmp["total_weight"]
    annual = (
        tmp.groupby("year", as_index=False)
        .agg(
            total_weight=("total_weight", "sum"),
            _w_ph2m=("_w_ph2m", "sum"),
            _w_wh2m=("_w_wh2m", "sum"),
            _w_ric=("_w_ric", "sum"),
        )
    )
    denom = annual["total_weight"].replace(0, np.nan)
    annual["national_PH2M"] = annual["_w_ph2m"] / denom
    annual["national_WH2M"] = annual["_w_wh2m"] / denom
    annual["national_Ricardian"] = annual["_w_ric"] / denom
    annual["national_H2M"] = annual["national_PH2M"] + annual["national_WH2M"]
    annual = annual.drop(columns=["_w_ph2m", "_w_wh2m", "_w_ric"])
    annual.to_csv(path, index=False)
    print(f"  Saved temporal trend -> {path}")
    return path


def finalize_monthly_outputs(
    partials: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Combine batch partials into expected, MC, and coverage outputs."""
    expected = _combine_monthly_partials([p["expected"] for p in partials])
    mc = _combine_monthly_partials([p["mc"] for p in partials])
    diagnostics = [p["diagnostics"] for p in partials]
    coverage = _build_monthly_coverage(expected, diagnostics)
    return expected, mc, coverage


# ============================================================================
# PNADC parquet streaming and output
# ============================================================================


def _validate_pnadc_schema(parquet_file: pq.ParquetFile) -> list[str]:
    available = set(parquet_file.schema_arrow.names)
    missing = sorted(set(PNADC_REQUIRED_COLUMNS) - available)
    if missing:
        raise ValueError(f"PNADC parquet is missing required columns: {missing}")
    if not any(col in available for col in PNADC_ID_COLUMNS):
        raise ValueError("PNADC parquet must contain id_rs or id_ind for deterministic MC draws.")
    return [col for col in PNADC_BATCH_COLUMNS if col in available]


def process_pnadc_parquet(
    pnad_path: Path,
    bin_shares: pd.DataFrame,
    pof_quintile_edges: np.ndarray,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    per_quarter_quintiles: bool = False,
    random_seed: int = RANDOM_SEED,
    verbose: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Stream PNADC parquet batches and return finalized monthly outputs."""
    parquet_file = pq.ParquetFile(pnad_path)
    columns = _validate_pnadc_schema(parquet_file)
    total_rows = parquet_file.metadata.num_rows if parquet_file.metadata is not None else None

    if verbose:
        total_msg = f"{total_rows:,}" if total_rows is not None else "unknown"
        print("\n" + "=" * 72)
        print("STEP 3: STREAM PNADC PARQUET & MERGE POF BIN SHARES")
        print("=" * 72)
        print(f"  Input: {pnad_path}")
        print(f"  Parquet rows: {total_msg}")
        print(f"  Batch size: {batch_size:,}")
        if per_quarter_quintiles:
            print("  Using legacy within-batch per-quarter quintiles.")

    partials: list[dict[str, Any]] = []
    processed = 0
    for batch_no, record_batch in enumerate(
        parquet_file.iter_batches(batch_size=batch_size, columns=columns),
        start=1,
    ):
        batch_df = record_batch.to_pandas()
        prepared = prepare_pnadc_batch(
            batch_df,
            bin_shares,
            pof_quintile_edges,
            per_quarter_quintiles=per_quarter_quintiles,
            random_seed=random_seed,
            bin_strategy=BIN_STRATEGY,
        )
        expected_partial = aggregate_monthly_expected(prepared)
        mc_partial = aggregate_monthly_mc(prepared)
        diagnostics = prepared.attrs["diagnostics"]
        partials.append(
            {
                "expected": expected_partial,
                "mc": mc_partial,
                "diagnostics": diagnostics,
            }
        )
        processed += len(batch_df)
        if verbose:
            total_fragment = f" / {total_rows:,}" if total_rows is not None else ""
            print(
                f"  Batch {batch_no}: raw={len(batch_df):,}, "
                f"included={diagnostics['n_included']:,}, "
                f"unmatched={diagnostics['n_unmatched']:,}, "
                f"processed={processed:,}{total_fragment}"
            )

    if not partials:
        return finalize_monthly_outputs([])
    return finalize_monthly_outputs(partials)


def aggregate_monthly_to_legacy_quarterly(monthly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate canonical monthly expected shares to legacy state-quarter shares."""
    if monthly.empty:
        return pd.DataFrame(
            columns=[
                "uf_code",
                "year",
                "quarter",
                "share_PH2M",
                "share_WH2M",
                "share_Ricardian",
                "share_H2M",
                "total_weight",
                "n_obs",
                "n_unmatched",
            ]
        )

    tmp = monthly.copy()
    tmp["quarter"] = ((tmp["month"].astype(int) - 1) // 3 + 1).astype(int)
    tmp["_w_ph2m"] = tmp["share_PH2M"] * tmp["total_weight"]
    tmp["_w_wh2m"] = tmp["share_WH2M"] * tmp["total_weight"]
    tmp["_w_ric"] = tmp["share_Ricardian"] * tmp["total_weight"]
    out = (
        tmp.groupby(["uf_code", "year", "quarter"], as_index=False)
        .agg(
            total_weight=("total_weight", "sum"),
            n_obs=("n_obs", "sum"),
            n_unmatched=("n_unmatched", "sum"),
            _w_ph2m=("_w_ph2m", "sum"),
            _w_wh2m=("_w_wh2m", "sum"),
            _w_ric=("_w_ric", "sum"),
        )
    )
    out = _add_share_columns(out)
    out["n_obs"] = out["n_obs"].astype(int)
    out["n_unmatched"] = out["n_unmatched"].astype(int)
    cols = [
        "uf_code",
        "year",
        "quarter",
        "share_PH2M",
        "share_WH2M",
        "share_Ricardian",
        "share_H2M",
        "total_weight",
        "n_obs",
        "n_unmatched",
    ]
    return out[cols].sort_values(["year", "quarter", "uf_code"]).reset_index(drop=True)


def _write_outputs(
    expected: pd.DataFrame,
    mc: pd.DataFrame,
    coverage: pd.DataFrame,
    *,
    tables_dir: Path = TABLES_DIR,
    diagnostics_dir: Path = DIAGNOSTICS_DIR,
    write_legacy_quarterly: bool = True,
    suffix: str = "",
) -> dict[str, Path]:
    tables_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "monthly_expected": tables_dir / f"state_month_htm_shares{suffix}.parquet",
        "monthly_mc": tables_dir / f"state_month_htm_shares_mc{suffix}.parquet",
        "coverage": diagnostics_dir / f"monthly_htm_coverage{suffix}.csv",
    }
    expected.to_parquet(paths["monthly_expected"], index=False)
    mc.to_parquet(paths["monthly_mc"], index=False)
    coverage.to_csv(paths["coverage"], index=False)

    if write_legacy_quarterly:
        quarterly = aggregate_monthly_to_legacy_quarterly(expected)
        paths["legacy_quarterly"] = tables_dir / f"state_quarter_htm_shares{suffix}.csv"
        quarterly.to_csv(paths["legacy_quarterly"], index=False)

    return paths


def _weighted_national_from_monthly(monthly: pd.DataFrame) -> dict[str, float]:
    total_weight = monthly["total_weight"].sum()
    if total_weight <= 0:
        return {"PH2M": np.nan, "WH2M": np.nan, "Ricardian": np.nan}
    return {
        "PH2M": float((monthly["share_PH2M"] * monthly["total_weight"]).sum() / total_weight),
        "WH2M": float((monthly["share_WH2M"] * monthly["total_weight"]).sum() / total_weight),
        "Ricardian": float(
            (monthly["share_Ricardian"] * monthly["total_weight"]).sum() / total_weight
        ),
    }


def _print_validation_summary(
    pof_national: dict[str, float],
    expected: pd.DataFrame,
    mc: pd.DataFrame,
) -> None:
    expected_nat = _weighted_national_from_monthly(expected)
    mc_nat = _weighted_national_from_monthly(mc)
    summary = pd.DataFrame(
        {
            "Stage": [
                "1. POF Classification",
                "3. PNADC monthly expected",
                "4. PNADC monthly MC diagnostic",
            ],
            "PH2M": [pof_national["p_ph2m"], expected_nat["PH2M"], mc_nat["PH2M"]],
            "WH2M": [pof_national["p_wh2m"], expected_nat["WH2M"], mc_nat["WH2M"]],
            "Ricardian": [pof_national["p_ric"], expected_nat["Ricardian"], mc_nat["Ricardian"]],
        }
    )
    summary["Total"] = summary["PH2M"] + summary["WH2M"] + summary["Ricardian"]

    print("\n" + "=" * 72)
    print("VALIDATION: NATIONAL TYPE SHARES AT EACH STAGE")
    print("=" * 72)
    print(summary.to_string(index=False))


def write_selic_sensitivity(
    selic_grid: tuple[float, ...] = (0.065, 0.09, 0.14),
    diagnostics_dir: Path = DIAGNOSTICS_DIR,
) -> Path:
    """Re-run POF Stage 1 at multiple SELIC rates and write national shares."""
    rows = []
    orig = SELIC_RATE
    try:
        for r in selic_grid:
            globals()["SELIC_RATE"] = r
            _bins, _edges, nat = build_pof_bin_shares(
                diagnostics_dir.parent / "tables",
                diagnostics_dir=diagnostics_dir,
                write_outputs=False,
            )
            rows.append(
                {
                    "selic": r,
                    "p_ph2m": nat["p_ph2m"],
                    "p_wh2m": nat["p_wh2m"],
                    "p_ric": nat["p_ric"],
                }
            )
    finally:
        globals()["SELIC_RATE"] = orig

    out = pd.DataFrame(rows)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    path = diagnostics_dir / "selic_sensitivity.csv"
    out.to_csv(path, index=False)
    print(f"  Saved SELIC sensitivity -> {path}")
    return path


def generate_quarterly_choropleths(state_qtr: pd.DataFrame, output_dir: Path = PLOTS_DIR) -> bool:
    """Generate legacy per-quarter choropleths from a state-quarter DataFrame."""
    try:
        from generate_choropleths import (
            compute_global_vmin_vmax,
            load_ibge_shapefile,
            plot_choropleth,
        )
    except Exception as exc:
        print(f"  Could not import choropleth helpers: {exc}")
        return False

    state_qtr_valid = state_qtr.dropna(subset=["year", "quarter"])
    if state_qtr_valid.empty:
        print("  No valid state-quarter rows for choropleths.")
        return False

    print("\n" + "=" * 72)
    print("STEP 6: CHOROPLETH MAPS")
    print("=" * 72)
    print("  Downloading IBGE state boundaries...")
    try:
        brazil, regions_gdf = load_ibge_shapefile()
    except Exception as exc:
        print(f"  Could not download IBGE shapefile: {exc}")
        print("  Skipping choropleth generation. Run again or use --no-choropleth.")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    vmin_vmax = compute_global_vmin_vmax(state_qtr_valid)
    generated = False
    for (yr, qtr), grp in state_qtr_valid.groupby(["year", "quarter"]):
        yr, qtr = int(yr), int(qtr)
        htm_q = grp.assign(uf_code=lambda d: d["uf_code"].astype(int)).copy()
        htm_q["PH2M"] = htm_q["share_PH2M"]
        htm_q["WH2M"] = htm_q["share_WH2M"]
        htm_q["Ricardian"] = htm_q["share_Ricardian"]
        htm_q["total_HtM"] = htm_q["PH2M"] + htm_q["WH2M"]
        gdf = brazil.merge(
            htm_q[["uf_code", "PH2M", "WH2M", "Ricardian", "total_HtM", "total_weight"]],
            on="uf_code",
            how="left",
        )
        out_png = output_dir / f"choropleth_htm_{yr}Q{qtr}.png"
        plot_choropleth(gdf, regions_gdf, grp, yr, qtr, out_png, vmin_vmax)
        print(f"  Saved {out_png.name}")
        generated = True
    return generated


# ============================================================================
# CLI
# ============================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HTM Agent Classification Pipeline")
    parser.add_argument("--no-choropleth", action="store_true", help="Skip choropleth map generation")
    parser.add_argument(
        "--per-quarter-quintiles",
        action="store_true",
        help=(
            "Use legacy within-batch per-quarter PNADC quintiles instead of "
            "POF cut-points. Default keeps POF cut-points."
        ),
    )
    parser.add_argument(
        "--pnad-parquet",
        type=Path,
        default=None,
        help="Path to PNADC monthly matched parquet (default: pnadc_matched_with_periods.parquet)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"PNADC parquet batch size (default: {DEFAULT_BATCH_SIZE:,})",
    )
    parser.add_argument(
        "--no-legacy-quarterly",
        action="store_true",
        help="Do not write legacy results/tables/state_quarter_htm_shares.csv",
    )
    parser.add_argument(
        "--vehicle-valuation",
        choices=["off", "fipe-proxy"],
        default="fipe-proxy",
        help="Include POF INVENTARIO vehicles in illiquid assets (default: on).",
    )
    parser.add_argument(
        "--write-selic-sensitivity",
        action="store_true",
        help="Run POF Stage 1 across SELIC in {0.065, 0.09, 0.14} and write a sensitivity CSV.",
    )
    parser.add_argument(
        "--bin-strategy",
        choices=["A", "G", "both"],
        default="A",
        help="Bin construction: A=5way labour x quintiles, G=3way labour x absolute BRL bands.",
    )
    parser.add_argument(
        "--canonical-strategy",
        choices=["A", "G"],
        default="A",
        help="When --bin-strategy=both, also write this strategy to canonical unsuffixed filenames.",
    )
    parser.add_argument(
        "--exclude-covid-disruption",
        action="store_true",
        help="Set 202004-202007 shares and weights to missing in monthly outputs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    global USE_VEHICLE_VALUATION, BIN_STRATEGY
    orig_vehicle_valuation = USE_VEHICLE_VALUATION
    orig_bin_strategy = BIN_STRATEGY
    USE_VEHICLE_VALUATION = args.vehicle_valuation == "fipe-proxy"
    try:
        pnad_path = args.pnad_parquet if args.pnad_parquet is not None else PNAD_MATCHED_DEFAULT
        if not pnad_path.exists():
            raise FileNotFoundError(
                f"PNADC Parquet not found: {pnad_path}. Add the file or pass --pnad-parquet PATH."
            )

        bin_strategy = getattr(args, "bin_strategy", "A")
        canonical_strategy = getattr(args, "canonical_strategy", "A")
        strategies = ["A", "G"] if bin_strategy == "both" else [bin_strategy]
        comparison_rows: list[dict[str, float | int | str]] = []
        canonical_expected: pd.DataFrame | None = None
        canonical_paths: dict[str, Path] | None = None

        for strategy in strategies:
            BIN_STRATEGY = strategy
            suffix = f"_{strategy}" if bin_strategy == "both" else ""

            bin_shares, pof_quintile_edges, pof_national = build_pof_bin_shares()
            if bin_strategy == "both":
                TABLES_DIR.mkdir(parents=True, exist_ok=True)
                bin_shares.to_csv(TABLES_DIR / f"pof_bin_shares_{strategy}.csv", index=False)
                if strategy == canonical_strategy:
                    bin_shares.to_csv(TABLES_DIR / "pof_bin_shares.csv", index=False)
            elif strategy != "A":
                TABLES_DIR.mkdir(parents=True, exist_ok=True)
                bin_shares.to_csv(TABLES_DIR / "pof_bin_shares.csv", index=False)
            expected, mc, coverage = process_pnadc_parquet(
                pnad_path,
                bin_shares,
                pof_quintile_edges,
                batch_size=args.batch_size,
                per_quarter_quintiles=args.per_quarter_quintiles,
                random_seed=RANDOM_SEED,
                verbose=True,
            )

            if getattr(args, "exclude_covid_disruption", False):
                covid_cols = [
                    "share_PH2M",
                    "share_WH2M",
                    "share_Ricardian",
                    "share_H2M",
                    "total_weight",
                ]
                expected.loc[expected["ref_month_yyyymm"].between(202004, 202007), covid_cols] = np.nan
                mc.loc[mc["ref_month_yyyymm"].between(202004, 202007), covid_cols] = np.nan
                print("  Excluded COVID Q2-Q3 2020 months from monthly output.")

            print("\n" + "=" * 72)
            print(f"STEP 5: STATE-MONTH HTM SHARES (strategy {strategy})")
            print("=" * 72)
            paths = _write_outputs(
                expected,
                mc,
                coverage,
                write_legacy_quarterly=not args.no_legacy_quarterly,
                suffix=suffix,
            )
            trend_path = write_temporal_trend_summary(expected, suffix=suffix)

            if bin_strategy == "both" and strategy == canonical_strategy:
                canonical_paths = _write_outputs(
                    expected,
                    mc,
                    coverage,
                    write_legacy_quarterly=not args.no_legacy_quarterly,
                    suffix="",
                )
                write_temporal_trend_summary(expected, suffix="")
                print(f"  Saved canonical strategy {strategy} outputs -> {canonical_paths['monthly_expected']}")
                canonical_expected = expected.copy()
            elif bin_strategy != "both":
                canonical_paths = paths
                canonical_expected = expected.copy()

            print(f"  Saved {len(expected):,} monthly expected rows -> {paths['monthly_expected']}")
            print(f"  Saved {len(mc):,} monthly MC diagnostic rows -> {paths['monthly_mc']}")
            print(f"  Saved monthly coverage diagnostics -> {paths['coverage']}")
            print(f"  Saved annual temporal trend -> {trend_path}")
            if "legacy_quarterly" in paths:
                print(f"  Saved legacy quarterly shares -> {paths['legacy_quarterly']}")

            comparison_rows.append(
                {
                    "strategy": strategy,
                    "n_bins": len(bin_shares),
                    "mean_unmatched_share": (
                        float(coverage["unmatched_share"].mean())
                        if "unmatched_share" in coverage.columns
                        else np.nan
                    ),
                    "national_PH2M": pof_national["p_ph2m"],
                    "national_WH2M": pof_national["p_wh2m"],
                    "national_Ricardian": pof_national["p_ric"],
                }
            )

            _print_validation_summary(pof_national, expected, mc)

        if args.write_selic_sensitivity:
            BIN_STRATEGY = canonical_strategy if bin_strategy == "both" else strategies[0]
            write_selic_sensitivity()

        if len(comparison_rows) > 1:
            comp = pd.DataFrame(comparison_rows)
            DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
            comp_path = DIAGNOSTICS_DIR / "bin_strategy_comparison.csv"
            comp.to_csv(comp_path, index=False)
            print(f"\n  Strategy comparison -> {comp_path}")
            print(comp.to_string(index=False))

        choropleth_generated = False
        if not args.no_choropleth and canonical_expected is not None:
            quarterly = aggregate_monthly_to_legacy_quarterly(canonical_expected)
            choropleth_generated = generate_quarterly_choropleths(quarterly, PLOTS_DIR)

        print("\nPipeline complete. Output files:")
        if canonical_paths is not None:
            print(f"  - {canonical_paths['monthly_expected']}")
            print(f"  - {canonical_paths['monthly_mc']}")
            print(f"  - {canonical_paths['coverage']}")
            if "legacy_quarterly" in canonical_paths:
                print(f"  - {canonical_paths['legacy_quarterly']}")
        if choropleth_generated:
            print("  - results/plots/choropleth_htm_*.png")
        return 0
    finally:
        USE_VEHICLE_VALUATION = orig_vehicle_valuation
        BIN_STRATEGY = orig_bin_strategy


if __name__ == "__main__":
    raise SystemExit(main())
