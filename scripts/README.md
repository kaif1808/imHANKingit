# Scripts Guide

This directory contains non-core scripts organized by purpose.

## Canonical Entry Points (Kept in Repo Root)

- `htm_classification.py` — main POF -> PNADC classification pipeline.
- `generate_choropleths.py` — standalone choropleth generation from state-quarter shares.
- `cumulative_irf_heterogeneity.py` — state-level monthly IRF heterogeneity workflow.

## Folder Structure

- `scripts/data_prep/` — data preparation helpers.
  - `pnad.r` — PNADC panel pre-filter helper.
  - `install.R` — helper for R-side dependency setup.
- `scripts/reporting/` — report-generation scripts.
  - `irf_heterogeneity_final.R` — canonical IRF reporting script.
- `scripts/utils/` — utility scripts used occasionally.
  - `convert_report_to_notebook.py`
  - `fix_notebook_markdown.py`

## Exploratory And Legacy Locations

- `analysis/` — exploratory one-off scripts.
- `archive/legacy/` — historical/superseded files kept for reference.

### Deprecated Replacements

- `archive/legacy/irf_heterogeneity_analysis.R` -> replaced by `scripts/reporting/irf_heterogeneity_final.R`.

## Canonical Workflow

1. Optional prep: `scripts/data_prep/pnad.r`
2. Classify: `python3 htm_classification.py`
3. Heterogeneity IRFs: `python3 cumulative_irf_heterogeneity.py`
4. Choropleths (standalone rerun): `python3 generate_choropleths.py`

## Hygiene Guardrails For New Scripts

- Keep root limited to canonical entrypoints and core project files.
- Put new helpers in `scripts/` by intent (`data_prep`, `reporting`, `utils`).
- Put one-off experiments in `analysis/`.
- Move superseded files to `archive/legacy/` instead of deleting immediately.
