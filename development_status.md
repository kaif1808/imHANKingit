# Development Status

## Latest Update — 2026-04-30

### Root clutter reduction: non-script loose files archived

Performed a second root-cleanup pass to move non-script loose artifacts out of the repository root and into a dedicated legacy holding area.

**What was done:**

- Moved previously root-level ad hoc files to `archive/legacy/root_loose_files/`:
  - `consume_state.csv`, `monetary_shocks.csv`
  - `pnadc_2016_1.rds`, `pnadc_2017_1.rds`, `pnadc_2018_1.rds`, `pnadc_2019_1.rds`
  - `pnadc_panel_3.csv`, `pnadc_panel_4.csv`
  - `plotnine 1.png`, `Voicy_YAHOO.mp3`
- Removed root cache folder `__pycache__/`.
- Retired empty `chloropleths/` legacy directory.
- Updated docs to reflect new location of loose root artifacts:
  - `README.md`
  - `SCRIPT_CONSOLIDATION_MAP.md`

**Updated files:** `README.md`, `SCRIPT_CONSOLIDATION_MAP.md`, `development_status.md`, plus file relocations under `archive/legacy/root_loose_files/`

## Latest Update — 2026-04-30

### Script organization overhaul (phase 1) + consolidation baseline (phase 2)

Reduced root-level clutter by reorganizing loose scripts into purpose-based folders, then established canonical workflow and guardrails for ongoing script maintenance.

**What was done:**

- Created script organization directories:
  - `scripts/data_prep/`
  - `scripts/reporting/`
  - `scripts/utils/`
  - `analysis/`
  - `archive/legacy/`
- Rehomed loose scripts from repo root:
  - `convert_report_to_notebook.py` -> `scripts/utils/`
  - `fix_notebook_markdown.py` -> `scripts/utils/`
  - `pnad.r` and `install.R` -> `scripts/data_prep/`
  - `irf_heterogeneity_final.R` -> `scripts/reporting/`
  - `test.r` and `test_approach_b.R` -> `analysis/`
- Archived non-canonical artifacts and superseded scripts under `archive/legacy/`, including:
  - `irf_heterogeneity_analysis.R` (superseded)
  - old planning/export artifacts and `new_function/`
- Added script documentation:
  - `scripts/README.md` (folder purpose, canonical workflow, deprecations, guardrails)
  - `SCRIPT_CONSOLIDATION_MAP.md` (canonical vs exploratory vs legacy classification)
- Updated root `README.md` with a clear “Where scripts live” section and moved-path references.
- Added `tests/test_repo_structure.py` as a lightweight guardrail so script clutter does not regress.

**Updated files:** `README.md`, `development_status.md`, `scripts/README.md`, `SCRIPT_CONSOLIDATION_MAP.md`, `tests/test_repo_structure.py`, plus script relocations across `scripts/`, `analysis/`, and `archive/legacy/`

## Latest Update — 2026-04-30

### Repository hygiene cleanup + results provenance manifest

Completed a safe repo-hygiene pass focused on keeping generated research outputs while reducing git noise and documenting reproducibility ownership for `results/`.

**What was done:**

- Added stronger ignore rules in `.gitignore` for machine-local clutter (`.DS_Store`) and Python cache artifacts (`__pycache__`, `*.py[cod]`), plus generated report companion folders (`*_files/`).
- Removed tracked macOS metadata files under `results/`:
  - `results/.DS_Store`
  - `results/plots/.DS_Store`
  - `results/tables/.DS_Store`
  - `results/reports/irf_diagnostics_writeup_files/.DS_Store`
- Added `RESULTS_PROVENANCE.md` with explicit artifact family -> producer script mapping and rerun commands for:
  - `htm_classification.py`
  - `generate_choropleths.py`
  - `cumulative_irf_heterogeneity.py`
- Updated `README.md` to point to `RESULTS_PROVENANCE.md` as the canonical provenance reference for generated outputs.

**Updated files:** `.gitignore`, `RESULTS_PROVENANCE.md`, `README.md`, `development_status.md`

## Latest Update — 2026-04-24

### HTM pipeline: PNADC input from `pnad_matched.parquet`

