# Results Provenance Manifest

This file pairs generated artifacts under `results/` with the scripts that create them.
It is intended as a reproducibility map, not a source-code specification.

## Canonical Policy

- Files under `results/` are generated artifacts.
- Keep tracked outputs that are used for analysis, reporting, or paper figures.
- Ignore machine-specific junk and cache byproducts (for example `.DS_Store`, Python cache files).

## Artifact -> Producer Mapping

| Artifact family | Producer script | Minimal inputs | Re-run command |
| --- | --- | --- | --- |
| `results/tables/pof_bin_shares.csv` | `htm_classification.py` | POF fixed-width tables in `Data/Dados_20230713/` + dictionary workbook `Data/Documentacao_20230713/Dicionarios de variaveis.xls` | `python3 htm_classification.py --no-choropleth` |
| `results/tables/state_quarter_htm_shares.csv` | `htm_classification.py` | Same as above + PNADC parquet (`PNAD-C-Treated/pnad_matched.parquet` by default, or `--pnad-parquet`) | `python3 htm_classification.py --no-choropleth` |
| `results/tables/individual_agent_types.parquet` | `htm_classification.py` | Same as above | `python3 htm_classification.py --no-choropleth` |
| `results/plots/choropleth_htm_YYYYQq.png` | `htm_classification.py` (step 6) or `generate_choropleths.py` | `results/tables/state_quarter_htm_shares.csv` + IBGE shapefile download at runtime | `python3 generate_choropleths.py --input results/tables/state_quarter_htm_shares.csv --output-dir results/plots` |
| `results/datasets/state_monthly_covariates.csv` | `cumulative_irf_heterogeneity.py` | `results/tables/state_quarter_htm_shares.csv` + `results/tables/aggregate_state_monthly_shock_h2m.csv` | `python3 cumulative_irf_heterogeneity.py` |
| `results/tables/irf_state_level/irf_state_pooled_monthly.csv` | `cumulative_irf_heterogeneity.py` | Same as above | `python3 cumulative_irf_heterogeneity.py` |
| `results/tables/irf_state_level/irf_state_pooled_type_irfs.csv` | `cumulative_irf_heterogeneity.py` | Same as above | `python3 cumulative_irf_heterogeneity.py` |
| `results/tables/irf_state_level/irf_state_by_state_monthly.csv` | `cumulative_irf_heterogeneity.py` | Same as above | `python3 cumulative_irf_heterogeneity.py` |
| `results/tables/irf_state_level/irf_state_by_state_type_irfs.csv` | `cumulative_irf_heterogeneity.py` | Same as above | `python3 cumulative_irf_heterogeneity.py` |
| `results/tables/irf_state_level/irf_state_regional_monthly.csv` | `cumulative_irf_heterogeneity.py` | Same as above | `python3 cumulative_irf_heterogeneity.py` |
| `results/tables/irf_state_level/irf_state_regional_type_irfs.csv` | `cumulative_irf_heterogeneity.py` | Same as above | `python3 cumulative_irf_heterogeneity.py` |
| `results/plots/irf_state_level/*.png` | `cumulative_irf_heterogeneity.py` | Same as above | `python3 cumulative_irf_heterogeneity.py` |

## Additional Produced Files

The repository also contains other generated tables, diagnostics, and report assets under:

- `results/tables/`
- `results/diagnostics/`
- `results/reports/`
- `results/plots/`

These come from analysis/reporting scripts and notebook render steps (including IRF diagnostics/report workflows). Treat them as generated outputs and regenerate from source scripts/notebooks when upstream logic changes.
