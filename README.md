# ImHANKingIt

## Project (brief)
ImHANKingIt is a research pipeline that builds a time-series of Hand-to-Mouth (HtM) agent-type shares for Brazil, following the Kaplan-Violante-Weidner (2014) framework.

Starting from the POF 2017-18 household budget survey (fixed-width text tables), the pipeline classifies individuals into three agent types:
- PH2M: Poor Hand-to-Mouth (low liquid and low illiquid assets)
- WH2M: Wealthy Hand-to-Mouth (low liquid, high illiquid assets)
- Ricardian: sufficient liquid buffer to smooth consumption

The resulting type shares are transferred to the PNADC quarterly labour-force survey via demographic bin construction, merge, and a Monte Carlo assignment step, producing a state x quarter panel of type shares suitable for HANK calibration.

## What the pipeline produces
- `results/tables/pof_bin_shares.csv`: weighted PH2M/WH2M/Ricardian shares by demographic bins (with Dirichlet smoothing).
- `results/tables/state_quarter_htm_shares.csv`: population-weighted agent-type shares by UF (state) and quarter.
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
├── chloropleths/  (empty/legacy)
├── results/
│   ├── tables/
│   │   ├── pof_bin_shares.csv
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
├── tests/
│   └── test_htm_quintiles.py
├── htm_classification.py
├── generate_choropleths.py
├── convert_report_to_notebook.py
├── fix_notebook_markdown.py
├── pnad.r
├── install.R
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
- Pre-filtered and derived PNADC CSVs for the Python pipeline.
- The main script currently expects `test5.csv`, `test6.csv`, and `test7.csv` (plus optional `pnadc_panel_5/6/7.csv`).

`chloropleths/`
- Kept as an empty/legacy folder.

`results/`
- Canonical destination for generated artifacts to keep repo root clean.
- `results/tables/`: generated CSV outputs from pipeline and diagnostics.
- `results/plots/`: generated PNG outputs (choropleths and IRFs).
- `results/reports/`: rendered analysis reports and companion `_files/` directories.

`overleaf/`
- LaTeX project files for the written report/presentation.
- `overleaf/Graphs/` contains the choropleth images used by the paper (typically `choropleth_htm_*.png`).

`tests/`
- Unit tests (pytest) covering key calibration logic (e.g., quintile cut-point alignment behavior).

### Key scripts and notebooks
`htm_classification.py`
- End-to-end pipeline: POF classification -> demographic bin shares -> PNADC merge -> Monte Carlo assignment -> state x quarter shares -> optional choropleths.
- Note: `BASE_DIR` is currently hardcoded to a local path inside this repo.
- Default output locations:
  - `results/tables/pof_bin_shares.csv`
  - `results/tables/state_quarter_htm_shares.csv`
  - `results/plots/choropleth_htm_YYYYQq.png`

`generate_choropleths.py`
- Generates per-quarter choropleth figures from `results/tables/state_quarter_htm_shares.csv` (downloads IBGE state boundaries).
- Default output directory: `results/plots/`.

`convert_report_to_notebook.py` and `fix_notebook_markdown.py`
- Utilities for converting and cleaning the exported HTML report into `htm_classification_report.ipynb`.

`pnad.r`
- Helper script for pre-filtering large PNADC panel files into smaller CSV inputs used by the Python pipeline.

`install.R`
- Minimal R setup helper for installing the `datazoom.social` dependency.

`main.ipynb`, `htm_classification_report.ipynb`, `htm_classification_report.html`
- Analysis notebooks and the rendered HTML report for the classification and results.

## How to run
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Run the pipeline:
   - `python3 htm_classification.py`
3. Common flags:
   - Skip choropleths: `python3 htm_classification.py --no-choropleth`
   - Alternative quintiling: `python3 htm_classification.py --per-quarter-quintiles`

## Notes
- Choropleth generation requires `geopandas` and downloads IBGE boundaries at runtime.
- If you move the repo, update `BASE_DIR` in `htm_classification.py` (the pipeline uses local paths).
