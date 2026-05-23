# ImHANKingIt: Hand-to-Mouth Agent Classification Pipeline

A comprehensive research pipeline for classifying Brazilian households into Hand-to-Mouth (HtM) agent types using the Kaplan–Violante–Weidner (KVW, 2014) framework, with applications to PNADC monthly labor-force panel data and local-projection IRF heterogeneity analysis.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Quick Start](#quick-start)
3. [Repository Structure](#repository-structure)
4. [Pipeline Architecture](#pipeline-architecture)
5. [Data Schema & Requirements](#data-schema--requirements)
6. [Running the Pipelines](#running-the-pipelines)
7. [Outputs](#outputs)
8. [Development & Testing](#development--testing)
9. [Key Concepts & Theory](#key-concepts--theory)
10. [Troubleshooting & FAQ](#troubleshooting--faq)
11. [Contributing Guidelines](#contributing-guidelines)
12. [Related Documentation](#related-documentation)

---

## Project Overview

### What is ImHANKingIt?

**ImHANKingIt** is a research pipeline designed to:

1. **Classify households** using Brazilian household survey data (POF 2017-18) into three behavioral agent types based on the KVW framework.
2. **Transfer classifications** to a larger PNADC monthly matched labor-force panel to build state-month expected type shares.
3. **Analyze macroeconomic heterogeneity** through local-projection impulse response functions (IRFs) with HtM interaction terms.

The pipeline bridges household-level survey data with monthly macroeconomic panel analysis, enabling research on how hand-to-mouth agents respond differently to economic shocks.

### The KVW Framework & Agent Types

Following Kaplan, Violante, and Weidner (2014), households are classified into three mutually exclusive agent types:

- **PH2M (Poor Hand-to-Mouth)**: Households with liquid assets below a threshold but nonzero illiquid assets. Face both liquidity and income constraints.
- **WH2M (Wealthy Hand-to-Mouth)**: Households with liquid assets above threshold but primarily illiquid wealth. Consumption is hand-to-mouth despite wealth.
- **Ricardian**: Households with sufficient liquid assets and low income risk. Can smooth consumption across shocks.

### Classification Thresholds

**Configurable parameters** (at top of scripts):
- `SELIC_RATE`: 9% (opportunity cost of liquid holdings)
- `LIQUID_THRESH`: 0.50 (liquid asset ratio threshold)
- `ILLIQUID_MULT`: 3.0 (illiquid wealth multiplier)
- `POVERTY_LINE`: 170 BRL/month (subsistence minimum)
- `ALPHA_SMOOTH`: 0.1 (Dirichlet smoothing parameter)
- `MIN_WEIGHTED_N`: 30 (minimum bin size for smoothing)
- `RANDOM_SEED`: 42 (Monte Carlo reproducibility)

### Research Objectives

Key questions addressed by this pipeline:

- What share of Brazilian households are hand-to-mouth, and how does this vary by region, demographics, and income?
- How do monetary shocks propagate differently through PH2M vs. WH2M agents?
- What is the aggregate demand multiplier heterogeneity implied by HtM type shares?
- How stable are HtM classifications across time and demographic groups?

---

## Quick Start

### Prerequisites

- Python 3.8+
- Git (for repository cloning)
- Optional: R (for PNADC preprocessing)

### 1. Install Dependencies

```bash
git clone <repository-url>
cd imHANKingit
pip install -r requirements.txt
```

**Key dependencies:**
- `numpy`, `pandas`, `pyarrow`: Data manipulation
- `statsmodels`, `scipy`: Statistical analysis
- `pyfixest`: High-dimensional fixed-effect regressions
- `geopandas`: Geographic visualization
- `matplotlib`, `seaborn`: Plotting

### 2. Verify Data Structure

```bash
ls -R Data/Dados_20230713/
ls -R Data/Documentacao_20230713/
```

Expected files:
- POF raw data: `DOMICILIO.txt`, `MORADOR.txt`, `RENDIMENTO_TRABALHO.txt`, `OUTROS_RENDIMENTOS.txt`, `ALUGUEL_ESTIMADO.txt`
- POF dictionary: `Data/Documentacao_20230713/Dicionarios de variaveis.xls`

### 3. Run the Canonical Monthly Pipeline

```bash
# Full run with choropleths (takes ~15-30 minutes)
python3 htm_classification.py

# Faster run without choropleth maps
python3 htm_classification.py --no-choropleth
```

### 4. Verify Outputs

```bash
ls -lh results/tables/pof_bin_shares.csv
ls -lh results/tables/state_month_htm_shares.parquet
head -20 results/diagnostics/monthly_htm_coverage.csv
```

---

## Repository Structure

### Complete Directory Inventory

```
imHANKingit/
├── scripts/
│   ├── reporting/              # Entry-point scripts
│   │   ├── htm_classification.py         # Main pipeline (POF + PNADC)
│   │   ├── basic_state_month_lp.py       # LP regressions with HtM interaction
│   │   ├── cumulative_irf_heterogeneity.py  # IRF heterogeneity analysis
│   │   ├── generate_choropleths.py       # Standalone map generation
│   │   └── scripts/README.md
│   ├── data_prep/              # Data preprocessing helpers
│   │   ├── pnad_faixa_pretreat.py        # DataZoom label converters
│   │   ├── pnad.r
│   │   └── [other prep scripts]
│   └── utils/                  # Utilities
│
├── tests/                      # pytest suite (5 files, 23 tests)
│   ├── test_htm_monthly_batch.py
│   ├── test_htm_quintiles.py
│   ├── test_pnad_faixa_pretreat.py
│   ├── test_basic_state_month_lp.py
│   └── test_repo_structure.py
│
├── Data/
│   ├── Dados_20230713/         # POF 2017-18 fixed-width files
│   ├── Documentacao_20230713/  # POF data dictionary (Excel)
│   ├── state_data/             # State-level macro data
│   ├── pnad/                   # PNADC preprocessing outputs
│   └── external/               # Reference data
│
├── results/
│   ├── tables/                 # Output tables (CSV, parquet)
│   │   ├── pof_bin_shares.csv
│   │   ├── state_month_htm_shares.parquet (CANONICAL)
│   │   └── basic_state_month_lp/
│   ├── diagnostics/            # Coverage, merge, validation reports
│   ├── plots/                  # Choropleths and IRF charts
│   └── datasets/               # Panel datasets for replication
│
├── analysis/                   # Exploratory notebooks
├── archive/legacy/             # Superseded scripts
├── wealth/                     # Wealth data processing
├── calibration/                # Model calibration files
├── overleaf/                   # LaTeX slide deck (25 frames)
│
├── CLAUDE.md                   # Developer architecture guide
├── AGENTS.md                   # Repository conventions
├── PNADC_REQUIRED_VARIABLES.md # PNADC schema contract
├── RESULTS_PROVENANCE.md       # Output ownership
├── development_status.md       # Change log
└── requirements.txt
```

### Key Directories Reference

| Directory | Purpose |
|-----------|---------|
| `scripts/reporting/` | Entry points: POF classification, PNADC matching, LP IRF, visualization |
| `scripts/data_prep/` | Data preprocessing, label converters, R helpers |
| `tests/` | pytest suite: 5 files, 23 tests covering all stages |
| `results/tables/` | Output tables: POF bins, state-month shares, IRF tables |
| `results/diagnostics/` | Coverage reports, matching diagnostics, validation |
| `results/plots/` | Choropleths, IRF line plots, diagnostic charts |
| `Data/Dados_20230713/` | POF 2017-18 raw data (5 fixed-width files) |
| `Data/state_data/` | State-level inputs: consumption, labor market |
| `analysis/` | Exploratory Jupyter notebooks |
| `archive/legacy/` | Superseded scripts (reference only) |

---

## Pipeline Architecture

### Four-Stage Pipeline

```
Stage 1: POF Classification
    ↓ Parses POF 2017-18 fixed-width files
    ↓ Classifies households into PH2M/WH2M/Ricardian
    ↓ Builds 6-dimensional demographic bins
    ↓
POF Bin Shares (pof_bin_shares.csv)
    ↓
Stage 2: PNADC Monthly Matching
    ↓ Streams monthly PNADC panel (500k rows/batch)
    ↓ Merges POF bin probabilities via demographics
    ↓ Aggregates to state × month expected shares
    ↓
State-Month HtM Shares (state_month_htm_shares.parquet) ← CANONICAL
    ↓
Stage 3: Local Projections (Optional)
    ↓ Builds state × month panel + consumption + shocks
    ↓ Runs fixed-effect LPs with HtM interactions
    ↓ Computes cumulative & marginal IRFs (0-12+ months)
    ↓
IRF Tables & Plots (results/tables/basic_state_month_lp/)
    ↓
Stage 4: Visualization (Optional)
    └─ Generates state-level choropleths, IRF charts
```

### Stage 1: POF Classification

**Input**: `Data/Dados_20230713/` (5 fixed-width text files)

**Processing**:
1. Parse fixed-width files using column specs from Excel dictionary
2. Merge on household/person identifiers
3. Calculate income: labor + transfers (clipped ≥ 1)
4. Calculate assets: liquid (cash/savings), illiquid (real estate)
5. Classify into agent types (KVW thresholds)
6. Build 6D bins: (macro_region × age × education × gender × labor_status × income_quintile)
7. Compute bin-level type shares with Dirichlet smoothing (α=0.1)

**Output**: `pof_bin_shares.csv` (~3,600–7,200 bins)

### Stage 2: PNADC Monthly Matching

**Input**: `pnadc_matched_with_periods.parquet` (monthly PNADC panel)

**Required PNADC columns**:
- `UF`, `V2009` (age), `V2007` (sex), `VD3004` (education)
- `V2001` (household size), `rendimento_habitual_real` (income)
- `ref_month_yyyymm`, `weight_monthly`, `id_rs` or `id_ind`

**Processing**:
1. Stream parquet in 500k-row batches
2. Exclude: age < 15, missing month/weight/UF
3. Construct 6D demographic bin keys
4. Merge with POF bin probabilities
5. Aggregate to state × month expected shares (weighted)
6. Deterministic Monte Carlo diagnostic (RANDOM_SEED=42)

**Outputs**:
- `state_month_htm_shares.parquet` (**CANONICAL**): ~10,800 rows (27 states × 400 months)
  - Invariant: `share_PH2M + share_WH2M + share_Ricardian = 1.0`
- `state_month_htm_shares_mc.parquet` (diagnostic)
- `monthly_htm_coverage.csv` (coverage diagnostics)

### Stage 3: Local Projections

**Input**: State-month HtM shares + consumption + labor market + shocks

**Specification** (fixed-effect LP):
```
Δlog(consumption)_h,t+h = β·shock + γ·(shock × share_PH2M) + δ·(shock × share_WH2M)
                           + state_FE + (optional: month_FE) + controls
```

**Outputs**:
- `irf.csv`: Full IRF table (all specs, horizons, terms)
- `aggregate_irf.csv`: Mean composition IRFs
- IRF plots: `cumulative_irf.png`, `marginal_irf.png`

### Stage 4: Choropleths & Visualization

**Input**: `state_quarter_htm_shares.csv`

**Output**: 4-panel state maps per quarter showing PH2M, WH2M, H2M, Ricardian shares

---

## Data Schema & Requirements

### POF Input Schema

**Files in `Data/Dados_20230713/`**:

| File | Records | Key Columns |
|------|---------|-------------|
| `DOMICILIO.txt` | Households | Region, state, strata |
| `MORADOR.txt` | Individuals | Age (V2009), sex (V2007), education (VD3004) |
| `RENDIMENTO_TRABALHO.txt` | Income flows | Labor income |
| `OUTROS_RENDIMENTOS.txt` | Non-labor income | Transfers, pensions, financial |
| `ALUGUEL_ESTIMADO.txt` | Implicit rent | Owned housing services |

**Dictionary**: `Data/Documentacao_20230713/Dicionarios de variaveis.xls` (Excel, specifies fixed-width columns)

### PNADC Input Schema (Parquet)

**Required columns**:

| Column | Type | Usage |
|--------|------|-------|
| `UF` | str | State code → macro-region, aggregation key |
| `V2009` | int | Age (≥ 15 filter), age-group binning |
| `V2007` | int | Sex code → gender binning |
| `VD3004` | int | Education code → education-group binning |
| `V2001` | int | Household size → per-capita income |
| `rendimento_habitual_real` | float | Monthly income → quintile assignment |
| `ref_month_yyyymm` | int | Period key (YYYYMM); excluded if missing |
| `weight_monthly` | float | Survey weight; excluded if missing |
| `id_rs` or `id_ind` | str/int | Panel ID (deterministic MC) |

**Optional labor-status columns**: `formal`, `conta_propria`, `informal`, `ocupado`, `desocupado`, `fora_forca_trab`

**Outlier handling**:
- Income < POF min quantile → Q1
- Income > POF max quantile → Q5

### Output Schema: `state_month_htm_shares.parquet`

**CANONICAL OUTPUT**

| Column | Type | Description |
|--------|------|-------------|
| `uf_code` | int | State code (11–28) |
| `year` | int | Year |
| `month` | int | Month (1–12) |
| `ref_month_yyyymm` | int | Period key |
| `share_PH2M` | float | PH2M share ∈ [0, 1] |
| `share_WH2M` | float | WH2M share ∈ [0, 1] |
| `share_Ricardian` | float | Ricardian share ∈ [0, 1] |
| `share_H2M` | float | HtM aggregate ∈ [0, 1] |
| `total_weight` | float | Sum of weights |
| `n_obs` | int | Matched records |
| `n_unmatched` | int | Unmatched records |

---

## Running the Pipelines

### Full Classification Pipeline

```bash
python3 htm_classification.py
```

**Options**:
- `--no-choropleth`: Skip map generation
- `--pnad-parquet /path/to/file.parquet`: Custom PNADC input
- `--per-quarter-quintiles`: Use within-quarter quintiles (legacy)
- `--no-legacy-quarterly`: Skip quarterly aggregate

### Faster Run (No Choropleths)

```bash
python3 htm_classification.py --no-choropleth
```

### Regenerate Maps Only

```bash
python3 generate_choropleths.py \
    --input results/tables/state_quarter_htm_shares.csv \
    --output-dir results/plots
```

### Local Projection IRFs

```bash
python3 scripts/reporting/basic_state_month_lp.py
```

### IRF Heterogeneity

```bash
python3 scripts/reporting/cumulative_irf_heterogeneity.py
```

---

## Outputs

### Core HtM Classification

| File | Format | Purpose |
|------|--------|---------|
| `results/tables/pof_bin_shares.csv` | CSV | POF bin shares (~3,600–7,200 rows) |
| `results/tables/state_month_htm_shares.parquet` | Parquet | **CANONICAL** state-month shares (~10,800 rows) |
| `results/tables/state_month_htm_shares_mc.parquet` | Parquet | Monte Carlo diagnostic |
| `results/diagnostics/monthly_htm_coverage.csv` | CSV | Coverage, matching, exclusion stats |
| `results/tables/state_quarter_htm_shares.csv` | CSV | Legacy quarterly aggregate (optional) |

### Secondary Outputs

| File | Format | Purpose |
|------|--------|---------|
| `results/plots/choropleth_htm_YYYYQq.png` | PNG | State-level maps (4 panels per quarter) |
| `results/tables/basic_state_month_lp/irf.csv` | CSV | IRF table (all specs, horizons) |
| `results/plots/basic_state_month_lp/*.png` | PNG | IRF line plots with 95% CI |

For complete output provenance, see `RESULTS_PROVENANCE.md`.

---

## Development & Testing

### Test Suite

| Test File | Purpose | Tests |
|-----------|---------|-------|
| `test_htm_monthly_batch.py` | PNADC batch processing, monthly aggregation | 6 |
| `test_htm_quintiles.py` | Quintile alignment, outlier handling | 2 |
| `test_pnad_faixa_pretreat.py` | Data prep converters | 4 |
| `test_basic_state_month_lp.py` | LP panel, regression, plotting | 8 |
| `test_repo_structure.py` | Repository hygiene | 3 |

**Total**: 5 files, 23 tests

### Running Tests

```bash
# Full suite
pytest tests/ -v

# Specific file
pytest tests/test_htm_monthly_batch.py -v

# With coverage
pytest tests/ --cov=scripts --cov-report=html
```

### Testing Guidelines

Add tests when:
- Changing classification logic
- Modifying schema expectations
- Updating aggregation formulas
- Adding new entry-point features

**Validation checklist after changes**:
- [ ] Type shares sum to 1.0 per state-month
- [ ] Coverage diagnostics reasonable
- [ ] Dirichlet smoothing applied correctly
- [ ] Deterministic MC matches expected shares
- [ ] Quintile alignment stable
- [ ] All tests pass

---

## Key Concepts & Theory

### HtM Classification Logic

**Classification tree**:
```
If liquid_ratio ≥ LIQUID_THRESH (0.50):
    → Ricardian
Else if illiquid_ratio ≥ ILLIQUID_MULT (3.0):
    → WH2M
Else:
    → PH2M
```

### Demographic Bins (6-Dimensional)

Cross-tabulation of:
- Macro-region (5): N, NE, CW, SE, S
- Age group (6): 15-24, 25-34, 35-44, 45-54, 55-64, 65+
- Education (4): <HS, HS, Some College, College+
- Gender (2): M, F
- Labor status (3): Employed, Unemployed, Inactive
- Income quintile (5): Q1–Q5

**Total**: ~3,600 theoretical bins (many empty)

### Dirichlet Smoothing

For bins with < 30 weighted records:
```
smoothed_share = (count + α) / (total + K·α)
```
where α = 0.1, K = 3. Prevents zero-count outliers while preserving empirical data.

### Monte Carlo Diagnostic

Deterministic agent assignment per record (seeded RNG):
- Seed: `hash(id || RANDOM_SEED=42)`
- Validates consistency between expected and realized shares

---

## Troubleshooting & FAQ

### POF Data Not Found

**Error**: `FileNotFoundError: Data/Dados_20230713/DOMICILIO.txt`

**Solution**:
```bash
ls -la Data/Dados_20230713/
ls -la Data/Documentacao_20230713/Dicionarios\ de\ variaveis.xls
```

### PNADC Parquet Not Found

**Error**: `FileNotFoundError: pnadc_matched_with_periods.parquet`

**Solution**:
```bash
# Place in repo root or pass explicit path
python3 htm_classification.py --pnad-parquet /path/to/pnadc.parquet
```

### Schema Mismatch

**Error**: `KeyError: 'V2009'`

**Solution**:
```python
import pyarrow.parquet as pq
pf = pq.ParquetFile('/path/to/pnadc.parquet')
print(pf.schema)  # Validate against PNADC_REQUIRED_VARIABLES.md
```

### Choropleth Generation Fails

**Error**: `HTTPError: 403 Forbidden`

**Solution**:
```bash
python3 htm_classification.py --no-choropleth
# Retry later or pre-download IBGE boundaries
```

### IRF Script Cannot Find Monthly Shares

**Error**: `FileNotFoundError: state_month_htm_shares.parquet`

**Solution**:
```bash
# Verify htm_classification.py succeeded
ls -lh results/tables/state_month_htm_shares*.parquet

# Re-run if missing
python3 htm_classification.py
```

---

## Contributing Guidelines

### Repository Organization

1. **Canonical entry points** stay in root:
   - `htm_classification.py`
   - `generate_choropleths.py`
   - `cumulative_irf_heterogeneity.py`

2. **New scripts** by purpose:
   - Data prep → `scripts/data_prep/`
   - Reporting → `scripts/reporting/`
   - Utilities → `scripts/utils/`

3. **Exploratory work** → `analysis/`

4. **Superseded code** → `archive/legacy/`

5. **Update docs** when changing:
   - Command-line arguments
   - Input/output schema
   - Generated artifacts

### Coding Standards (PEP 8)

**Python**:
- 4-space indentation, snake_case, UPPER_SNAKE_CASE constants
- Type hints where feasible
- Docstrings for public functions
- Keep scripts < 500 lines

### Commit & PR Guidelines

**Commit style** (imperative):
- `fix(classification): align quintile cutpoints`
- `feat(reporting): add aggregate IRF chart`
- `test(htm_monthly): add batch edge case`

**PR structure**:
1. Objective: Problem solved?
2. Changes: Key modifications
3. Testing: Commands run, test results
4. Outputs: New artifacts (screenshots)
5. Docs: Updated PNADC_REQUIRED_VARIABLES.md, etc.

**Before merging**:
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Documentation updated
- [ ] No uncommitted changes in results/
- [ ] Issues/PRs linked

---

## Related Documentation

| File | Purpose |
|------|---------|
| **CLAUDE.md** | Developer architecture, parameters, commands, notes |
| **AGENTS.md** | Repository conventions, coding style, commit standards |
| **PNADC_REQUIRED_VARIABLES.md** | PNADC schema contract |
| **RESULTS_PROVENANCE.md** | Output ownership, rerun commands |
| **development_status.md** | Change log |

---

**Last Updated**: May 23, 2026  
**Maintained by**: ImHANKingIt Research Team