Switched the PNAD-C stage of `htm_classification.py` from reading and stacking multiple pretreated CSVs to a single Parquet file, with a CLI override and explicit error if the file is missing.

**What was done:**

- **Input:** `pd.read_parquet` on `PNAD-C-Treated/pnad_matched.parquet` by default, or `--pnad-parquet PATH`.
- **Dependencies:** added `pyarrow` to `requirements.txt` for reliable Parquet I/O.
- **Pretreated format:** added `pnad_faixa_pretreat.py` with `faixa_idade_to_age` and `faixa_educ_to_vd3004` (DataZoom string labels → numeric age and VD3004 codes), plus `tests/test_pnad_faixa_pretreat.py`.
- **Fix:** `argparse.ArgumentParser` name typo; removed unused `pyreadr` import from the classification script.

**Updated files:** `htm_classification.py`, `requirements.txt`, `pnad_faixa_pretreat.py`, `tests/test_pnad_faixa_pretreat.py`, `development_status.md`

## Latest Update — 2026-04-20

### BSE cover letter: LaTeX source and one-page PDF

Added a formal predoctoral application cover letter as standalone LaTeX, compiled to a single-page PDF alongside the existing markdown draft.

**What was done:**
- Added `overleaf/coverletter/COVER_LETTER_KAI_FAULKNER_BSE.tex` (Times-style body via `newtx`, BSE letterhead with name and `kai.faulkner@bse.eu`, inside address for Professor Jan Eeckhout at BSE, subject line with ERC ref 101198932, British English via `babel`)
- Generated `overleaf/coverletter/COVER_LETTER_KAI_FAULKNER_BSE.pdf` (verified one page via `pdfinfo`)
- Added `overleaf/coverletter/.gitignore` for LaTeX auxiliary files (`*.aux`, `*.log`, `latexmk` files, etc.)

**Build:** `cd overleaf/coverletter && latexmk -pdf -interaction=nonstopmode COVER_LETTER_KAI_FAULKNER_BSE.tex`

**Updated files:**
- `overleaf/coverletter/COVER_LETTER_KAI_FAULKNER_BSE.tex` — new
- `overleaf/coverletter/COVER_LETTER_KAI_FAULKNER_BSE.pdf` — new
- `overleaf/coverletter/.gitignore` — new
- `development_status.md` — this entry

## Latest Update — 2026-04-17

### PNAD-C variable inventory documentation added

Created a complete markdown inventory of PNAD-C variables referenced by the classification pipeline, split by supported input schema and annotated by usage/requirement level.

**What was done:**
- Added `PNADC_REQUIRED_VARIABLES.md` at repo root
- Documented variables used in both branches (`UF`, `Ano`, `Trimestre`)
- Documented DataZoom-pretreated branch required columns (`faixa_idade`, `sexo`, `faixa_educ`, `Habitual`, `rendimento_habitual_real`, `ID_DOMICILIO`)
- Documented raw PNAD-C branch required columns (`V2009`, `V2007`, `VD3004`, `V1028`, `V2001`) and optional income column handling
- Documented conditional labor-status columns (`formal`, `informal`, `ocupado`, `desocupado`, `conta_propria`, `fora_forca_trab`)
- Added minimal input checklists and derived-column notes for both schema variants

**Updated files:**
- `PNADC_REQUIRED_VARIABLES.md` — new full variable inventory for PNAD-C pipeline inputs
- `development_status.md` — logged this documentation update

## Latest Update — 2026-04-17

### Repository cleanup: moved generated artifacts under `results/` and redirected PNG defaults

Reorganized output deposition so generated tables, plots, and rendered diagnostics no longer pollute the repo root.

**What was done:**
- Standardized output directories: `results/tables/`, `results/plots/`, `results/plots/state_irf/`, and `results/reports/`
- Updated `htm_classification.py` defaults:
  - `pof_bin_shares.csv` -> `results/tables/pof_bin_shares.csv`
  - `state_quarter_htm_shares.csv` -> `results/tables/state_quarter_htm_shares.csv`
  - `choropleth_htm_*.png` -> `results/plots/choropleth_htm_*.png`
- Updated `generate_choropleths.py` defaults:
  - `--input` now defaults to `results/tables/state_quarter_htm_shares.csv`
  - `--output-dir` now defaults to `results/plots/`
