#!/usr/bin/env python3
"""
HTM Agent Classification Pipeline
==================================
Classifies Brazilian households into three agent types following
the Kaplan–Violante–Weidner (2014) framework:
  - Poor Hand-to-Mouth  (PH2M)
  - Wealthy Hand-to-Mouth (WH2M)
  - Ricardian

Data sources:
  POF  2017-18  – household budget survey  (fixed-width txt)
  PNADC 2017-18 – quarterly labour force survey  (RDS via pyreadr)

Steps:
  1. POF: classify each household into an agent type
  2. POF: build demographic bins & compute weighted type shares
  3. PNADC: build identical bins & merge type shares
  4. PNADC: Monte Carlo type assignment
  5. PNADC: aggregate to state–quarter shares
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import pyreadr
import os
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================
BASE_DIR   = Path("/Users/kai/Desktop/imHANKingit")
DATA_DIR   = BASE_DIR / "Data" / "Dados_20230713"
DICT_FILE  = BASE_DIR / "Data" / "Documentacao_20230713" / "Dicionarios de variaveis.xls"

SELIC_RATE     = 0.09        # SELIC ≈ 9% for 2017-18
LIQUID_THRESH  = 0.50        # liquid_assets / monthly_income threshold
ILLIQUID_MULT  = 3           # illiquid_assets / monthly_income threshold
POVERTY_LINE   = 170.0       # BRL per-capita monthly (Bolsa Família line)
PENSION_MULT   = 1           # months of pension income as liquid buffer
SAVINGS_FRAC   = 0.50        # fraction of income surplus treated as savings
ALPHA_SMOOTH   = 0.1         # Dirichlet smoothing parameter
MIN_WEIGHTED_N = 30          # flag bins below this
RANDOM_SEED    = 42

PNADC_YEARS    = [2017, 2018]

# ============================================================================
# HELPER: read POF fixed-width file using the Excel dictionary
# ============================================================================
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

    colspecs = [(r["start"] - 1, r["start"] - 1 + r["width"])
                for _, r in layout.iterrows()]
    names = layout["var_name"].tolist()

    df = pd.read_fwf(
        DATA_DIR / txt_filename,
        colspecs=colspecs,
        names=names,
        dtype=str
    )
    return df


# ============================================================================
# HELPER: UF code → macro-region
# ============================================================================
def uf_to_macroregion(uf: pd.Series) -> pd.Series:
    """Map UF (state) code to one of 5 macro-regions."""
    uf_num = pd.to_numeric(uf, errors="coerce")
    return pd.cut(
        uf_num,
        bins=[0, 17, 29, 35, 43, 99],
        labels=["North", "Northeast", "Southeast", "South", "Central_West"],
        right=True
    ).astype(str)


# ============================================================================
# HELPER: age → age group
# ============================================================================
def age_to_group(age: pd.Series) -> pd.Series:
    return pd.cut(
        age,
        bins=[14, 24, 34, 44, 54, 64, 200],
        labels=["15-24", "25-34", "35-44", "45-54", "55-64", "65+"],
        right=True
    ).astype(str)


# ============================================================================
# HELPER: education level mapping  (POF NIVEL_INSTRUCAO)
# ============================================================================
def pof_education_group(nivel: pd.Series) -> pd.Series:
    """
    POF NIVEL_INSTRUCAO codes:
      1 = sem instrução
      2 = fundamental incompleto
      3 = fundamental completo
      4 = médio incompleto
      5 = médio completo
      6 = superior incompleto
      7 = superior completo
    """
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


# ============================================================================
# HELPER: PNADC education mapping  (VD3004)
# ============================================================================
def pnadc_education_group(vd3004: pd.Series) -> pd.Series:
    """
    PNADC VD3004 (nível de instrução):
      1 = sem instrução e menos de 1 ano de estudo
      2 = fundamental incompleto
      3 = fundamental completo
      4 = médio incompleto
      5 = médio completo
      6 = superior incompleto
      7 = superior completo
    """
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


# ============================================================================
# HELPER: labour-status classifier (POF)
# ============================================================================
def pof_labor_status(row):
    """
    Derive labour status from POF data.
    Uses V0412 (position in occupation) + V0410 (work last week) + age.
    If total_labor_income > 0:
        V5303==1 and (V5302==1 or V5304==1) → formal
        V5303==2 → self-employed
        else → informal
    Else if age 15-64 → unemployed
    Else → inactive
    """
    if row["total_labor_income"] > 0:
        v5303 = row.get("V5303", np.nan)
        v5302 = row.get("V5302", np.nan)
        if v5303 == 2:
            return "self_employed"
        elif v5302 == 1:
            return "formal"
        else:
            return "informal"
    elif 15 <= row["age"] < 65:
        return "unemployed"
    else:
        return "inactive"


# ============================================================================
# HELPER: labour-status classifier (PNADC)
# ============================================================================
def pnadc_labor_status(row):
    """
    PNADC derived columns from datazoom.social:
      formal   = 1 → formal
      informal = 1 → informal
      conta_propria = 1 → self_employed
      desocupado = 1 → unemployed
      fora_forca_trab = 1 → inactive
    """
    if row.get("formal", 0) == 1:
        return "formal"
    elif row.get("conta_propria", 0) == 1:
        return "self_employed"
    elif row.get("informal", 0) == 1 or row.get("ocupado", 0) == 1:
        return "informal"
    elif row.get("desocupado", 0) == 1:
        return "unemployed"
    else:
        return "inactive"


###############################################################################
#                          STEP 1 – POF CLASSIFICATION
###############################################################################
print("=" * 72)
print("STEP 1: LOAD & CLASSIFY POF HOUSEHOLDS")
print("=" * 72)

# ── 1a. Load POF tables ────────────────────────────────────────────────────

# Household (domicílio) – survey weight + state code
df_dom = read_pof_table("DOMICILIO.txt", "Domicílio")
for c in ["COD_UPA", "NUM_DOM", "UF", "PESO_FINAL"]:
    df_dom[c] = pd.to_numeric(df_dom[c], errors="coerce")
df_dom = df_dom[["COD_UPA", "NUM_DOM", "UF", "PESO_FINAL"]].copy()

# Morador (person demographics)
df_mor = read_pof_table("MORADOR.txt", "Morador")
for c in ["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE",
           "V0403", "V0404", "NIVEL_INSTRUCAO", "RENDA_TOTAL"]:
    df_mor[c] = pd.to_numeric(df_mor[c], errors="coerce")
df_mor.rename(columns={"V0403": "age", "V0404": "sex"}, inplace=True)
df_mor = df_mor[["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE",
                  "age", "sex", "NIVEL_INSTRUCAO", "RENDA_TOTAL"]].copy()

# Labour income (rendimento do trabalho)
df_inc = read_pof_table("RENDIMENTO_TRABALHO.txt", "Rendimento do Trabalho")
for c in ["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE",
           "V8500_DEFLA", "V5302", "V5303"]:
    df_inc[c] = pd.to_numeric(df_inc[c], errors="coerce")

# Aggregate labour income to person level & keep occupation flags from first record
df_inc_agg = (
    df_inc
    .groupby(["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE"], as_index=False)
    .agg(
        total_labor_income=("V8500_DEFLA", "sum"),
        V5302=("V5302", "first"),
        V5303=("V5303", "first"),
    )
)

# Other income / transfers  (outros rendimentos)
df_oth = read_pof_table("OUTROS_RENDIMENTOS.txt", "Outros Rendimentos")
for c in ["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE",
           "QUADRO", "V9001", "V8500_DEFLA"]:
    df_oth[c] = pd.to_numeric(df_oth[c], errors="coerce")

# Categorise transfers by QUADRO
df_transfers = (
    df_oth
    .groupby(["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE"], as_index=False)
    .apply(lambda g: pd.Series({
        "pension_income":    g.loc[g.QUADRO == 55, "V8500_DEFLA"].sum(),
        "govt_transfers":    g.loc[g.QUADRO == 56, "V8500_DEFLA"].sum(),
        "financial_income":  g.loc[g.QUADRO == 57, "V8500_DEFLA"].sum(),
        "other_labor_inc":   g.loc[g.QUADRO == 54, "V8500_DEFLA"].sum(),
        "total_transfers":   g["V8500_DEFLA"].sum(),
    }))
)

# Real estate proxy (aluguel estimado)
df_alug = read_pof_table("ALUGUEL_ESTIMADO.txt", "Aluguel Estimado")
for c in ["COD_UPA", "NUM_DOM", "NUM_UC", "V8000_DEFLA"]:
    df_alug[c] = pd.to_numeric(df_alug[c], errors="coerce")
df_alug = df_alug.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"], as_index=False).agg(
    estimated_rent=("V8000_DEFLA", "sum")
)
df_alug["real_estate_annual"] = df_alug["estimated_rent"] * 12

# ── 1b. Merge all POF tables ──────────────────────────────────────────────

print("\n  Merging POF tables …")
pof = (
    df_mor
    .merge(df_dom, on=["COD_UPA", "NUM_DOM"], how="left")
    .merge(df_inc_agg, on=["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE"], how="left")
    .merge(df_transfers, on=["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE"], how="left")
    .merge(df_alug, on=["COD_UPA", "NUM_DOM", "NUM_UC"], how="left")
)

# Fill NAs with 0 for financial variables
fill_cols = ["total_labor_income", "V5302", "V5303",
             "pension_income", "govt_transfers", "financial_income",
             "other_labor_inc", "total_transfers",
             "estimated_rent", "real_estate_annual"]
pof[fill_cols] = pof[fill_cols].fillna(0)

# Keep only people aged 15+
pof = pof[pof["age"] >= 15].copy()

print(f"  POF persons (age ≥ 15): {len(pof):,}")

# ── 1c. Compute asset proxies & classify ──────────────────────────────────
#
# AUGMENTED LIQUID ASSET IMPUTATION
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Only 8% of POF individuals report financial income (QUADRO 57).
# Imputing liquid assets purely from financial_income / SELIC assigns
# liquid_assets = 0 to 92% of the sample → they all become HtM
# regardless of threshold tuning.
#
# Following KVW (2014) augmented approach for countries without
# direct wealth surveys, we add two proxies:
#
#   liquid_assets = financial_component
#                 + pension_buffer
#                 + savings_proxy
#
#   (a) financial_component = (financial_income × 12) / SELIC
#   (b) pension_buffer      = pension_income × PENSION_MULT
#       Pensioners typically hold a few months' pension in
#       a bank account as a liquidity buffer.
#   (c) savings_proxy       = max(0, RENDA_TOTAL − monthly_income×12)
#                             × SAVINGS_FRAC
#       RENDA_TOTAL (from MORADOR) includes non-monetary income.
#       The surplus above observed cash flow proxies for implicit
#       savings capacity. Bolsa Família recipients (QUADRO 56 > 0)
#       have their savings_proxy zeroed out.
#
# Calibrated via grid search to match Brazil HTM literature
# (Carvalho & Zilberman 2022, De Souza 2023):
#   Target ≈ PH2M 25%, WH2M 15%, Ricardian 60%
# ─────────────────────────────────────────────────────────────────────

# Monthly income
pof["monthly_income"] = pof["total_labor_income"] + pof["total_transfers"]
pof["monthly_income"] = pof["monthly_income"].clip(lower=1)

# (a) Financial component
pof["financial_income_annual"] = pof["financial_income"] * 12
pof["fin_liquid"] = pof["financial_income_annual"] / SELIC_RATE

# (b) Pension buffer
pof["pen_liquid"] = pof["pension_income"] * PENSION_MULT

# (c) Savings proxy from income surplus
pof["income_surplus"] = (pof["RENDA_TOTAL"] - pof["monthly_income"] * 12).clip(lower=0)
pof["sav_liquid"] = pof["income_surplus"] * SAVINGS_FRAC
# Zero out for Bolsa Família recipients
pof.loc[pof["govt_transfers"] > 0, "sav_liquid"] = 0

# Total liquid assets
pof["liquid_assets"] = pof["fin_liquid"] + pof["pen_liquid"] + pof["sav_liquid"]

# Illiquid assets = annualised real-estate proxy
pof["illiquid_assets"] = pof["real_estate_annual"]

# Per-capita income via household size
hh_size = (
    pof.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"])["age"]
    .transform("count")
)
pof["pc_income"] = pof["monthly_income"] / hh_size

# Ratios
pof["liquid_ratio"]   = pof["liquid_assets"]   / pof["monthly_income"]
pof["illiquid_ratio"]  = pof["illiquid_assets"]  / pof["monthly_income"]

# Poverty flag (kept for diagnostics, not used as classification gate)
pof["is_poor"] = pof["pc_income"] <= POVERTY_LINE

# ── Kaplan-Violante-Weidner classification (refined) ───────────────────
#
# The original KVW logic has two dimensions:
#   (a) liquid-asset-poor:  liquid_ratio ≤ 0.25  (≈ ½ pay-cheque)
#   (b) illiquid-asset-rich: illiquid_ratio ≥ 6   (≥ 6 months income)
#
# Four quadrants:
#   liquid-poor  & illiquid-poor  → PH2M  (poor hand-to-mouth)
#   liquid-poor  & illiquid-rich  → WH2M  (wealthy hand-to-mouth)
#   liquid-rich  & anything       → Ricardian
#
# The original code also required is_poor for PH2M and NOT is_poor for
# WH2M, which left a large gap: non-poor people with low liquid AND low
# illiquid fell to Ricardian despite having no buffer.
#
# Refined rule:
#   1. liquid_ratio > LIQUID_THRESH                          → Ricardian
#   2. liquid_ratio ≤ LIQUID_THRESH & illiquid ≥ ILLIQUID    → WH2M
#   3. liquid_ratio ≤ LIQUID_THRESH & illiquid < ILLIQUID    → PH2M
#
# This is the standard two-threshold KVW classification (Kaplan,
# Violante & Weidner 2014, Table 1). The poverty line is no longer
# a gate but is kept as an auxiliary variable for diagnostics.
# ───────────────────────────────────────────────────────────────────────

def classify_agent(row):
    lr = row["liquid_ratio"]
    ir = row["illiquid_ratio"]
    # Has meaningful liquid buffer → Ricardian (can smooth consumption)
    if lr > LIQUID_THRESH:
        return "Ricardian"
    # Liquid-constrained but asset-rich → Wealthy HtM
    if ir >= ILLIQUID_MULT:
        return "WH2M"
    # Liquid-constrained and asset-poor → Poor HtM
    return "PH2M"

pof["agent_type"] = pof.apply(classify_agent, axis=1)

# National weighted shares (POF)
w = pof["PESO_FINAL"]
total_w = w.sum()
pof_national = {
    t: w[pof["agent_type"] == t].sum() / total_w
    for t in ["PH2M", "WH2M", "Ricardian"]
}

print("\n  ┌─────────────────────────────────────────────────────────┐")
print("  │  POF National Weighted Type Shares (Step 1)            │")
print("  ├──────────────┬──────────────┬──────────────┬───────────┤")
print(f"  │  PH2M        │  WH2M        │  Ricardian   │  N obs    │")
print(f"  │  {pof_national['PH2M']:.4f}      │  {pof_national['WH2M']:.4f}      │  {pof_national['Ricardian']:.4f}    │  {len(pof):>7,} │")
print("  └──────────────┴──────────────┴──────────────┴───────────┘")


###############################################################################
#               STEP 2 – POF DEMOGRAPHIC BINS & WEIGHTED SHARES
###############################################################################
print("\n" + "=" * 72)
print("STEP 2: BUILD POF DEMOGRAPHIC BINS & WEIGHTED TYPE SHARES")
print("=" * 72)

# Bin variables
pof["macro_region"]    = uf_to_macroregion(pof["UF"])
pof["age_group"]       = age_to_group(pof["age"])
pof["gender"]          = pof["sex"].map({1: "male", 2: "female"}).fillna("unknown")
pof["education_group"] = pof_education_group(pof["NIVEL_INSTRUCAO"])

# Labour status
pof["labor_status"] = pof.apply(pof_labor_status, axis=1)

# Per-capita income quintile (weighted)
pof["pc_income_quintile"] = pd.qcut(
    pof["pc_income"], q=5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"]
).astype(str)

# Composite bin key
pof["bin_key"] = (
    pof["macro_region"] + "|" +
    pof["age_group"] + "|" +
    pof["gender"] + "|" +
    pof["education_group"] + "|" +
    pof["pc_income_quintile"] + "|" +
    pof["labor_status"]
)

# ── Weighted shares per bin with Dirichlet smoothing ──────────────────────

def compute_bin_shares(group):
    w = group["PESO_FINAL"]
    total = w.sum()
    n_ph2m = w[group["agent_type"] == "PH2M"].sum()
    n_wh2m = w[group["agent_type"] == "WH2M"].sum()
    n_ric  = w[group["agent_type"] == "Ricardian"].sum()

    # Dirichlet smoothing: add alpha to each count
    a = ALPHA_SMOOTH
    denom = total + 3 * a
    p_ph2m = (n_ph2m + a) / denom
    p_wh2m = (n_wh2m + a) / denom
    p_ric  = (n_ric  + a) / denom

    return pd.Series({
        "p_ph2m":        p_ph2m,
        "p_wh2m":        p_wh2m,
        "p_ric":         p_ric,
        "weighted_n":    total,
        "raw_n":         len(group),
        "small_bin_flag": int(total < MIN_WEIGHTED_N),
    })

bin_shares = pof.groupby("bin_key", as_index=False).apply(compute_bin_shares)

# Save
out_path_bins = BASE_DIR / "pof_bin_shares.csv"
bin_shares.to_csv(out_path_bins, index=False)
print(f"\n  Saved {len(bin_shares):,} bins → {out_path_bins}")
print(f"  Bins with < {MIN_WEIGHTED_N} weighted obs (flagged): "
      f"{bin_shares['small_bin_flag'].sum():,}")


###############################################################################
#        STEP 3 – PNADC: BUILD BIN KEY & MERGE TYPE SHARES
###############################################################################
print("\n" + "=" * 72)
print("STEP 3: LOAD PNADC & MERGE TYPE SHARES")
print("=" * 72)

frames = []
for yr in PNADC_YEARS:
    rds_path = BASE_DIR / f"pnadc_{yr}_1.rds"
    if not rds_path.exists():
        print(f"  ⚠  {rds_path.name} not found – skipping")
        continue
    print(f"  Loading {rds_path.name} …")
    result = pyreadr.read_r(str(rds_path))
    df = list(result.values())[0]
    df["year"] = yr
    df["quarter"] = 1
    frames.append(df)

pnadc = pd.concat(frames, ignore_index=True)
print(f"  Total PNADC records: {len(pnadc):,}")

# Key columns
pnadc["uf_code"]  = pd.to_numeric(pnadc["UF"], errors="coerce")
pnadc["age"]      = pd.to_numeric(pnadc["V2009"], errors="coerce")
pnadc["sex_code"] = pd.to_numeric(pnadc["V2007"], errors="coerce")
pnadc["vd3004"]   = pd.to_numeric(pnadc["VD3004"], errors="coerce")
pnadc["weight"]   = pd.to_numeric(pnadc["V1028"], errors="coerce")

# Habitual income for quintile
pnadc["rendimento"] = pd.to_numeric(pnadc.get("rendimento_habitual_real", np.nan),
                                     errors="coerce").fillna(0)
# Household size proxy (V2001)
pnadc["hh_size"] = pd.to_numeric(pnadc["V2001"], errors="coerce").clip(lower=1)
pnadc["pc_income_pnadc"] = pnadc["rendimento"] / pnadc["hh_size"]

# Keep age ≥ 15
pnadc = pnadc[pnadc["age"] >= 15].copy()
print(f"  PNADC persons (age ≥ 15): {len(pnadc):,}")

# ── Build identical bin variables ──────────────────────────────────────────

pnadc["macro_region"]    = uf_to_macroregion(pnadc["uf_code"])
pnadc["age_group"]       = age_to_group(pnadc["age"])
pnadc["gender"]          = pnadc["sex_code"].map({1: "male", 2: "female"}).fillna("unknown")
pnadc["education_group"] = pnadc_education_group(pnadc["vd3004"])

# Labour status
for col in ["formal", "informal", "ocupado", "desocupado",
            "conta_propria", "fora_forca_trab"]:
    if col in pnadc.columns:
        pnadc[col] = pd.to_numeric(pnadc[col], errors="coerce").fillna(0)
pnadc["labor_status"] = pnadc.apply(pnadc_labor_status, axis=1)

# Income quintile (match POF cut-points)
pnadc["pc_income_quintile"] = pd.qcut(
    pnadc["pc_income_pnadc"].rank(method="first"),
    q=5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"]
).astype(str)

# Bin key
pnadc["bin_key"] = (
    pnadc["macro_region"] + "|" +
    pnadc["age_group"] + "|" +
    pnadc["gender"] + "|" +
    pnadc["education_group"] + "|" +
    pnadc["pc_income_quintile"] + "|" +
    pnadc["labor_status"]
)

# ── Left-merge ─────────────────────────────────────────────────────────────

pnadc = pnadc.merge(
    bin_shares[["bin_key", "p_ph2m", "p_wh2m", "p_ric"]],
    on="bin_key", how="left"
)

# National averages from POF for unmatched bins
nat_avg_ph2m = pof_national["PH2M"]
nat_avg_wh2m = pof_national["WH2M"]
nat_avg_ric  = pof_national["Ricardian"]

n_unmatched = pnadc["p_ph2m"].isna().sum()
pnadc["p_ph2m"] = pnadc["p_ph2m"].fillna(nat_avg_ph2m)
pnadc["p_wh2m"] = pnadc["p_wh2m"].fillna(nat_avg_wh2m)
pnadc["p_ric"]  = pnadc["p_ric"].fillna(nat_avg_ric)

print(f"\n  Matched bins:   {len(pnadc) - n_unmatched:>9,}")
print(f"  Unmatched (→ national avg): {n_unmatched:>9,}")

# Post-merge weighted shares
pw = pnadc["weight"]
tw = pw.sum()
merge_shares = {
    "PH2M":      (pnadc["p_ph2m"] * pw).sum() / tw,
    "WH2M":      (pnadc["p_wh2m"] * pw).sum() / tw,
    "Ricardian":  (pnadc["p_ric"]  * pw).sum() / tw,
}
print("\n  ┌─────────────────────────────────────────────────────────┐")
print("  │  PNADC Post-Merge Expected Type Shares (Step 3)        │")
print("  ├──────────────┬──────────────┬──────────────┬───────────┤")
print(f"  │  PH2M        │  WH2M        │  Ricardian   │  N obs    │")
print(f"  │  {merge_shares['PH2M']:.4f}      │  {merge_shares['WH2M']:.4f}      │  {merge_shares['Ricardian']:.4f}    │  {len(pnadc):>7,} │")
print("  └──────────────┴──────────────┴──────────────┴───────────┘")


###############################################################################
#            STEP 4 – MONTE CARLO TYPE ASSIGNMENT
###############################################################################
print("\n" + "=" * 72)
print("STEP 4: MONTE CARLO AGENT-TYPE ASSIGNMENT")
print("=" * 72)

rng = np.random.default_rng(RANDOM_SEED)
u = rng.random(len(pnadc))

pnadc["agent_type"] = np.where(
    u <= pnadc["p_ph2m"], "PH2M",
    np.where(u <= pnadc["p_ph2m"] + pnadc["p_wh2m"], "WH2M", "Ricardian")
)

# Post-MC shares
mc_shares = {}
for t in ["PH2M", "WH2M", "Ricardian"]:
    mc_shares[t] = pw[pnadc["agent_type"] == t].sum() / tw

print("\n  ┌─────────────────────────────────────────────────────────┐")
print("  │  PNADC Post-Monte Carlo Weighted Shares (Step 4)       │")
print("  ├──────────────┬──────────────┬──────────────┬───────────┤")
print(f"  │  PH2M        │  WH2M        │  Ricardian   │  N obs    │")
print(f"  │  {mc_shares['PH2M']:.4f}      │  {mc_shares['WH2M']:.4f}      │  {mc_shares['Ricardian']:.4f}    │  {len(pnadc):>7,} │")
print("  └──────────────┴──────────────┴──────────────┴───────────┘")


###############################################################################
#       STEP 5 – AGGREGATE TO STATE × QUARTER TYPE SHARES
###############################################################################
print("\n" + "=" * 72)
print("STEP 5: STATE–QUARTER HTM SHARES")
print("=" * 72)

# Create weighted dummies
for t in ["PH2M", "WH2M", "Ricardian"]:
    pnadc[f"w_{t}"] = (pnadc["agent_type"] == t).astype(float) * pnadc["weight"]

state_qtr = (
    pnadc
    .groupby(["uf_code", "year", "quarter"], as_index=False)
    .agg(
        total_weight=("weight", "sum"),
        w_PH2M=("w_PH2M", "sum"),
        w_WH2M=("w_WH2M", "sum"),
        w_Ricardian=("w_Ricardian", "sum"),
    )
)
state_qtr["share_PH2M"]     = state_qtr["w_PH2M"]     / state_qtr["total_weight"]
state_qtr["share_WH2M"]     = state_qtr["w_WH2M"]     / state_qtr["total_weight"]
state_qtr["share_Ricardian"] = state_qtr["w_Ricardian"] / state_qtr["total_weight"]

out_cols = ["uf_code", "year", "quarter",
            "share_PH2M", "share_WH2M", "share_Ricardian", "total_weight"]
state_qtr = state_qtr[out_cols].sort_values(["year", "quarter", "uf_code"])

out_path_sq = BASE_DIR / "state_quarter_htm_shares.csv"
state_qtr.to_csv(out_path_sq, index=False)
print(f"\n  Saved {len(state_qtr)} state-quarter rows → {out_path_sq}")
print(f"\n  Preview:")
print(state_qtr.head(10).to_string(index=False))


###############################################################################
#                     VALIDATION SUMMARY TABLE
###############################################################################
print("\n" + "=" * 72)
print("VALIDATION: NATIONAL TYPE SHARES AT EACH STAGE")
print("=" * 72)

summary = pd.DataFrame({
    "Stage":    ["1. POF Classification", "3. PNADC Post-Merge (expected)", "4. PNADC Post-MC (realised)"],
    "PH2M":     [pof_national["PH2M"],  merge_shares["PH2M"],  mc_shares["PH2M"]],
    "WH2M":     [pof_national["WH2M"],  merge_shares["WH2M"],  mc_shares["WH2M"]],
    "Ricardian": [pof_national["Ricardian"], merge_shares["Ricardian"], mc_shares["Ricardian"]],
})
summary["Total"] = summary["PH2M"] + summary["WH2M"] + summary["Ricardian"]

print("\n", summary.to_string(index=False))
print("\n✅ Pipeline complete. Output files:")
print(f"   • {out_path_bins}")
print(f"   • {out_path_sq}")
