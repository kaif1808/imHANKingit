# ImHANKingIt — Full Dataset Schema

This document describes every dataset in the pipeline: inputs, intermediates, primary outputs, regression outputs, and diagnostics. All file paths are relative to the repository root.

---

## Table of Contents

1. [Input Datasets](#1-input-datasets)
2. [Intermediate / Lookup Tables](#2-intermediate--lookup-tables)
3. [Primary Pipeline Outputs](#3-primary-pipeline-outputs)
4. [Panel & Regression Inputs](#4-panel--regression-inputs)
5. [POF Summary Tables](#5-pof-summary-tables)
6. [IRF / Regression Output Datasets](#6-irf--regression-output-datasets)
7. [Diagnostics](#7-diagnostics)
8. [Key Classification Parameters](#8-key-classification-parameters)

---

## 1. Input Datasets

### 1a. `pnadc_matched_with_periods.parquet` — Primary PNADC input

Default location: repo root. Override with `--pnad-parquet /path/to/file.parquet`.  
Read via `pyarrow.parquet.ParquetFile.iter_batches(...)` in 500k-row chunks.

#### Required columns

| Variable | Type | Description |
|---|---|---|
| `UF` | int | State IBGE code (e.g. 11 = Rondônia, 53 = DF) |
| `V2009` | int | Raw age in years |
| `V2007` | int | Sex code (1 = male, 2 = female) |
| `VD3004` | int | Education level code (1–7) |
| `V2001` | int | Household size |
| `rendimento_habitual_real` | float | Real habitual household income (BRL) |
| `ref_month_yyyymm` | int | Period key, e.g. `201201`; missing rows excluded from aggregation |
| `ref_month_in_year` | int | Month number (1–12); recovered from `ref_month_yyyymm` if invalid |
| `weight_monthly` | float | Monthly survey expansion weight; missing rows excluded from aggregation |

#### Required identifiers (at least one must be present)

| Variable | Type | Description |
|---|---|---|
| `id_rs` | string | **Preferred.** Stable panel identifier for deterministic Monte Carlo draws |
| `id_ind` | string | **Fallback.** Used when `id_rs` is missing; must be non-null if `id_rs` is null |

#### Optional labour-status columns

Missing columns default to zero and fall through to the remaining available indicators.

| Variable | Type | Description |
|---|---|---|
| `formal` | int | 1 = formal employee |
| `conta_propria` | int | 1 = self-employed |
| `informal` | int | 1 = informal worker |
| `ocupado` | int | 1 = employed (informal classification fallback) |
| `desocupado` | int | 1 = unemployed |
| `fora_forca_trab` | int | Read for schema continuity; unassigned rows default to inactive |

#### Ignored legacy columns

`faixa_idade`, `sexo`, `faixa_educ`, `Habitual`, `V1028` — may be present but are intentionally unused by the monthly pipeline.

#### Derived columns (computed inside `htm_classification.py`)

| Derived column | Source |
|---|---|
| `year`, `month` | Parsed from `ref_month_yyyymm` |
| `uf_code` | Mapped from `UF` |
| `age` | From `V2009` |
| `sex_code` | From `V2007` |
| `vd3004` | From `VD3004` |
| `pc_income_pnadc` | `rendimento_habitual_real / V2001` |
| `macro_region` | Mapped from `uf_code`: North / Northeast / Center-West / Southeast / South |
| `age_group` | Binned: 15–24 / 25–34 / 35–44 / 45–54 / 55–64 / 65+ |
| `gender` | male / female |
| `education_group` | no_education / primary / secondary / tertiary |
| `labor_status` | formal / informal / self_employed / unemployed / inactive |
| `pc_income_quintile` | Q1–Q5 using POF-derived cut-points |
| `bin_key` | `macro_region\|age_group\|gender\|education_group\|pc_income_quintile\|labor_status` |
| `p_ph2m`, `p_wh2m`, `p_ric` | Merged from `pof_bin_shares.csv` on `bin_key` |
| `agent_type` | Deterministic Monte Carlo draw from the three probabilities (seed = 42) |

---

### 1b. POF 2017–18 Fixed-Width Microdata (`Data/Dados_20230713/`)

Parsed via `Data/Documentacao_20230713/Dicionarios de variaveis.xls`. These raw files are never loaded directly by downstream scripts — only the derived `pof_bin_shares.csv` is used after classification.

| Concept | Role in classification |
|---|---|
| Monthly household income | Denominator for liquid and illiquid asset ratios |
| Liquid assets (checking, savings) | Must be < `LIQUID_THRESH × income` to be HtM |
| Illiquid assets (real estate, pension, business equity) | Must be ≥ `ILLIQUID_MULT × income` to be Wealthy HtM |
| Household size | Used to compute per-capita income |
| Demographic variables | Used to construct the 6-dimensional `bin_key` |

---

## 2. Intermediate / Lookup Tables

### 2a. `results/tables/pof_bin_shares.csv` — POF demographic bin lookup

One row per unique demographic bin. Merged onto PNADC records during stage 2 of the pipeline.

| Column | Type | Description |
|---|---|---|
| `bin_key` | string | `macro_region\|age_group\|gender\|education_group\|pc_income_quintile\|labor_status` |
| `p_ph2m` | float | Dirichlet-smoothed probability of Poor HtM |
| `p_wh2m` | float | Dirichlet-smoothed probability of Wealthy HtM |
| `p_ric` | float | Dirichlet-smoothed probability of Ricardian |
| `weighted_n` | float | Survey-weighted household count in this bin |
| `raw_n` | int | Unweighted household count |
| `small_bin_flag` | int | 1 if `weighted_n < MIN_WEIGHTED_N` (Dirichlet smoothing active) |

---

## 3. Primary Pipeline Outputs

### 3a. `results/tables/state_month_htm_shares.parquet` — Canonical expected-shares output

Probability-weighted aggregation of PNADC records to state × month level. This is the primary input to all downstream regression scripts.

| Column | Type | Description |
|---|---|---|
| `uf_code` | int64 | State IBGE code |
| `year` | int64 | Year |
| `month` | int64 | Month (1–12) |
| `ref_month_yyyymm` | int64 | Period key, e.g. `201201` |
| `share_PH2M` | float64 | Probability-weighted share of Poor HtM households |
| `share_WH2M` | float64 | Probability-weighted share of Wealthy HtM households |
| `share_Ricardian` | float64 | Probability-weighted share of Ricardian households |
| `share_H2M` | float64 | Total HtM share (`share_PH2M + share_WH2M`) |
| `total_weight` | float64 | Sum of `weight_monthly` in the state-month cell |
| `n_obs` | int64 | Raw observation count |
| `n_unmatched` | int64 | Observations with no matching POF bin |

**Shape:** 4,536 rows (27 states × ~168 months)

---

### 3b. `results/tables/state_month_htm_shares_mc.parquet` — Monte Carlo diagnostic

Identical schema to **3a**. Shares are computed from deterministic Monte Carlo agent-type draws rather than probability weighting. Used to validate agreement with the expected-shares approach.

**Shape:** 4,536 rows

---

### 3c. `results/tables/state_quarter_htm_shares.csv` — Legacy quarterly aggregate

Written unless `--no-legacy-quarterly` is passed. Used by `cumulative_irf_heterogeneity.py` when the monthly parquet is absent.

| Column | Type | Description |
|---|---|---|
| `uf_code` | int | State IBGE code |
| `year` | int | Year |
| `quarter` | int | Quarter (1–4) |
| `share_PH2M` | float | Quarter-aggregated Poor HtM share |
| `share_WH2M` | float | Quarter-aggregated Wealthy HtM share |
| `share_Ricardian` | float | Quarter-aggregated Ricardian share |
| `share_H2M` | float | Total HtM share |
| `total_weight` | float | Sum of quarterly survey weights |
| `n_obs` | int | Observation count |
| `n_unmatched` | int | Unmatched observations |

---

### 3d. `results/tables/individual_agent_types.parquet` — Individual-level classifications

One row per PNADC individual with their demographic bin, bin probabilities, and deterministic agent-type assignment.

| Column | Type | Description |
|---|---|---|
| `id_ind` | string | Individual identifier |
| `id_dom` | int32 | Household identifier |
| `year` | int32 | Year |
| `quarter` | int32 | Quarter |
| `uf_code` | float | State IBGE code |
| `weight` | float | Survey expansion weight |
| `macro_region` | string | North / Northeast / Center-West / Southeast / South |
| `age_group` | string | 15–24 / 25–34 / 35–44 / 45–54 / 55–64 / 65+ |
| `gender` | string | male / female |
| `education_group` | string | no_education / primary / secondary / tertiary |
| `labor_status` | string | formal / informal / self_employed / unemployed / inactive |
| `pc_income_quintile` | string | Q1 / Q2 / Q3 / Q4 / Q5 |
| `p_ph2m` | float | Probability of Poor HtM from bin lookup |
| `p_wh2m` | float | Probability of Wealthy HtM from bin lookup |
| `p_ric` | float | Probability of Ricardian from bin lookup |
| `agent_type` | string | Deterministic MC assignment: PH2M / WH2M / Ricardian |
| `is_PH2M` | int8 | 1 if `agent_type == PH2M` |
| `is_WH2M` | int8 | 1 if `agent_type == WH2M` |
| `is_Ricardian` | int8 | 1 if `agent_type == Ricardian` |

**Shape:** 10,111,618 rows

---

## 4. Panel & Regression Inputs

### 4a. `results/tables/state_month_labour_market.parquet`

State × month labour market indicators. Built from PNADC by `scripts/data_prep/pnad.r`.

| Column | Type | Description |
|---|---|---|
| `UF` | int32 | State code (raw) |
| `ref_month_yyyymm` | float | Period key |
| `unemployment_rate` | float | State unemployment rate |
| `employed_weight.x` | float | Employed population weight (first source) |
| `unemployed_weight` | float | Unemployed population weight |
| `labour_force_participation_rate` | float | LFPR |
| `labour_force_weight` | float | Total labour force weight |
| `population` | float | State population |
| `formal_share` | float | Share of formal employment among employed |
| `informal_share` | float | Share of informal employment |
| `conta_propria_share` | float | Self-employed share |
| `employed_weight.y` | float | Employed population weight (second source) |
| `uf_code` | int32 | Normalised state code |
| `year` | int32 | Year |
| `month` | float | Month |

**Shape:** 4,563 rows

---

### 4b. `results/tables/state_month_income_ts.csv` — State-month income time series

| Column | Type | Description |
|---|---|---|
| `UF` | int | State code |
| `ref_month_yyyymm` | int | Period key |
| `mean_income` | float | Mean real income in state-month cell (BRL) |
| `n_obs` | int | Observation count |
| `total_weight` | float | Sum of survey weights |
| `uf_code` | int | Normalised state code |
| `year` | int | Year |
| `month` | int | Month |
| `mean_income_sa` | float | Seasonally adjusted income |
| `mean_income_trend` | float | HP-filtered trend component |

---

### 4c. `results/tables/national_income_ts.csv` — National income time series

| Column | Type | Description |
|---|---|---|
| `ref_month_yyyymm` | int | Period key |
| `mean_income` | float | National mean real income (BRL) |
| `n_obs` | int | Observation count |
| `total_weight` | float | Total population weight |
| `year` | int | Year |
| `month` | int | Month |
| `date` | date | Calendar date (YYYY-MM-DD) |
| `mean_income_sa` | float | Seasonally adjusted income |
| `mean_income_trend` | float | HP-filtered trend component |

---

### 4d. `results/diagnostics/shock_transformation_log.csv` — Monetary policy shocks

| Column | Type | Description |
|---|---|---|
| `raw_date` | date | Observation date |
| `year` | int | Year |
| `month` | int | Month |
| `quarter` | int | Quarter |
| `di_surprise` | float | Raw DI futures surprise (percentage points) |
| `mp_shock_monthly` | float | Transformed monetary-policy shock used in regressions; positive = contractionary |

---

## 5. POF Summary Tables

All POF summary tables share the same core columns. Variants differ in the classification rule or aggregation unit applied.

### Core columns (`results/tables/pof_group_wealth_income_summary*.csv`)

| Column | Type | Description |
|---|---|---|
| `agent_type` | string | PH2M / WH2M / Ricardian |
| `weighted_n` | float | Survey-weighted household count |
| `n_obs` | int | Unweighted observation count |
| `mean_monthly_income` | float | Mean monthly household income (BRL) |
| `mean_pc_income` | float | Mean per-capita income (BRL) |
| `mean_total_labor_income` | float | Mean total labour income (BRL) |
| `mean_total_transfers` | float | Mean transfer income (BRL) |
| `mean_pension_income` | float | Mean pension income (BRL) |
| `mean_govt_transfers` | float | Mean government transfer income (BRL) |
| `mean_financial_income` | float | Mean financial income (BRL) |
| `mean_other_labor_inc` | float | Mean other labour income (BRL) |
| `mean_liquid_assets` | float | Mean liquid asset holdings (BRL) |
| `mean_illiquid_assets` | float | Mean illiquid asset holdings (BRL) |
| `mean_liquid_ratio` | float | Liquid assets / monthly income |
| `mean_illiquid_ratio` | float | Illiquid assets / monthly income |

### Variants

| File | Additional column | Classification rule |
|---|---|---|
| `pof_group_wealth_income_summary.csv` | — | Baseline |
| `pof_group_wealth_income_summary_classical.csv` | — | Classical KVW thresholds |
| `pof_group_wealth_income_summary_poverty_split.csv` | — | Poverty-line split |
| `pof_group_wealth_income_summary_bin_units_compare.csv` | `classification` | Baseline vs. bin-unit comparison |
| `pof_group_wealth_income_summary_bin_units_dominant.csv` | `classification` | Dominant bin-unit assignment |
| `pof_group_wealth_income_summary_bin_units_expected.csv` | `classification` | Expected bin-unit assignment |

---

## 6. IRF / Regression Output Datasets

All IRF output tables share a common set of core columns. Wider tables add scenario or state identifiers.

### 6a. `results/tables/basic_state_month_lp/irf.csv` — Full IRF results

| Column | Type | Description |
|---|---|---|
| `response_type` | string | `marginal` or `cumulative` |
| `shock_variable` | string | e.g. `mp_shock` |
| `shock_type` | string | Narrative description of the shock |
| `shock_direction` | string | `contractionary_rate_surprise` / `expansionary_rate_surprise` |
| `shock_unit` | string | Units of the shock variable |
| `shock_multiplier` | float | Sign multiplier applied for shock direction |
| `shock_plot_label` | string | Human-readable label for plots |
| `spec` | string | Model specification tag (e.g. `lag1`) |
| `with_time_fe` | bool | Whether month fixed effects are included |
| `horizon` | int | LP horizon h (0, 1, 2, …) |
| `term` | string | Regression term name (e.g. `mp_shock`, `mp_shock:share_PH2M_lag1`) |
| `term_label` | string | Human-readable term label |
| `term_role` | string | `baseline_level_effect` / `differential_irf` / `aggregate_total_irf` |
| `household_exposure` | string | Which household type the estimate characterises |
| `baseline_household_type` | string | Omitted (reference) category |
| `term_note` | string | Technical interpretation note |
| `estimate` | float | Point estimate |
| `std_error` | float | Clustered standard error |
| `conf_low` | float | Lower 95% confidence bound |
| `conf_high` | float | Upper 95% confidence bound |
| `n_obs` | int | Observations used in regression |
| `n_states` | int | Number of states in the sample |
| `identified` | bool | Whether the term is identified in this specification |
| `note` | string | Additional estimation notes |
| `plot_share_delta` | float | Share delta used for scaled plotting |
| `plot_share_delta_pp` | float | Share delta in percentage points |
| `plot_estimate` | float | Estimate scaled to share delta |
| `plot_std_error` | float | SE scaled to share delta |
| `plot_conf_low` | float | Scaled lower CI |
| `plot_conf_high` | float | Scaled upper CI |
| `plot_effect_label` | string | Axis label for plots |

**Shape:** 2,352 rows

---

### 6b. `results/tables/basic_state_month_lp/aggregate_irf.csv`

Same 31 columns as **6a**. Contains only the aggregate response evaluated at the sample-mean household composition (linear combination of `mp_shock` plus interaction terms at mean lagged shares).

**Shape:** 392 rows

---

### 6c. `results/tables/basic_state_month_lp/state_irf.csv` — State-specific IRFs

All columns from **6a**, plus:

| Added column | Type | Description |
|---|---|---|
| `uf_code` | int | State IBGE code |
| `state_name` | string | State name |
| `macro_region` | string | North / Northeast / Center-West / Southeast / South |
| `avg_share_PH2M` | float | State time-mean PH2M share |
| `avg_share_WH2M` | float | State time-mean WH2M share |
| `avg_share_Ricardian` | float | State time-mean Ricardian share |
| `se_type` | string | Standard error type (`HC1`, `cluster_uf`) |

**Shape:** 5,292 rows

---

### 6d. `results/tables/basic_state_month_lp/lpirf_test_cumulative_irf.csv`

| Column | Type | Description |
|---|---|---|
| `horizon` | int | LP horizon h |
| `marginal_irf` | float | h-step marginal IRF estimate |
| `marginal_se` | float | Standard error |
| `marginal_low` | float | Lower 95% CI |
| `marginal_high` | float | Upper 95% CI |
| `cumulative_irf` | float | Sum of marginal IRFs through horizon h |
| `cumulative_se` | float | Cumulative standard error |
| `cumulative_low` | float | Lower 95% CI (cumulative) |
| `cumulative_high` | float | Upper 95% CI (cumulative) |

**Shape:** 48 rows

---

### 6e. `results/tables/lp_income/` and `results/tables/lp_wealth/` — Income and wealth LP outputs

Each file in these directories follows this schema:

| Column | Type | Description |
|---|---|---|
| `horizon` | int | LP horizon h |
| `term` | string | Regression term name |
| `estimate` | float | Point estimate |
| `ci_low` / `ci_high` | float | 95% confidence interval |
| `se` | float | Standard error |
| `shock_sd` | float | Standard deviation of the shock variable |
| `estimate_1sd` | float | Estimate scaled by 1 SD of shock |
| `ci_low_1sd` / `ci_high_1sd` | float | CI scaled by 1 SD of shock |
| `nobs` | int | Observations used |
| `se_method` | string | Standard error method |
| `response_type` | string | `marginal` or `cumulative` |
| `spec` | string | Model specification tag |
| `panel_effect` | string | *(income files only)* Fixed-effect type applied |

---

### 6f. `results/tables/irf_master_results.parquet` — Master IRF archive

Consolidated archive across all specifications and frequencies.

| Column | Type | Description |
|---|---|---|
| `level` | string | `state` or `national` |
| `frequency` | string | `quarterly` or `monthly` |
| `group` | string | e.g. `all_states` |
| `outcome` | string | Outcome variable (e.g. `consumption_index`) |
| `horizon` | int64 | LP horizon h |
| `n_obs` | int64 | Observations |
| `estimate` | float64 | Point estimate |
| `std_error` | float64 | Standard error |
| `ci_low` / `ci_high` | float64 | 95% confidence interval |
| `p_value` | float64 | p-value |
| `shock_sd` | float64 | Shock standard deviation |
| `irf_pos_1sd` / `irf_neg_1sd` | float64 | IRF for +1 / −1 SD shock |
| `ci_low_pos_1sd` / `ci_high_pos_1sd` | float64 | CI for +1 SD |
| `inference` | string | Inference method (e.g. `cluster_uf_fallback`) |
| `model_id` | string | Model identifier string |

**Shape:** 345 rows

---

## 7. Diagnostics

### 7a. `results/diagnostics/monthly_htm_coverage.csv`

One row per calendar month. Tracks observation counts, exclusions, and national-level shares.

| Column | Description |
|---|---|
| `ref_month_yyyymm` | Period key |
| `year`, `month` | Decomposed period |
| `n_obs` | Observations included in monthly aggregation |
| `n_unmatched` | Observations with no matching POF bin |
| `unmatched_share` | `n_unmatched / n_obs` |
| `total_weight` | Sum of `weight_monthly` for included rows |
| `national_share_PH2M` | National probability-weighted PH2M share |
| `national_share_WH2M` | National probability-weighted WH2M share |
| `national_share_Ricardian` | National probability-weighted Ricardian share |
| `national_share_H2M` | National total HtM share |
| `excluded_missing_weight` | Rows dropped for missing `weight_monthly` |
| `raw_rows_with_known_month` | Rows with a valid `ref_month_yyyymm` |
| `raw_rows_total` | Total rows in all batches |
| `included_rows_total` | Rows entering monthly aggregation |
| `missing_ref_month_total` | Rows excluded for missing month |
| `missing_weight_monthly_total` | Rows excluded for missing weight |
| `excluded_monthly_total` | Total exclusions (all reasons) |
| `under_15_or_missing_age_total` | Rows excluded by age < 15 filter |
| `missing_uf_total` | Rows excluded for missing state code |
| `unmatched_rows_total` | Rows with no matching POF bin |
| `n_batches` | Number of PyArrow batches processed |

---

### 7b. `results/diagnostics/merge_drops_state.csv`

Tracks row drops at each merge step in the state-level panel construction.

| Column | Description |
|---|---|
| `uf_code` | State IBGE code |
| `year`, `month`, `quarter` | Time identifiers |
| `_merge` | Merge indicator (`both`, `left_only`, `right_only`) |
| `step` | Pipeline step name where the drop occurred |

---

### 7c. `results/diagnostics/key_cardinality_checks.csv`

Validates merge key cardinality at each join.

| Column | Description |
|---|---|
| `name` | Dataset or join name |
| `left_rows` | Row count of left dataset before merge |
| `right_rows` | Row count of right dataset before merge |
| `merged_rows` | Row count after merge |
| `left_only` | Rows present only in the left dataset |
| `right_only` | Rows present only in the right dataset |
| `validate` | Merge validation assertion used (e.g. `1:1`, `m:1`) |

---

### 7d. `results/diagnostics/input_schema_audit.csv`

Automated schema check run at pipeline start.

| Column | Description |
|---|---|
| `dataset` | Dataset name |
| `exists` | Whether the file was found on disk |
| `n_cols` | Column count |
| `columns` | Serialised list of column names |

---

### 7e. `results/diagnostics/individual_gate_status.csv`

Gate check for individual-level consumption data files.

| Column | Description |
|---|---|
| `individual_file` | Path to individual-level input file |
| `has_consumption_column` | Boolean — whether a consumption column was found |
| `consumption_column` | Name of the consumption column found |
| `has_month_key` | Boolean — presence of a monthly period key |
| `has_quarter_key` | Boolean — presence of a quarterly period key |
| `has_state_key` | Boolean — presence of a state identifier |
| `has_type_key` | Boolean — presence of an agent-type column |
| `status` | `pass` / `fail` |

---

### 7f. `results/diagnostics/individual_income_merge.csv`

Summary of income merge completeness.

| Column | Description |
|---|---|
| `n_total` | Total rows in the individual dataset |
| `n_has_income` | Rows with a non-missing income value |
| `pct_missing` | Share of rows missing income |

---

## 8. Key Classification Parameters

| Parameter | Value | Role |
|---|---|---|
| `SELIC_RATE` | 9% | Annual rate used to compute the opportunity cost of illiquid assets |
| `LIQUID_THRESH` | 0.50 | Households with liquid assets < 0.5 × monthly income are classified as HtM |
| `ILLIQUID_MULT` | 3 | Wealthy HtM must hold illiquid assets ≥ 3 × monthly income |
| `POVERTY_LINE` | 170 BRL/month | Absolute poverty threshold separating Poor HtM from Wealthy HtM |
| `ALPHA_SMOOTH` | 0.1 | Dirichlet smoothing concentration parameter for sparse bins |
| `MIN_WEIGHTED_N` | 30 | Minimum weighted observations per bin before `small_bin_flag` is set |
| `RANDOM_SEED` | 42 | Seed for all deterministic Monte Carlo draws |

### Agent type decision rule

```
liquid_assets < LIQUID_THRESH × monthly_income
    AND pc_income < POVERTY_LINE         →  PH2M  (Poor Hand-to-Mouth)
    AND illiquid_assets ≥ ILLIQUID_MULT × monthly_income  →  WH2M  (Wealthy Hand-to-Mouth)
otherwise                                →  Ricardian
```

---

*Generated 2026-05-23. Re-run `python3 scripts/reporting/htm_classification.py` to refresh all outputs listed in sections 3–7.*