- Relocated existing generated root artifacts:
  - IRF and choropleth PNGs -> `results/plots/` (state-level IRFs -> `results/plots/state_irf/`)
  - IRF and pipeline CSV outputs -> `results/tables/`
  - IRF rendered report outputs (`.html`, `.pdf`, `_files/`) -> `results/reports/`

**Updated files:**
- `htm_classification.py` — default output paths moved to `results/tables` and `results/plots`
- `generate_choropleths.py` — default input/output paths moved to `results/` subfolders
- `README.md` — documented canonical output locations and updated repo tree

## Latest Update — 2026-04-16

### README: Added project overview, directory tree, and repo guide

Expanded `README.md` from a title-only placeholder into a practical repository guide for contributors and future analysis work.

**What was done:**
- Added a brief project description explaining the POF -> PNADC HTM classification pipeline
- Added a 3-level directory tree with directories and key files
- Added descriptions for `Data/`, `PNAD-C/`, `PNAD-C-Treated/`, `overleaf/`, `chloropleths/`, and `tests/`
- Added short notes for the main scripts and notebooks
- Added a brief run section covering dependency install, main pipeline execution, and key CLI flags
- Documented that `BASE_DIR` in `htm_classification.py` is path-sensitive

**Updated files:**
- `README.md` — full project overview, directory tree, directory descriptions, and run instructions

## Latest Update — 2026-03-10

### Overleaf main.tex: Expanded with full report content

Expanded `overleaf/main.tex` with all relevant information from `htm_classification_report.ipynb`.

**What was done:**
- **Introduction:** Added literature refs (Carvalho & Zilberman 2022; De Souza 2023); clarified POF→PNADC transfer
- **Data Sources:** Added Key variables column
- **New frame: POF Table Structure** — 5 files and key columns
- **Classification:** QUADRO 56 detail for Bolsa Família; expanded parameter descriptions
- **Bin Matching:** Notes column on Six Bin Dimensions; new Mismatch Problem frame (60.2% match, root causes); Before/After table; Strategy Comparison table (A, D, G, I)
- **Validation:** Monte Carlo note; Warning block on WH2M elevation
- **Regional Results:** New Key Regional Patterns frame (PH2M/WH2M/Ricardian by region)
- **Robustness:** λ sweep 0.25–1.50; sensitivity findings
- **Outputs:** Dirichlet smoothing, 4-panel choropleth description

**Updated files:**
- `overleaf/main.tex` — 25 frames, 313 lines (was 237)

## Prior Update — 2026-03-10

### HTM Classification Report: Updated for 8 quarters (2017 Q1 – 2018 Q4)

Restructured `htm_classification_report.ipynb` to align with the current pipeline (panels 5, 6, 7 covering 2017 Q1 – 2018 Q4).

**What was done:**
- **Data Sources table:** PNADC row updated to 2017 Q1 – 2018 Q4 (8 quarters), CSV format (test5/6/7.csv)
- **Pipeline Architecture:** Added Step 6 (choropleth maps per quarter)
- **Shared config cell:** Added PNADC_CSV_FILES and PNADC_DATA_DIR aligned with htm_classification.py
- **Output table:** Dynamic quarter/row counts (27 states × N quarters)
- **Match rate footnotes:** "Illustrative; actual values depend on PNADC panels loaded"
- **Choropleth caption:** Clarified one map generated per quarter

**Updated files:**
- `htm_classification_report.ipynb` — Data Sources, pipeline step 6, config, output table, footnotes, figure caption

## Prior Update — 2026-03-09

### HTM Classification: 2017 Q4 Ricardian calibration fixes

Addressed the ~10pp drop in Ricardian agent share from 2017 Q3 to Q4 by fixing POF–PNADC quintile alignment and adding diagnostics.

