#!/usr/bin/env python3
"""
Build guide-aligned Brazil wealth proxy panel at state-month frequency.

Primary output:
  wealth/panel/main_panel_27uf_monthly.csv

The build order follows wealth/brazil_wealth_data_guide.md:
1) ESTBAN month-level state aggregation from wealth/bcb_data (base frame)
2) PF credit merge from wealth/Credit_long_month_state.csv
3) Optional merges for IPCA / population / PNAD if files are available
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEALTH_DIR = PROJECT_ROOT / "wealth"
BCB_DATA_DIR = WEALTH_DIR / "bcb_data"
PANEL_DIR = WEALTH_DIR / "panel"

UF_NAME_TO_CODE = {
    "acre": 12,
    "alagoas": 27,
    "amapa": 16,
    "amazonas": 13,
    "bahia": 29,
    "ceara": 23,
    "distrito federal": 53,
    "espirito santo": 32,
    "goias": 52,
    "maranhao": 21,
    "mato grosso": 51,
    "mato grosso do sul": 50,
    "minas gerais": 31,
    "para": 15,
    "paraiba": 25,
    "parana": 41,
    "pernambuco": 26,
    "piaui": 22,
    "rio de janeiro": 33,
    "rio grande do norte": 24,
    "rio grande do sul": 43,
    "rondonia": 11,
    "roraima": 14,
    "santa catarina": 42,
    "sao paulo": 35,
    "sergipe": 28,
    "tocantins": 17,
}


def _normalize_text(value: str) -> str:
    txt = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"\s+", " ", txt).strip().lower()
    return txt


def build_estban_state_monthly() -> pd.DataFrame:
    files = sorted(BCB_DATA_DIR.glob("*_ESTBAN.CSV"))
    if not files:
        raise FileNotFoundError(f"No ESTBAN CSV files found under {BCB_DATA_DIR}")

    frames: list[pd.DataFrame] = []
    for path in files:
        df = pd.read_csv(path, sep=";", encoding="latin1", skiprows=2)
        if "#DATA_BASE" not in df.columns or "UF" not in df.columns:
            continue

        for col in [
            "VERBETE_401_SERVICOS_PUBLICOS + VERBETE_402_ATIVIDADES_EMPRESARIAIS + VERBETE_403_ESPECIAIS_DO_TESOURO_NACIONAL + VERBETE_404_SALDOS_CREDORES_EM_CONTAS_DE_EMPRESTIMOS_E_FINAN + VERBETE_411_DE_PESSOAS_FISICAS + VERBETE_412_DE_PESSOAS_JURIDICAS + VERBETE_413_DE_INSTITUICOES_FINANCEIRAS + VERBETE_414_JUDICIAIS + VERBETE_415_OBRIGATORIOS + VERBETE_416_PARA_INVESTIMENTOS + VERBETE_417_VINCULADOS + VERBETE_418_DEMAIS_DEPOSITOS + VERBETE_419_SLD_CRED_CTAS_EMPR_FINANC_OUTR",
            "VERBETE_420_DEPOSITOS_DE_POUPANCA",
            "VERBETE_432_DEPOSITOS_A_PRAZO",
            "VERBETE_160_OPERACOES_DE_CREDITO",
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = np.nan

        keep = df[
            [
                "#DATA_BASE",
                "UF",
                "VERBETE_401_SERVICOS_PUBLICOS + VERBETE_402_ATIVIDADES_EMPRESARIAIS + VERBETE_403_ESPECIAIS_DO_TESOURO_NACIONAL + VERBETE_404_SALDOS_CREDORES_EM_CONTAS_DE_EMPRESTIMOS_E_FINAN + VERBETE_411_DE_PESSOAS_FISICAS + VERBETE_412_DE_PESSOAS_JURIDICAS + VERBETE_413_DE_INSTITUICOES_FINANCEIRAS + VERBETE_414_JUDICIAIS + VERBETE_415_OBRIGATORIOS + VERBETE_416_PARA_INVESTIMENTOS + VERBETE_417_VINCULADOS + VERBETE_418_DEMAIS_DEPOSITOS + VERBETE_419_SLD_CRED_CTAS_EMPR_FINANC_OUTR",
                "VERBETE_420_DEPOSITOS_DE_POUPANCA",
                "VERBETE_432_DEPOSITOS_A_PRAZO",
                "VERBETE_160_OPERACOES_DE_CREDITO",
            ]
        ].copy()
        keep.columns = [
            "yyyymm",
            "uf",
            "dep_401_nominal",
            "dep_420_nominal",
            "dep_432_nominal",
            "credit_160_nominal",
        ]
        frames.append(keep)

    estban = pd.concat(frames, ignore_index=True)
    estban["uf"] = estban["uf"].astype(str).str.strip().str.upper()
    estban["yyyymm"] = pd.to_numeric(estban["yyyymm"], errors="coerce").astype("Int64")
    estban = estban.dropna(subset=["yyyymm"])
    estban["year"] = (estban["yyyymm"] // 100).astype(int)
    estban["month_num"] = (estban["yyyymm"] % 100).astype(int)

    # Guide target is deposit-account based. In this vintage, explicit deposit
    # lines are available for 420 (poupanca) and 432 (a prazo). We keep the
    # broader 401 aggregate separately for diagnostics only.
    estban["deposits_nominal"] = estban["dep_420_nominal"].fillna(0.0) + estban["dep_432_nominal"].fillna(0.0)
    estban["deposits_nominal_broad401"] = (
        estban["dep_401_nominal"].fillna(0.0)
        + estban["dep_420_nominal"].fillna(0.0)
        + estban["dep_432_nominal"].fillna(0.0)
    )

    grouped = (
        estban.groupby(["uf", "year", "month_num"], as_index=False)
        .agg(
            deposits_nominal=("deposits_nominal", "sum"),
            deposits_nominal_broad401=("deposits_nominal_broad401", "sum"),
            estban_credit_nominal=("credit_160_nominal", "sum"),
        )
        .sort_values(["uf", "year", "month_num"])
        .reset_index(drop=True)
    )
    return grouped


def build_pf_credit_state_monthly() -> pd.DataFrame:
    path = WEALTH_DIR / "Credit_long_month_state.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing PF credit file: {path}")

    df = pd.read_csv(path)
    df["borrower_type_norm"] = df["borrower_type"].map(_normalize_text)
    df = df[df["borrower_type_norm"] == "individual persons"].copy()
    if df.empty:
        raise ValueError("No 'Individual persons' rows found in Credit_long_month_state.csv")

    dt = pd.to_datetime(df["Date"], format="%m/%Y", errors="coerce")
    df = df[dt.notna()].copy()
    df["year"] = dt[dt.notna()].dt.year.values
    df["month_num"] = dt[dt.notna()].dt.month.values
    df["uf_code"] = df["state"].map(lambda s: UF_NAME_TO_CODE.get(_normalize_text(s)))
    df = df.dropna(subset=["uf_code"])
    df["uf_code"] = df["uf_code"].astype(int)
    df["pf_credit_nominal"] = pd.to_numeric(df["value_million_brl"], errors="coerce") * 1_000_000.0

    out = (
        df.groupby(["uf_code", "year", "month_num"], as_index=False)["pf_credit_nominal"]
        .sum()
        .sort_values(["uf_code", "year", "month_num"])
        .reset_index(drop=True)
    )
    return out


def try_load_ipca() -> pd.DataFrame | None:
    path = WEALTH_DIR / "ipca" / "raw" / "ipca_national_monthly.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    cols = {_normalize_text(c): c for c in df.columns}
    month_col = cols.get("month") or cols.get("date")
    ipca_col = cols.get("ipca") or cols.get("index")
    if not month_col or not ipca_col:
        return None
    dt = pd.to_datetime(df[month_col], errors="coerce")
    out = pd.DataFrame(
        {
            "year": dt.dt.year,
            "month_num": dt.dt.month,
            "ipca_index": pd.to_numeric(df[ipca_col], errors="coerce"),
        }
    ).dropna(subset=["year", "month_num", "ipca_index"])
    return out


def try_load_population() -> pd.DataFrame | None:
    path = WEALTH_DIR / "population" / "raw" / "pop_estimates_uf_annual.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    cols = {_normalize_text(c): c for c in df.columns}
    uf_col = cols.get("uf_code") or cols.get("uf")
    year_col = cols.get("year")
    pop_col = cols.get("population") or cols.get("pop")
    if not (uf_col and year_col and pop_col):
        return None
    annual = df[[uf_col, year_col, pop_col]].copy()
    annual.columns = ["uf_code", "year", "population"]
    annual["uf_code"] = pd.to_numeric(annual["uf_code"], errors="coerce")
    annual["year"] = pd.to_numeric(annual["year"], errors="coerce")
    annual["population"] = pd.to_numeric(annual["population"], errors="coerce")
    annual = annual.dropna()
    annual["uf_code"] = annual["uf_code"].astype(int)
    annual["year"] = annual["year"].astype(int)
    return annual


def build_main_panel() -> pd.DataFrame:
    estban = build_estban_state_monthly()
    estban["uf_code"] = estban["uf"].map(
        {
            "RO": 11,
            "AC": 12,
            "AM": 13,
            "RR": 14,
            "PA": 15,
            "AP": 16,
            "TO": 17,
            "MA": 21,
            "PI": 22,
            "CE": 23,
            "RN": 24,
            "PB": 25,
            "PE": 26,
            "AL": 27,
            "SE": 28,
            "BA": 29,
            "MG": 31,
            "ES": 32,
            "RJ": 33,
            "SP": 35,
            "PR": 41,
            "SC": 42,
            "RS": 43,
            "MS": 50,
            "MT": 51,
            "GO": 52,
            "DF": 53,
        }
    )
    estban = estban.dropna(subset=["uf_code"]).copy()
    estban["uf_code"] = estban["uf_code"].astype(int)

    panel = estban.sort_values(["uf_code", "year", "month_num"]).reset_index(drop=True)
    credit = build_pf_credit_state_monthly()
    panel = panel.merge(credit, on=["uf_code", "year", "month_num"], how="left")

    ipca = try_load_ipca()
    if ipca is not None:
        panel = panel.merge(ipca, on=["year", "month_num"], how="left")
    else:
        panel["ipca_index"] = np.nan

    pop = try_load_population()
    if pop is not None:
        panel = panel.merge(pop, on=["uf_code", "year"], how="left")
    else:
        panel["population"] = np.nan

    panel["deposits_pc_nominal"] = panel["deposits_nominal"] / panel["population"]
    panel["pf_credit_pc_nominal"] = panel["pf_credit_nominal"] / panel["population"]
    panel["deflator"] = panel["ipca_index"] / 100.0
    panel["deposits_pc_real"] = panel["deposits_pc_nominal"] / panel["deflator"]
    panel["pf_credit_pc_real"] = panel["pf_credit_pc_nominal"] / panel["deflator"]

    # Guide-aligned wealth proxy (firm contamination caveat applies).
    panel["net_liquid_proxy"] = panel["deposits_pc_real"] - panel["pf_credit_pc_real"]

    panel["ref_month_yyyymm"] = panel["year"] * 100 + panel["month_num"]
    panel = panel.sort_values(["uf_code", "year", "month_num"]).reset_index(drop=True)
    return panel


def main() -> None:
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    panel = build_main_panel()

    out = PANEL_DIR / "main_panel_27uf_monthly.csv"
    panel.to_csv(out, index=False)

    estban_out = PANEL_DIR / "estban_state_monthly.csv"
    panel[
        ["uf_code", "year", "month_num", "ref_month_yyyymm", "deposits_nominal", "estban_credit_nominal"]
    ].to_csv(estban_out, index=False)

    print(f"Saved main panel: {out} ({len(panel):,} rows)")
    print(f"Saved ESTBAN state-month extract: {estban_out}")
    print(
        "Coverage:",
        f"{panel['uf_code'].nunique()} UFs,",
        f"{panel['year'].min()}-{panel['year'].max()}",
    )

    lp_path = PROJECT_ROOT / "results" / "datasets" / "basic_state_month_lp" / "state_month_lp_dataset.csv"
    if lp_path.exists():
        lp = pd.read_csv(lp_path)
        wealth_cols = [
            "uf_code",
            "year",
            "month_num",
            "deposits_nominal",
            "deposits_nominal_broad401",
            "estban_credit_nominal",
            "pf_credit_nominal",
            "ref_month_yyyymm",
        ]
        merged = lp.merge(
            panel[wealth_cols].rename(columns={"month_num": "month"}),
            on=["uf_code", "year", "month"],
            how="left",
            suffixes=("", "_wealth"),
        )

        for col in [
            "deposits_nominal",
            "deposits_nominal_broad401",
            "estban_credit_nominal",
            "pf_credit_nominal",
            "ref_month_yyyymm",
        ]:
            wcol = f"{col}_wealth"
            if wcol in merged.columns:
                merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(
                    pd.to_numeric(merged[wcol], errors="coerce")
                )
                merged = merged.drop(columns=[wcol])

        # Keep compatibility with existing workflow variables and maximize PF
        # credit coverage before derived proxy calculations.
        if "credit_pf" in merged.columns:
            merged["credit_pf"] = pd.to_numeric(merged["credit_pf"], errors="coerce").fillna(
                pd.to_numeric(merged["pf_credit_nominal"], errors="coerce")
            )
            merged["pf_credit_nominal"] = pd.to_numeric(merged["pf_credit_nominal"], errors="coerce").fillna(
                pd.to_numeric(merged["credit_pf"], errors="coerce")
            )

        pop = pd.to_numeric(merged["population"], errors="coerce")
        ipca = pd.to_numeric(merged["ipca_index"], errors="coerce")
        deflator = ipca / 100.0
        merged["deposits_pc_nominal"] = pd.to_numeric(merged["deposits_nominal"], errors="coerce") / pop
        merged["pf_credit_pc_nominal"] = pd.to_numeric(merged["pf_credit_nominal"], errors="coerce") / pop
        merged["deposits_pc_real"] = merged["deposits_pc_nominal"] / deflator
        merged["pf_credit_pc_real"] = merged["pf_credit_pc_nominal"] / deflator
        merged["net_liquid_proxy"] = merged["deposits_pc_real"] - merged["pf_credit_pc_real"]
        if "log_credit_pf" in merged.columns:
            c = pd.to_numeric(merged["credit_pf"], errors="coerce")
            merged["log_credit_pf"] = np.where(c > 0, np.log(c), np.nan)

        merged.to_csv(lp_path, index=False)
        print(f"Updated LP dataset with wealth proxy fields: {lp_path}")


if __name__ == "__main__":
    main()
