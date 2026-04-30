# ImHANKingIt

## Project (brief)
ImHANKingIt is a research pipeline that builds a time-series of Hand-to-Mouth (HtM) agent-type shares for Brazil, following the Kaplan-Violante-Weidner (2014) framework.

Starting from the POF 2017-18 household budget survey (fixed-width text tables), the pipeline classifies individuals into three agent types:
- PH2M: Poor Hand-to-Mouth (low liquid and low illiquid assets)
- WH2M: Wealthy Hand-to-Mouth (low liquid, high illiquid assets)
- Ricardian: sufficient liquid buffer to smooth consumption

The resulting type shares are transferred to the PNADC monthly matched labour-force panel via demographic bin construction and probability matching, producing canonical state x month expected HtM shares. A deterministic Monte Carlo state-month series is also produced as a diagnostic.

## What the pipeline produces
- `results/tables/pof_bin_shares.csv`: weighted PH2M/WH2M/Ricardian shares by demographic bins (with Dirichlet smoothing).
- `results/tables/state_month_htm_shares.parquet`: population-weighted expected agent-type shares by UF (state) and month.
- `results/tables/state_month_htm_shares_mc.parquet`: deterministic Monte Carlo diagnostic shares by UF and month.
- `results/diagnostics/monthly_htm_coverage.csv`: monthly coverage, exclusion, unmatched-bin, and national-share diagnostics.
- `results/tables/state_quarter_htm_shares.csv`: legacy state-quarter shares aggregated from the monthly expected output.
- `results/plots/choropleth_htm_YYYYQq.png`: four-panel choropleths per quarter (PH2M, WH2M, Total HtM, Ricardian).

## Directory Layout

### Tree (directories + key files, ~3 levels deep)
```text
.
├── Data/
│   ├── Dados_20230713/
│   │   ├── DOMICILIO.txt
│   │   ├── MORADOR.txt
│   │   ├── RENDIMENTO_TRABALHO.txt
│   │   ├── OUTROS_RENDIMENTOS.txt
│   │   └── ALUGUEL_ESTIMADO.txt
│   ├── Documentacao_20230713/
│   │   ├── Dicionarios de variaveis.xls
│   │   ├── Manual do Agente de Pesquisa.pdf
│   │   └── Estratos POF 2017-2018.xls
│   ├── pnad/  (placeholder/unused)
│   ├── pnadc_2022_1.rds
│   ├── pnadc_panel_9.csv
│   └── pnadc_panel_10.csv
├── PNAD-C/
│   ├── pnadc_panel_3.csv
│   ├── pnadc_panel_4.csv
│   ├── pnadc_panel_5.csv
│   ├── pnadc_panel_6.csv
│   ├── pnadc_panel_7.csv
│   ├── pnadc_panel_8.csv
│   └── pnadc_panel_9.csv
├── PNAD-C-Treated/
│   ├── pnadc_panel_5.csv
│   ├── pnadc_panel_6.csv
│   ├── pnadc_panel_7.csv
│   ├── test5.csv
│   ├── test6.csv
│   └── test7.csv
├── results/
│   ├── tables/
│   │   ├── pof_bin_shares.csv
│   │   ├── state_month_htm_shares.parquet
│   │   ├── state_month_htm_shares_mc.parquet
│   │   ├── state_quarter_htm_shares.csv
│   │   └── irf_*.csv
│   ├── plots/
│   │   ├── choropleth_htm_*.png
│   │   ├── irf_*.png
│   │   └── state_irf/
│   │       └── irf_state_mp_*.png
│   └── reports/
│       ├── irf_diagnostics_writeup.html
│       ├── irf_diagnostics_writeup.pdf
│       └── irf_diagnostics_writeup_files/
├── overleaf/
│   ├── main.tex
│   └── Graphs/
│       └── choropleth_htm_*.png
├── scripts/
│   ├── data_prep/
│   │   ├── pnad.r
│   │   └── install.R
│   ├── reporting/
│   │   └── irf_heterogeneity_final.R
│   ├── utils/
│   │   ├── convert_report_to_notebook.py
│   │   └── fix_notebook_markdown.py
│   └── README.md
├── analysis/
│   ├── test.r
│   └── test_approach_b.R
├── archive/
│   └── legacy/
│       └── irf_heterogeneity_analysis.R
├── tests/
│   └── test_htm_quintiles.py
├── htm_classification.py
├── generate_choropleths.py
├── main.ipynb
├── htm_classification_report.ipynb
├── htm_classification_report.html
├── requirements.txt
└── development_status.md
```