**What was done:**
- **POF–PNADC quintile cut-point mismatch (fix #1):** PNADC now uses POF income quintile cut-points instead of within-PNADC ranks, so bin matching aligns on the same income scale. This largely eliminated the 2017 Q4 discontinuity (e.g. UF 33: 70%→59% became 59%→60%).
- **Per-quarter quintiles option (fix #2):** Added `--per-quarter-quintiles` flag to use within-quarter quintiles instead of POF cut-points (reduces seasonal bias when enabled).
- **Per-quarter diagnostics:** Added diagnostic block outputting, by year–quarter: n_obs, n_unmatched bins, mean pc_income, quintile shares (Q1–Q5), labor status shares (formal, informal, self_employed, unemployed, inactive).

**Updated files:**
- `htm_classification.py` — POF retbins for cut-points; PNADC quintile logic (POF cut-points or per-quarter); `--per-quarter-quintiles` flag; per-quarter diagnostic table

## Prior Update — 2026-03-09

### HTM Classification: 8-panel CSV input and choropleth generation

Modified `htm_classification.py` to use PNADC panel CSV files and generate per-quarter choropleth maps.

**What was done:**
- Replaced PNADC RDS loading with CSV loading from `pnadc_panel_5.csv`, `pnadc_panel_6.csv`, `pnadc_panel_7.csv`
- Added Step 6: choropleth map generation per quarter (PH2M, WH2M, total HtM, Ricardian)
- Downloads IBGE state boundaries from geoftp.ibge.gov.br; graceful fallback if download fails
- Added `--no-choropleth` flag to skip map generation
- Output: `state_quarter_htm_shares.csv` (54 rows: 27 states × 2 quarters from current panels), `choropleth_htm_{year}Q{quarter}.png` per quarter

**Updated files:**
- `htm_classification.py` — CSV load, choropleth step, argparse
- `requirements.txt` — geopandas already present

### PNADC panel filtering helper (R)

Added a lightweight R helper script to pre-filter large PNADC panel CSVs down to only the columns required by the PNADC pipeline in `htm_classification.py`, writing per-panel `test5/6/7.csv` files into `PNAD-C-Treated` while processing each panel sequentially with explicit garbage collection.

**Updated files:**
- `pnad.r` — new `process_panel()` helper using `data.table::fread/fwrite` and per-panel `gc()` for memory efficiency

### Per-quarter choropleth generation from CSV

Added standalone script and updated notebook to generate per-quarter choropleth maps from `state_quarter_htm_shares.csv` without running the full pipeline.

**What was done:**
- Created `generate_choropleths.py` — reads CSV, downloads IBGE shapefile, produces one 4-panel choropleth (PH2M, WH2M, total HtM, Ricardian) per quarter; supports `--input` and `--output-dir`
- Updated `htm_classification_report.ipynb` Section 6 — replaced single aggregated map with per-quarter loop; saves `choropleth_htm_{year}Q{quarter}.png` for each quarter; displays first quarter as example

**Updated files:**
- `generate_choropleths.py` — new standalone script
- `htm_classification_report.ipynb` — cells 12–13: per-quarter generation and display

## Prior Update — 2026-03-05

### HTM Classification Report → Jupyter Notebook conversion

Added `convert_report_to_notebook.py` and the generated `htm_classification_report.ipynb`.

**What was done:**
- Wrote a BeautifulSoup-based HTML → `.ipynb` converter (`convert_report_to_notebook.py`)
- Parses the JupyterLab-style HTML export (`htm_classification_report.html`) and extracts all 20 cells:
  - 8 markdown cells (with rendered HTML headings, tables, LaTeX)
  - 12 code cells (Python source, Quarto `#| label:` directives preserved)
- Outputs captured: 7 HTML DataFrames, 2 base64 PNG choropleth maps, 1 stream output
- `BASE_DIR` path corrected from `/Users/matt/…` to `/Users/kai/Desktop/imHANKingit`
- Notebook validated as nbformat 4.5 compliant

**Updated files:**
- `convert_report_to_notebook.py` — new conversion utility
- `htm_classification_report.ipynb` — generated notebook
- `requirements.txt` — added `geopandas>=0.14`, `beautifulsoup4>=4.12`

## Prior work

- `htm_classification.py` — full 5-step KVW classification pipeline (POF → PNADC)
- `main.ipynb` — main analysis notebook
- `htm_classification_diagnosis.ipynb`, `htm_classification_diagnosis-1.ipynb` — diagnostic notebooks
- Output CSVs: `pof_bin_shares.csv`, `state_quarter_htm_shares.csv`
- PNADC RDS files: 2015–2019 Q1 panels
