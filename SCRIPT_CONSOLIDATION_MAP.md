# Script Consolidation Map

This map classifies scripts by role and migration status.

## Canonical (production-facing)

- `htm_classification.py`
- `generate_choropleths.py`
- `cumulative_irf_heterogeneity.py`
- `pnad_faixa_pretreat.py` (shared helper module imported by canonical pipeline)
- `scripts/data_prep/pnad.r`
- `scripts/reporting/irf_heterogeneity_final.R`

## Exploratory

- `analysis/test.r`
- `analysis/test_approach_b.R`

## Legacy / Superseded

- `archive/legacy/irf_heterogeneity_analysis.R` -> replaced by `scripts/reporting/irf_heterogeneity_final.R`
- `archive/legacy/untitled:plan-cumulativeIrfHeterogeneity.prompt.md`
- `archive/legacy/conversation-export.html`
- `archive/legacy/conversation-export.json`
- `archive/legacy/new_function/`
- `archive/legacy/root_loose_files/` (previous root-level ad hoc data/media snapshots)

## Migration Notes

- Do not add new one-off scripts at repo root.
- New non-canonical scripts should be placed in `scripts/` or `analysis/`.
- When replacing a script, move the old version to `archive/legacy/` and document the replacement here.
