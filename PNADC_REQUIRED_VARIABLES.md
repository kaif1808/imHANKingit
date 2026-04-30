# PNAD-C Required Variable Inventory

This document lists the PNAD-C columns referenced by `htm_classification.py` for the streamed monthly parquet stage.

## Canonical Monthly Parquet

The default input is `pnadc_matched_with_periods.parquet` in the repository root, or another file passed with `--pnad-parquet`.

The pipeline reads the parquet with `pyarrow.parquet.ParquetFile.iter_batches(...)` and selects only the columns needed for monthly aggregation and diagnostics.

### Required input columns

| Variable | Required? | Where used |
|---|---|---|
| `UF` | Yes | Converted to `uf_code`, mapped to macro-region bins, and used for state-month aggregation. |
| `V2009` | Yes | Raw age, used for the age >= 15 filter and age-group binning. |
| `V2007` | Yes | Raw sex code, used for gender binning. |
| `VD3004` | Yes | Raw education code, used for education-group binning. |
| `V2001` | Yes | Raw household size, used to compute per-capita income. |
| `rendimento_habitual_real` | Yes | Raw habitual real income, used to compute per-capita income. |
| `ref_month_yyyymm` | Yes | Monthly period key used for `year`, `month`, coverage diagnostics, and aggregation. Rows with missing values are excluded from monthly aggregation and counted in diagnostics. |
| `ref_month_in_year` | Yes | Month number. If invalid, the month is recovered from `ref_month_yyyymm`. |
| `weight_monthly` | Yes | Monthly survey weight used for all expected and Monte Carlo weighted shares. Rows with missing values are excluded from monthly aggregation and counted in diagnostics. |

### Required identifier availability

At least one of these must be present:

| Variable | Required? | Where used |
|---|---|---|
| `id_rs` | Preferred | Stable panel identifier for deterministic Monte Carlo draws. |
| `id_ind` | Fallback | Used for deterministic Monte Carlo draws when `id_rs` is missing. |

Rows with missing `id_rs` must have non-missing `id_ind`.

### Optional labor-status columns

These improve bin matching quality when present. Missing columns default to zero and therefore classify through the remaining available indicators.

| Variable | Required? | Where used |
|---|---|---|
| `formal` | Optional | `formal == 1` classifies worker as formal. |
| `conta_propria` | Optional | `conta_propria == 1` classifies worker as self-employed. |
| `informal` | Optional | Helps classify worker as informal. |
| `ocupado` | Optional | Also triggers informal classification fallback. |
| `desocupado` | Optional | `desocupado == 1` classifies worker as unemployed. |
| `fora_forca_trab` | Optional | Read for schema continuity; current classifier otherwise defaults unassigned rows to inactive. |

### Ignored legacy/pretreated columns

The monthly parquet may contain `faixa_idade`, `sexo`, `faixa_educ`, `Habitual`, and `V1028`, but the monthly pipeline intentionally uses the raw PNADC columns listed above. In particular, monthly aggregation uses `weight_monthly`, not `V1028` or `Habitual`.

## Derived columns

`year`, `month`, `uf_code`, `age`, `sex_code`, `vd3004`, `pc_income_pnadc`, `macro_region`, `age_group`, `gender`, `education_group`, `labor_status`, `pc_income_quintile`, `bin_key`, `p_ph2m`, `p_wh2m`, `p_ric`, and deterministic `agent_type` are derived inside `htm_classification.py`.

## Outputs

- `results/tables/state_month_htm_shares.parquet`: canonical expected probability-weighted state-month shares.
- `results/tables/state_month_htm_shares_mc.parquet`: deterministic Monte Carlo diagnostic state-month shares.
- `results/diagnostics/monthly_htm_coverage.csv`: coverage, exclusion, unmatched-bin, weight, and national monthly share diagnostics.
- `results/tables/state_quarter_htm_shares.csv`: optional legacy quarterly aggregate, written unless `--no-legacy-quarterly` is used.
