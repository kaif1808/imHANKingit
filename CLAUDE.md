# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**ImHANKingIt** is a research pipeline that classifies Brazilian households into Hand-to-Mouth (HtM) agent types following the Kaplan–Violante–Weidner (2014) framework, then transfers those classifications to the PNADC monthly matched labor-force panel, and runs local-projection IRF regressions with HtM interaction terms.

Three agent types: `PH2M` (Poor HtM), `WH2M` (Wealthy HtM), `Ricardian`.

## Architecture

### Pipeline stages

1. **POF classification** (`scripts/reporting/htm_classification.py`):
   - Reads raw POF 2017-18 fixed-width text files from `Data/Dados_20230713/`, parsed via `Data/Documentacao_20230713/Dicionarios de variaveis.xls`
   - Classifies households into three agent types using KVW thresholds
   - Builds 6-dimensional demographic bins (region, age, education, gender, labor status, income quintile)
   - Outputs `results/tables/pof_bin_shares.csv` with Dirichlet-smoothed type shares per bin

2. **PNADC monthly matching** (same script, stage 2):
   - Streams `pnadc_matched_with_periods.parquet` in pyarrow batches
   - Merges POF bin probabilities onto PNADC records via common demographic bins
   - Aggregates to state × month expected shares and a deterministic Monte Carlo diagnostic
   - Canonical output: `results/tables/state_month_htm_shares.parquet`

3. **Local projections** (`scripts/reporting/basic_state_month_lp.py`):
   - Builds state × month panel from consumption, HtM shares, and labour-market data
   - Runs fixed-effect LPs: `y_h = β·shock + γ·(shock×PH2M) + δ·(shock×WH2M) + FEs + controls`
   - Outputs IRF tables to `results/tables/basic_state_month_lp/` and plots to `results/plots/basic_state_month_lp/`

4. **IRF heterogeneity** (`scripts/reporting/cumulative_irf_heterogeneity.py`):
   - Monthly state-level IRFs with HtM interaction; falls back to quarterly interpolation if monthly parquet is absent

### Key parameters (`htm_classification.py`)

- `SELIC_RATE` (9%), `LIQUID_THRESH` (0.50), `ILLIQUID_MULT` (3) — agent classification thresholds
- `POVERTY_LINE` (170 BRL/month), `ALPHA_SMOOTH` (0.1), `MIN_WEIGHTED_N` (30), `RANDOM_SEED` (42)
- Paths are resolved relative to the repository root; run scripts from the repo root.

### Data schema

**PNADC inputs** — required columns: `UF`, `V2009`, `V2007`, `VD3004`, `V2001`, `rendimento_habitual_real`, `ref_month_yyyymm`, `ref_month_in_year`, `weight_monthly`, plus `id_rs` or `id_ind`. See `PNADC_REQUIRED_VARIABLES.md`.

**`state_month_htm_shares.parquet`** columns: `[uf_code, year, month, ref_month_yyyymm, share_PH2M, share_WH2M, share_Ricardian, share_H2M, total_weight, n_obs, n_unmatched]`

## Development Commands

### Setup
```bash
pip install -r requirements.txt
```

### Run Main Classification Pipeline
```bash
# Full pipeline
python3 scripts/reporting/htm_classification.py

# Skip choropleths
python3 scripts/reporting/htm_classification.py --no-choropleth

# Custom PNADC input
python3 scripts/reporting/htm_classification.py --pnad-parquet /path/to/custom.parquet

# Legacy within-batch quintiles (instead of POF cut-points)
python3 scripts/reporting/htm_classification.py --per-quarter-quintiles

# Skip legacy quarterly aggregate
python3 scripts/reporting/htm_classification.py --no-legacy-quarterly
```

### Run Local Projection Pipeline
```bash
python3 scripts/reporting/basic_state_month_lp.py
```

### Run IRF Heterogeneity Pipeline
```bash
python3 scripts/reporting/cumulative_irf_heterogeneity.py
```

### Regenerate Choropleths Only
```bash
python3 scripts/reporting/generate_choropleths.py
python3 scripts/reporting/generate_choropleths.py --input results/tables/state_quarter_htm_shares.csv --output-dir results/plots
```

### PNADC Panel Preprocessing (R)
```bash
Rscript scripts/data_prep/pnad.r
# R dependency setup: Rscript scripts/data_prep/install.R
```

### Tests
```bash
pytest tests/
pytest tests/test_htm_monthly_batch.py -v
pytest tests/test_htm_quintiles.py::test_pof_quintile_cutpoints_align_pnadc
pytest tests/test_pnad_faixa_pretreat.py -v
pytest tests/test_basic_state_month_lp.py -v
```

## Key Files

| File | Purpose |
|------|---------|
| `scripts/reporting/htm_classification.py` | Main POF classify → PNADC monthly pipeline |
| `scripts/reporting/basic_state_month_lp.py` | State × month LP regressions with HtM interaction terms |
| `scripts/reporting/cumulative_irf_heterogeneity.py` | Monthly state-level IRF heterogeneity |
| `scripts/reporting/generate_choropleths.py` | Standalone choropleth generation from quarterly shares |
| `scripts/data_prep/pnad_faixa_pretreat.py` | PNADC DataZoom label converters (`faixa_idade_to_age`, `faixa_educ_to_vd3004`) |
| `scripts/data_prep/pnad.r` | R helper to pre-filter PNADC panel CSVs |
| `PNADC_REQUIRED_VARIABLES.md` | PNADC schema contract |
| `RESULTS_PROVENANCE.md` | Output artifact ownership and rerun commands |
| `overleaf/main.tex` | LaTeX slides (25 frames) |

## Repository Layout

```
scripts/reporting/   — canonical entry-point scripts
scripts/data_prep/   — data preparation helpers (R and Python)
scripts/utils/       — occasional utilities (notebook converters)
analysis/            — exploratory one-offs
archive/legacy/      — superseded files kept for reference
results/tables/      — output CSVs and parquets
results/diagnostics/ — coverage and merge diagnostics
results/plots/       — charts and choropleths
tests/               — pytest suite
```

## Testing Notes

- **Quintile alignment:** POF-derived cut-points are used for PNADC bin matching; `--per-quarter-quintiles` is a legacy fallback.
- **Outliers:** PNADC incomes below POF min map to Q1; above max map to Q5.
- **Monte Carlo reproducibility:** `RANDOM_SEED=42`.
- **Dirichlet smoothing:** bins with `n_weighted < 30` are flagged in `pof_bin_shares.csv`.

## Common Issues

1. **`pnadc_matched_with_periods.parquet` not found** → pass `--pnad-parquet /path/to/parquet`
2. **Choropleth download fails** → script falls back gracefully; use `--no-choropleth` to skip
3. **Seasonal discontinuity in Ricardian shares** → try `--per-quarter-quintiles`
4. **IRF script can't find monthly shares** → `cumulative_irf_heterogeneity.py` falls back to quarterly interpolation when `state_month_htm_shares.parquet` is absent
