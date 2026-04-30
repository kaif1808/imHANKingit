# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ImHANKingIt** is a research pipeline that classifies Brazilian households into Hand-to-Mouth (HtM) agent types following the Kaplan–Violante–Weidner (2014) framework, then transfers those classifications to the PNADC monthly matched labor-force panel.

The pipeline produces:
- `results/tables/pof_bin_shares.csv` — demographic bin shares by HtM type
- `results/tables/state_month_htm_shares.parquet` — state × month expected probability-weighted type shares
- `results/tables/state_month_htm_shares_mc.parquet` — state × month deterministic Monte Carlo diagnostic shares
- `results/diagnostics/monthly_htm_coverage.csv` — monthly coverage and exclusion diagnostics
- `results/tables/state_quarter_htm_shares.csv` — legacy state × quarter aggregate
- `results/plots/choropleth_htm_YYYYQq.png` — per-quarter 4-panel regional maps (one per quarter)

## Architecture

### Two-Stage Pipeline

1. **POF stage (fixed-width text files):**
   - Read raw POF 2017-18 household budget survey (`Data/Dados_20230713/`)
   - Parse using Excel dictionary (`Data/Documentacao_20230713/Dicionarios de variaveis.xls`)
   - Classify each household into three agent types: PH2M (Poor HtM), WH2M (Wealthy HtM), Ricardian
   - Build demographic bins (6 dimensions: region, age, education, gender, labor status, income quintile)
   - Compute weighted type shares per bin with Dirichlet smoothing

2. **PNADC stage (monthly parquet):**
   - Stream PNADC (`pnadc_matched_with_periods.parquet` by default, or via `--pnad-parquet PATH`) in `pyarrow` batches
   - Build identical demographic bins on PNADC data
   - Merge POF bin probabilities onto PNADC records
   - Aggregate expected probabilities to state × month shares
   - Build deterministic Monte Carlo state-month shares as a diagnostic

3. **Visualization (optional):**
   - Generate per-quarter 4-panel choropleths if `--no-choropleth` not set
   - Downloads IBGE state boundaries; graceful fallback if download fails

### Configuration & Paths

Paths in `htm_classification.py` are resolved relative to the repository root containing the script.

Key parameters are set near the top of `htm_classification.py`:
- `SELIC_RATE` (9% for 2017-18), `LIQUID_THRESH` (0.50), `ILLIQUID_MULT` (3) — agent classification thresholds
- `POVERTY_LINE` (170 BRL/month), `PENSION_MULT` (1 month)
- `ALPHA_SMOOTH` (0.1) — Dirichlet smoothing strength; `MIN_WEIGHTED_N` (30) — bin flagging threshold
- `RANDOM_SEED` (42)

### Data Schema

**POF inputs** (fixed-width text files):
- `DOMICILIO.txt`, `MORADOR.txt`, `RENDIMENTO_TRABALHO.txt`, `OUTROS_RENDIMENTOS.txt`, `ALUGUEL_ESTIMADO.txt`
- Parsed via Excel dictionary for column positions

**PNADC inputs** (monthly parquet):
- Default: `pnadc_matched_with_periods.parquet`
- Required raw columns: `UF`, `V2009`, `V2007`, `VD3004`, `V2001`, `rendimento_habitual_real`, `ref_month_yyyymm`, `ref_month_in_year`, `weight_monthly`, plus `id_rs` or `id_ind`
- See `PNADC_REQUIRED_VARIABLES.md` for full variable inventory

**Output tables:**
- `pof_bin_shares.csv`: columns `[region, age, education, gender, labor_status, income_quintile, PH2M, WH2M, Ricardian, n_weighted, flag]`
- `state_month_htm_shares.parquet`: columns `[uf_code, year, month, ref_month_yyyymm, share_PH2M, share_WH2M, share_Ricardian, share_H2M, total_weight, n_obs, n_unmatched]`

## Development Commands

### Setup
```bash
pip install -r requirements.txt
```

