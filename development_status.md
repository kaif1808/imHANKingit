# Development Status

## Latest Update — 2026-03-09

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
