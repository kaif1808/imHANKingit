# Development Status

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
