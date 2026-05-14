#!/usr/bin/env python3
"""Prepare external monthly controls for HANK validation.

Inputs (defaults point to files already present in this repo):
- PNAD-C matched panel: pnadc_matched_with_periods.parquet
- POF folder: Data/Dados_20230713
- PMC retail by UF CSV dump (SIDRA table 8880 export)
- SELIC monthly CSV (SGS 4189 export)
- IPCA monthly XLSX (table 1737 export)

Optional:
- Download and aggregate SCR.data yearly ZIP files from BCB.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable
from urllib.request import urlopen

import pandas as pd


UF_CODE_TO_SIGLA = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
    21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL",
    28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR",
    42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}

SIGLA_TO_UF_CODE = {v: k for k, v in UF_CODE_TO_SIGLA.items()}

PT_MONTH = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def parse_month_label_pt(label: str) -> pd.Timestamp:
    label = label.strip().lower()
    m = re.match(r"([a-zçãé]+)\s+(\d{4})", label)
    if not m:
        raise ValueError(f"Unexpected month label: {label}")
    month_name, year_str = m.group(1), m.group(2)
    month = PT_MONTH[month_name]
    year = int(year_str)
    return pd.Timestamp(year=year, month=month, day=1)


def parse_sidra_pmc_export(path: Path) -> pd.DataFrame:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        raise ValueError(f"Empty PMC file: {path}")

    start_idx = None
    for i, r in enumerate(rows):
        if r and r[0].startswith("Variável - PMC - Número-índice (2022=100)"):
            start_idx = i
            break
    if start_idx is None:
        raise ValueError("Could not find base number-index section in PMC file.")

    months_row = rows[start_idx + 2]
    months = [c.strip() for c in months_row[2:] if c.strip()]
    month_dates = [parse_month_label_pt(m) for m in months]

    records = []
    i = start_idx + 4
    while i < len(rows):
        r = rows[i]
        if r and r[0].startswith("Variável - PMC - "):
            break
        if len(r) < 3:
            i += 1
            continue
        code = r[0].strip().replace('"', "")
        if not code.isdigit():
            i += 1
            continue
        uf_code = int(code)
        if uf_code not in UF_CODE_TO_SIGLA:
            i += 1
            continue
        vals = r[2 : 2 + len(month_dates)]
        for d, v in zip(month_dates, vals):
            vv = (v or "").strip().replace(",", ".")
            if vv in {"", "-", "..."}:
                continue
            try:
                val = float(vv)
            except ValueError:
                continue
            records.append(
                {
                    "uf_code": uf_code,
                    "date": d,
                    "year": d.year,
                    "month": d.month,
                    "pmc_retail_nominal_index": val,
                }
            )
        i += 1

    out = pd.DataFrame(records).sort_values(["uf_code", "date"])
    if out.empty:
        raise ValueError("Parsed PMC output is empty.")
    return out


def parse_selic_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", decimal=",")
    df["date"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    out = (
        df.rename(columns={"valor": "selic_aa_pct"})[["date", "year", "month", "selic_aa_pct"]]
        .sort_values("date")
        .reset_index(drop=True)
    )
    return out


def parse_ipca_xlsx(path: Path) -> pd.DataFrame:
    # Table 2 in this export is monthly variation (%), row with code 1 is Brasil.
    df = pd.read_excel(path, sheet_name="Tabela 2", header=None)
    month_row_idx = None
    for i in range(len(df)):
        row_vals = [str(x).lower() for x in df.iloc[i, :].tolist() if not pd.isna(x)]
        if any(re.match(r"janeiro\s+\d{4}", v) for v in row_vals):
            month_row_idx = i
            break
    if month_row_idx is None:
        raise ValueError("Could not find month header row in IPCA workbook.")

    data_row_idx = None
    for i in range(month_row_idx + 1, min(month_row_idx + 8, len(df))):
        c1 = str(df.iloc[i, 1]).strip().lower() if not pd.isna(df.iloc[i, 1]) else ""
        c0 = str(df.iloc[i, 0]).strip() if not pd.isna(df.iloc[i, 0]) else ""
        if c1 == "brasil" or c0 == "1":
            data_row_idx = i
            break
    if data_row_idx is None:
        raise ValueError("Could not find Brasil data row in IPCA workbook.")

    months_raw = df.iloc[month_row_idx, :].tolist()
    values_raw = df.iloc[data_row_idx, :].tolist()
    records = []
    for m, v in zip(months_raw, values_raw):
        if pd.isna(m) or pd.isna(v):
            continue
        try:
            d = parse_month_label_pt(str(m))
        except Exception:
            continue
        try:
            vv = float(str(v).replace(",", "."))
        except Exception:
            continue
        records.append(
            {
                "date": d,
                "year": d.year,
                "month": d.month,
                "ipca_mom_pct": vv,
            }
        )
    out = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    if out.empty:
        raise ValueError("Parsed IPCA output is empty.")
    return out


def download_scr_year_zip(year: int, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    url = f"https://www.bcb.gov.br/pda/desig/scrdata_{year}.zip"
    with urlopen(url, timeout=300) as resp:
        dest.write_bytes(resp.read())
    return dest


def _pick_column(df: pd.DataFrame, candidates: Iterable[str]) -> str:
    cols = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols:
            return cols[cand.lower()]
    raise KeyError(f"None of columns found: {list(candidates)}; available={list(df.columns)}")


def aggregate_scr_zip_files(zip_files: list[Path]) -> pd.DataFrame:
    frames = []
    for zp in zip_files:
        with zipfile.ZipFile(zp, "r") as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with zf.open(name) as fh:
                    df = pd.read_csv(fh, sep=";", encoding="latin1", decimal=",", low_memory=False)
                df.columns = [c.strip().lstrip("\ufeff").replace("ï»¿", "") for c in df.columns]
                try:
                    c_date = _pick_column(df, ["data_base", "Data_base"])
                    c_uf = _pick_column(df, ["uf", "UF"])
                    c_tipo = _pick_column(df, ["tipo_cliente", "cliente", "Cliente", "TIPO_CLIENTE"])
                    c_credit = _pick_column(df, ["carteira_ativa", "Carteira_ativa", "CARTEIRA_ATIVA"])
                except KeyError:
                    continue

                tmp = df[[c_date, c_uf, c_tipo, c_credit]].copy()
                tmp.columns = ["data_base", "uf", "tipo_cliente", "carteira_ativa"]
                tmp["tipo_cliente"] = tmp["tipo_cliente"].astype(str).str.upper().str.strip()
                tmp = tmp.loc[tmp["tipo_cliente"].eq("PF")]
                tmp["date"] = pd.to_datetime(tmp["data_base"], errors="coerce")
                tmp["uf"] = tmp["uf"].astype(str).str.upper().str.strip()
                tmp = tmp.loc[tmp["uf"].isin(SIGLA_TO_UF_CODE)]
                tmp["credit_pf"] = pd.to_numeric(tmp["carteira_ativa"], errors="coerce")
                tmp = tmp.dropna(subset=["date", "credit_pf"])
                tmp["uf_code"] = tmp["uf"].map(SIGLA_TO_UF_CODE).astype(int)
                agg = (
                    tmp.groupby(["uf_code", "date"], as_index=False)["credit_pf"]
                    .sum()
                    .sort_values(["uf_code", "date"])
                )
                frames.append(agg)

    if not frames:
        return pd.DataFrame(columns=["uf_code", "date", "credit_pf", "year", "month"])
    out = pd.concat(frames, ignore_index=True)
    out = out.groupby(["uf_code", "date"], as_index=False)["credit_pf"].sum()
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.month
    return out.sort_values(["uf_code", "date"]).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare external monthly controls (PMC/SELIC/IPCA/SCR).")
    parser.add_argument("--pnadc", default="pnadc_matched_with_periods.parquet")
    parser.add_argument("--pof-dir", default="Data/Dados_20230713")
    parser.add_argument("--pmc-csv", default="data_wishlist/drive-download-20260514T125654Z-3-001/PMC_retail_nominal_table8880.csv")
    parser.add_argument("--selic-csv", default="data_wishlist/drive-download-20260514T125654Z-3-001/bcdata.SELIC.4189.csv")
    parser.add_argument("--ipca-xlsx", default="data_wishlist/drive-download-20260514T125654Z-3-001/IPCA_monthly_brazil_table1737.xlsx")
    parser.add_argument("--output-dir", default="results/datasets/external")
    parser.add_argument("--download-scr", action="store_true")
    parser.add_argument("--scr-years", default="2022,2023,2024,2025")
    parser.add_argument("--scr-raw-dir", default="Data/external/scr_raw")
    args = parser.parse_args()

    pnadc_path = Path(args.pnadc)
    pof_dir = Path(args.pof_dir)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    checks = {
        "pnadc_exists": pnadc_path.exists(),
        "pof_dir_exists": pof_dir.exists(),
        "pmc_csv_exists": Path(args.pmc_csv).exists(),
        "selic_csv_exists": Path(args.selic_csv).exists(),
        "ipca_xlsx_exists": Path(args.ipca_xlsx).exists(),
    }

    pmc = parse_sidra_pmc_export(Path(args.pmc_csv))
    selic = parse_selic_csv(Path(args.selic_csv))
    ipca = parse_ipca_xlsx(Path(args.ipca_xlsx))

    pmc.to_csv(outdir / "pmc_retail_nominal_uf_monthly.csv", index=False)
    selic.to_csv(outdir / "selic_monthly_sgs4189.csv", index=False)
    ipca.to_csv(outdir / "ipca_monthly_brazil.csv", index=False)

    scr = pd.DataFrame(columns=["uf_code", "date", "credit_pf", "year", "month"])
    scr_zip_files: list[Path] = []
    if args.download_scr:
        years = [int(x.strip()) for x in args.scr_years.split(",") if x.strip()]
        raw_dir = Path(args.scr_raw_dir)
        for y in years:
            scr_zip_files.append(download_scr_year_zip(y, raw_dir / f"scrdata_{y}.zip"))
        scr = aggregate_scr_zip_files(scr_zip_files)
        if not scr.empty:
            scr.to_csv(outdir / "scr_credit_pf_uf_monthly.csv", index=False)

    panel = pmc.merge(selic[["year", "month", "selic_aa_pct"]], on=["year", "month"], how="left")
    panel = panel.merge(ipca[["year", "month", "ipca_mom_pct"]], on=["year", "month"], how="left")
    if not scr.empty:
        panel = panel.merge(scr[["uf_code", "year", "month", "credit_pf"]], on=["uf_code", "year", "month"], how="left")

    panel = panel.sort_values(["uf_code", "year", "month"]).reset_index(drop=True)
    panel.to_csv(outdir / "macro_external_panel_uf_monthly.csv", index=False)

    summary = {
        "input_checks": checks,
        "outputs": {
            "pmc_rows": int(len(pmc)),
            "selic_rows": int(len(selic)),
            "ipca_rows": int(len(ipca)),
            "scr_rows": int(len(scr)),
            "panel_rows": int(len(panel)),
            "panel_uf_count": int(panel["uf_code"].nunique()),
            "panel_date_min": str(panel["year"].min()) + f"-{int(panel['month'].min()):02d}",
            "panel_date_max": str(panel["year"].max()) + f"-{int(panel['month'].max()):02d}",
            "scr_downloaded_years": [int(p.stem.split("_")[-1]) for p in scr_zip_files],
        },
    }
    (outdir / "prep_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("Prepared external controls.")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