### Run Main Pipeline
```bash
# Full pipeline with choropleths
python3 htm_classification.py

# Skip choropleth generation
python3 htm_classification.py --no-choropleth

# Legacy within-batch PNADC quintiles instead of POF cut-points
python3 htm_classification.py --per-quarter-quintiles

# Custom PNADC input
python3 htm_classification.py --pnad-parquet /path/to/custom.parquet

# Skip legacy quarterly aggregate
python3 htm_classification.py --no-legacy-quarterly
```

### Tests
```bash
# Run all tests
pytest tests/

# Run specific test
pytest tests/test_htm_quintiles.py::test_pof_quintile_cutpoints_align_pnadc

# Single test function
pytest tests/test_pnad_faixa_pretreat.py -v
```

### Choropleth Generation (Standalone)
```bash
# Default: read results/tables/state_quarter_htm_shares.csv, write to results/plots/
python3 generate_choropleths.py

# Custom input/output
python3 generate_choropleths.py --input /path/to/shares.csv --output-dir /path/to/plots/
```

### PNADC Panel Preprocessing (R)
```bash
# Filter large PNADC panel CSVs to required columns
Rscript pnad.r
# Requires datazoom.social; install via: source('install.R')
```

## Key Files & Their Purpose

| File | Purpose |
|------|---------|
| `htm_classification.py` | Main 5-step pipeline (POF classify → bin shares → PNADC merge → Monte Carlo → state×quarter) |
| `pnad_faixa_pretreat.py` | PNADC DataZoom string label converters (`faixa_idade_to_age`, `faixa_educ_to_vd3004`) |
| `generate_choropleths.py` | Standalone per-quarter choropleth generation from state×quarter shares CSV |
| `tests/test_htm_quintiles.py` | Quintile alignment & outlier handling |
| `tests/test_pnad_faixa_pretreat.py` | DataZoom label conversion tests |
| `pnad.r` | R helper to pre-filter PNADC panel CSVs to required columns |
| `htm_classification_report.ipynb` | Full analysis notebook with inline classification & diagnostics |
| `main.ipynb` | Main exploratory analysis notebook |
| `overleaf/main.tex` | LaTeX slides (25 frames) for presentation/paper |

## Testing & Validation Notes

- **Quintile alignment:** POF-derived quintile cut-points are used when matching PNADC to bins (not per-PNADC quintiles), ensuring alignment across months. `--per-quarter-quintiles` is retained as a legacy within-batch option.
- **Outliers:** PNADC incomes outside the POF range map to Q1 (below minimum) or Q5 (above maximum).
- **Monte Carlo:** Stochastic assignment uses `RANDOM_SEED=42` for reproducibility.
- **Dirichlet smoothing:** Bins with `n_weighted < MIN_WEIGHTED_N` are flagged in output; smoothing parameter `ALPHA_SMOOTH` controls strength.

## Common Issues & Fixes

1. **"pnadc_matched_with_periods.parquet not found"** → Pass `--pnad-parquet /path/to/parquet`
2. **Choropleth download fails** → Script falls back gracefully; check network if needed
3. **Seasonal discontinuity in Ricardian shares** → Try `--per-quarter-quintiles` to reduce seasonal bias
4. **Monthly parquet missing for IRFs** → `cumulative_irf_heterogeneity.py` falls back to quarterly interpolation when `results/tables/state_month_htm_shares.parquet` is absent

## Dependencies

See `requirements.txt`:
- **Data/IO:** pandas, pyarrow (parquet), openpyxl (Excel), pyreadr (RDS)
- **Analysis:** numpy, scipy, statsmodels
- **Visualization:** matplotlib, seaborn, geopandas (choropleths)
- **Parsing:** beautifulsoup4 (HTML → notebook conversion)

## Writing & Presentation

- **LaTeX slides:** `overleaf/main.tex` — 25 frames covering data, methods, regional results, robustness
- **Analysis notebooks:** `htm_classification_report.ipynb` (complete), `main.ipynb` (exploratory)
- **Paper materials:** See `overleaf/` (cover letter, main slides)
