# Individual IRF data requirements

Part 2 was not executed because required fields are missing in results/tables/individual_agent_types.parquet.

## Required keys
- `uf_code` (state)
- `year`, `month` for monthly analysis and quarterly aggregation
- `agent_type` in {PH2M, WH2M, Ricardian}

## Required outcome
- one individual consumption variable (e.g., `consumption_real`)

## Detected schema summary
- has_state_key: True
- has_quarter_key: True
- has_month_key: False
- has_type_key: True
- has_consumption_column: False

## Next step
Provide individual consumption at monthly (preferred) or at least quarterly frequency in a mergeable file keyed by `id_ind`/`uf_code` and time.