### Directory descriptions
`Data/`
- Source inputs for the POF-to-PNADC pipeline.
- `Data/Dados_20230713/`: the POF fixed-width text files (the pipeline reads a small set of these files).
- `Data/Documentacao_20230713/`: Excel/Document files used to parse fixed-width tables (notably `Dicionarios de variaveis.xls`) and supporting documentation.
- `Data/pnad/`: currently an empty/unused placeholder.

`PNAD-C/`
- Raw PNADC panel extracts (stored as CSV and/or RDS depending on preprocessing stage).
- The current Python pipeline uses the treated CSVs in `PNAD-C-Treated/` as inputs.

`PNAD-C-Treated/`
- Historical location for pre-filtered and derived PNADC extracts.
- The canonical classification script now defaults to root-level `pnadc_matched_with_periods.parquet`; pass `--pnad-parquet` for another monthly matched parquet.

`results/`
- Canonical destination for generated artifacts to keep repo root clean.
- `results/tables/`: generated CSV outputs from pipeline and diagnostics.
- `results/plots/`: generated PNG outputs (choropleths and IRFs).
- `results/reports/`: rendered analysis reports and companion `_files/` directories.
- `RESULTS_PROVENANCE.md`: artifact-to-script reproducibility mapping with rerun commands.

`scripts/`
- Organized location for non-core scripts. See `scripts/README.md` for canonical flow, deprecations, and guardrails.

`analysis/`
- Exploratory one-off scripts that are not part of the canonical production pipeline.

`archive/legacy/`
- Historical/superseded scripts retained for reference only.
- `archive/legacy/root_loose_files/` stores previously root-level ad hoc data/media files outside the canonical workflow.

`overleaf/`
- LaTeX project files for the written report/presentation.
- `overleaf/Graphs/` contains the choropleth images used by the paper (typically `choropleth_htm_*.png`).

`tests/`
- Unit tests (pytest) covering key calibration logic (e.g., quintile cut-point alignment behavior).

### Key scripts and notebooks
`htm_classification.py`
- End-to-end pipeline: POF classification -> demographic bin shares -> streamed PNADC parquet batches -> state x month expected shares -> Monte Carlo diagnostic shares -> optional legacy quarterly choropleths.
- Note: paths are resolved relative to the repository root containing `htm_classification.py`.
- Default output locations:
  - `results/tables/pof_bin_shares.csv`
  - `results/tables/state_month_htm_shares.parquet`
  - `results/tables/state_month_htm_shares_mc.parquet`
  - `results/diagnostics/monthly_htm_coverage.csv`
  - `results/tables/state_quarter_htm_shares.csv` (legacy aggregate)
  - `results/plots/choropleth_htm_YYYYQq.png`

`generate_choropleths.py`
- Generates per-quarter choropleth figures from the legacy `results/tables/state_quarter_htm_shares.csv` aggregate (downloads IBGE state boundaries).
- Default output directory: `results/plots/`.

`scripts/utils/convert_report_to_notebook.py` and `scripts/utils/fix_notebook_markdown.py`
- Utilities for converting and cleaning the exported HTML report into `htm_classification_report.ipynb`.

`scripts/data_prep/pnad.r`
- Helper script for pre-filtering large PNADC panel files into smaller CSV inputs used by the Python pipeline.

`scripts/data_prep/install.R`
- Minimal R setup helper for installing the `datazoom.social` dependency.

## Where scripts live
- Canonical run targets stay in root: `htm_classification.py`, `generate_choropleths.py`, `cumulative_irf_heterogeneity.py`.
- Supporting scripts are organized under `scripts/` by intent (`data_prep`, `reporting`, `utils`).
- Exploratory scripts live in `analysis/`; retired/superseded scripts live in `archive/legacy/`.

`main.ipynb`, `htm_classification_report.ipynb`, `htm_classification_report.html`
- Analysis notebooks and the rendered HTML report for the classification and results.

## How to run
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Run the pipeline:
   - `python3 htm_classification.py`
3. Common flags:
   - Skip choropleths: `python3 htm_classification.py --no-choropleth`
   - Legacy within-batch PNADC quintiling: `python3 htm_classification.py --per-quarter-quintiles`
   - Custom monthly matched PNADC parquet: `python3 htm_classification.py --pnad-parquet /path/to/pnadc_matched_with_periods.parquet`
   - Skip the legacy quarterly CSV: `python3 htm_classification.py --no-legacy-quarterly`

## Notes
- Choropleth generation requires `geopandas` and downloads IBGE boundaries at runtime.
- `cumulative_irf_heterogeneity.py` reads `results/tables/state_month_htm_shares.parquet` directly and falls back to quarterly interpolation only when the monthly parquet is absent.
