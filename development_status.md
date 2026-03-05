# Development Status

## Latest Update — 2026-03-05

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
