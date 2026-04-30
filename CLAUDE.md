# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ImHANKingIt** is a research pipeline that classifies Brazilian households into Hand-to-Mouth (HtM) agent types following the Kaplan–Violante–Weidner (2014) framework, then transfers those classifications to the PNADC quarterly labor-force survey.

The pipeline produces:
- `results/tables/pof_bin_shares.csv` — demographic bin shares by HtM type
- `results/tables/state_quarter_htm_shares.csv` — state × quarter population-weighted type shares
- `results/plots/choropleth_htm_YYYYQq.png` — per-quarter 4-panel regional maps (one per quarter)

## Architecture

### Two-Stage Pipeline

1. **POF stage (fixed-width text files):**
   - Read raw POF 2017-18 household budget survey (`Data/Dados_20230713/`)
   - Parse using Excel dictionary (`Data/Documentacao_20230713/Dicionarios de variaveis.xls`)
   - Classify each household into three agent types: PH2M (Poor HtM), WH2M (Wealthy HtM), Ricardian
   - Build demographic bins (6 dimensions: region, age, education, gender, labor status, income quintile)
   - Compute weighted type shares per bin with Dirichlet smoothing

2. **PNADC stage (parquet or CSV):**
   - Read PNADC (`PNAD-C-Treated/pnad_matched.parquet` by default, or via `--pnad-parquet PATH`)
   - Build identical demographic bins on PNADC data
   - Merge POF bin shares onto PNADC records
   - Monte Carlo assignment: random draw HtM type per record from merged bin shares
   - Aggregate to state × quarter panel

3. **Visualization (optional):**
   - Generate per-quarter 4-panel choropleths if `--no-choropleth` not set
   - Downloads IBGE state boundaries; graceful fallback if download fails

### Configuration & Paths

**Important:** `BASE_DIR` in `htm_classification.py` (line 49) is hardcoded to `/Users/kai/Desktop/imHANKingit`. If the repo is moved, update this path or pass explicit flags.

Key parameters are set near the top of `htm_classification.py`:
- `SELIC_RATE` (9% for 2017-18), `LIQUID_THRESH` (0.50), `ILLIQUID_MULT` (3) — agent classification thresholds
- `POVERTY_LINE` (170 BRL/month), `PENSION_MULT` (1 month)
- `ALPHA_SMOOTH` (0.1) — Dirichlet smoothing strength; `MIN_WEIGHTED_N` (30) — bin flagging threshold
- `RANDOM_SEED` (42)

### Data Schema

**POF inputs** (fixed-width text files):
- `DOMICILIO.txt`, `MORADOR.txt`, `RENDIMENTO_TRABALHO.txt`, `OUTROS_RENDIMENTOS.txt`, `ALUGUEL_ESTIMADO.txt`
- Parsed via Excel dictionary for column positions

**PNADC inputs** (parquet):
- Default: `PNAD-C-Treated/pnad_matched.parquet`
- Required columns: `UF`, `Ano`, `Trimestre`, `faixa_idade`, `sexo`, `faixa_educ`, `Habitual`, `rendimento_habitual_real`, `ID_DOMICILIO`
- See `PNADC_REQUIRED_VARIABLES.md` for full variable inventory

**Output tables:**
- `pof_bin_shares.csv`: columns `[region, age, education, gender, labor_status, income_quintile, PH2M, WH2M, Ricardian, n_weighted, flag]`
- `state_quarter_htm_shares.csv`: columns `[UF, Ano, Trimestre, PH2M, WH2M, Ricardian, population]`

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

# Use per-quarter quintiles instead of POF cut-points (reduces seasonal bias)
python3 htm_classification.py --per-quarter-quintiles

# Custom PNADC input
python3 htm_classification.py --pnad-parquet /path/to/custom.parquet
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

- **Quintile alignment:** POF-derived quintile cut-points are used when matching PNADC to bins (not per-PNADC quintiles), ensuring alignment across quarters. Override with `--per-quarter-quintiles` if needed.
- **Outliers:** PNADC incomes outside the POF range map to Q1 (below minimum) or Q5 (above maximum).
- **Monte Carlo:** Stochastic assignment uses `RANDOM_SEED=42` for reproducibility.
- **Dirichlet smoothing:** Bins with `n_weighted < MIN_WEIGHTED_N` are flagged in output; smoothing parameter `ALPHA_SMOOTH` controls strength.

## Common Issues & Fixes

1. **"pnad_matched.parquet not found"** → Pass `--pnad-parquet /path/to/parquet` or create symlink in `PNAD-C-Treated/`
2. **Choropleth download fails** → Script falls back gracefully; check network if needed
3. **Seasonal discontinuity in Ricardian shares** → Try `--per-quarter-quintiles` to reduce seasonal bias
4. **BASE_DIR hardcoded path mismatch** → Update line 49 in `htm_classification.py` or run from correct directory

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
