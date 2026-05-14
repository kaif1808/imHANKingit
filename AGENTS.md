# Repository Guidelines

## Project Structure & Module Organization
This repository centers on three root-level entry points: `htm_classification.py`, `generate_choropleths.py`, and `cumulative_irf_heterogeneity.py`.

Use these directories consistently:
- `scripts/data_prep/`: preprocessing helpers (Python/R).
- `scripts/reporting/`: reporting and IRF scripts.
- `scripts/utils/`: utility and maintenance scripts.
- `tests/`: pytest suite (`test_*.py`).
- `results/`: generated tables, diagnostics, and plots.
- `analysis/`: exploratory work.
- `archive/legacy/`: superseded artifacts kept for reference.

## Build, Test, and Development Commands
- `pip install -r requirements.txt`: install Python dependencies.
- `python3 htm_classification.py`: run the canonical monthly HtM classification pipeline.
- `python3 htm_classification.py --no-choropleth`: skip map generation for faster runs.
- `python3 generate_choropleths.py --input results/tables/state_quarter_htm_shares.csv --output-dir results/plots`: regenerate maps only.
- `python3 cumulative_irf_heterogeneity.py`: run monthly IRF heterogeneity workflow.
- `pytest tests/`: run full test suite.
- `pytest tests/test_htm_monthly_batch.py -v`: run targeted regression checks.

## Coding Style & Naming Conventions
- Follow PEP 8 for Python: 4-space indentation, snake_case for functions/variables, UPPER_SNAKE_CASE for constants.
- Keep scripts task-focused and place new non-canonical scripts under `scripts/` (not repo root).
- Prefer descriptive filenames aligned with purpose, e.g., `state_month_*`, `irf_*`, `pnad_*`.
- For R scripts, use clear snake_case object names and keep side effects (file writes) explicit.

## Testing Guidelines
- Framework: `pytest` with shared fixtures in `tests/conftest.py`.
- Name tests `test_<behavior>.py` and test functions `test_<expected_outcome>()`.
- Add or update tests when changing pipeline logic, schema expectations, or aggregation behavior.
- Before PRs, run `pytest tests/` and include any relevant output file checks in `results/diagnostics/`.

## Commit & Pull Request Guidelines
- Commit style in history is concise and imperative; prefer scoped messages like `feat(reporting): add aggregate IRF chart`.
- Keep commits focused (one logical change per commit).
- PRs should include: objective, key data/logic changes, commands run (tests/pipeline), and affected outputs.
- Link related issues/tasks when available and include plot/table screenshots when visual outputs change.
