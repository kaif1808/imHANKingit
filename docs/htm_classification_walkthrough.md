# `htm_classification.py` — Step-by-Step Walkthrough

This document explains `scripts/reporting/htm_classification.py` (2,095 lines) from top to bottom in plain language. The script is a two-stage pipeline: (1) classify Brazilian households from the POF 2017–18 expenditure survey into three agent types using the Kaplan–Violante–Weidner (KVW) framework and summarise those types into demographic bin shares; (2) stream the PNADC monthly matched labour-force panel, transfer the POF bin probabilities onto each PNADC respondent, and aggregate the result to state × month HtM shares.

---

## 1. Overview

**What it does in one paragraph.** The script reads raw fixed-width text files from the Brazilian Household Budget Survey (POF 2017–18) and classifies each household into one of three macroeconomic agent types: *Poor Hand-to-Mouth* (PH2M), *Wealthy Hand-to-Mouth* (WH2M), or *Ricardian*. Classification follows the KVW two-threshold rule — households with enough liquid wealth to buffer income shocks are Ricardian; those without liquid buffers but with substantial illiquid assets (housing, vehicles) are Wealthy HtM; everyone else is Poor HtM. Because the POF is cross-sectional and not longitudinal, the script then bridges to the PNADC panel: it builds demographic bins (region × age × gender × education × income quintile × labour status), computes Dirichlet-smoothed agent-type probabilities within each bin, and joins those probabilities onto every PNADC respondent via their demographic characteristics. Finally, it aggregates expected shares and a Monte Carlo diagnostic to state × month cells and writes canonical Parquet outputs.

**The three agent types**

| Type | Abbreviation | KVW description |
|------|-------------|-----------------|
| Poor Hand-to-Mouth | `PH2M` | Low liquid wealth, low illiquid wealth — lives hand-to-mouth with no buffer stock |
| Wealthy Hand-to-Mouth | `WH2M` | Low liquid wealth, high illiquid wealth — illiquid assets lock up savings |
| Ricardian | `Ricardian` | Adequate liquid wealth — can smooth consumption across income shocks |

---

## 2. Configuration constants (lines 38–119)

All thresholds and paths are module-level constants at the top of the file. Changing any of these produces a different classification without touching any function.

### Paths

| Constant | Value | Purpose |
|----------|-------|---------|
| `DATA_DIR` | `Data/Dados_20230713/` | Raw POF fixed-width text files |
| `DICT_FILE` | `Data/Documentacao_20230713/Dicionarios de variaveis.xls` | Column layout for all POF tables |
| `TABLES_DIR` | `results/tables/` | Output CSVs and Parquets |
| `DIAGNOSTICS_DIR` | `results/diagnostics/` | Coverage and validation CSVs |
| `PNAD_MATCHED_DEFAULT` | `pnadc_matched_with_periods.parquet` | Default PNADC input |

### Classification thresholds

| Constant | Default | Meaning |
|----------|---------|---------|
| `SELIC_RATE` | `0.09` (9%) | Annual risk-free rate used to capitalise financial income → liquid-asset proxy |
| `LIQUID_THRESH` | `0.50` | Monthly-income multiples of liquid assets; above this → Ricardian |
| `ILLIQUID_MULT` | `3` | Monthly-income multiples of illiquid assets; at/above this → WH2M |
| `POVERTY_LINE` | `170.0` BRL/month per capita | Poverty split for the parallel classifier |
| `ILLIQUID_RATIO_CAP` | `20.0` | Cap applied before classification to avoid outlier distortion |
| `LIQUID_RATIO_CAP` | `50.0` | Same, for liquid ratio |
| `H2M_NET_WORTH_SPLIT_QUANTILE` | `0.55` | Fallback net-worth quantile for the ordering-guard split |

### Smoothing and reproducibility

| Constant | Default | Meaning |
|----------|---------|---------|
| `ALPHA_SMOOTH` | `0.1` | Dirichlet prior concentration; pulls small-bin estimates toward national shares |
| `MIN_WEIGHTED_N` | `30` | Bins below this get a `small_bin_flag=1` in the output CSV |
| `RANDOM_SEED` | `42` | Seed for deterministic Monte Carlo draws |
| `DEFAULT_BATCH_SIZE` | `500_000` | Rows per pyarrow batch when streaming PNADC |

### Bin strategy enum (line 116)

```python
class BinStrategy(str, Enum):
    A = "A"   # 5-way labour status × relative quintile (POF cut-points)
    G = "G"   # 3-way labour status × absolute BRL income bands
    BOTH = "both"
```

Strategy **A** (default) produces finer quintile splits anchored to the POF income distribution, ensuring the same population percentile is compared across survey and panel. Strategy **G** uses hard BRL thresholds (`B1`–`B5`), which are more interpretable but insensitive to inflation or distributional shifts between surveys.

---

## 3. POF helper functions (lines 124–429)

Before the main pipeline functions, several small helpers handle reading and mapping.

### `read_pof_table` (line 146)

Reads one POF fixed-width text file. It first parses the Excel data dictionary to learn each variable's starting position and byte width, then calls `pd.read_fwf` with the exact column specs. All values are read as `str` and cast to numeric later. Sheet names passed here must match the tab name in `Dicionarios de variaveis.xls`.

### Geographic and demographic mappers (lines 165–212)

- **`uf_to_macroregion`** — maps the 2-digit UF code to one of Brazil's five macro-regions (North, Northeast, Southeast, South, Central-West) using `pd.cut` on numeric ranges.
- **`age_to_group`** — bins ages into 10-year cohorts (15–24, 25–34, …, 65+).
- **`pof_education_group`** — maps POF `NIVEL_INSTRUCAO` codes (1–7) to four groups: `no_education`, `primary`, `secondary`, `tertiary`. Code 1 = no schooling; 6–7 = university or above.
- **`pnadc_education_group`** — same mapping applied to PNADC's `VD3004` variable, which uses the same 1–7 scale.

### Labour-status derivation (line 215)

**`pof_labor_status`** operates on one POF household row and returns one of five labels: `formal`, `self_employed`, `informal`, `unemployed`, `inactive`. The logic:
1. If `total_labor_income > 0` → the household is employed. The sub-category is determined by `V5302` (formal employment indicator) and `V5303` (self-employment indicator).
2. If income is zero but age is 15–64 → `unemployed`.
3. Otherwise → `inactive`.

### Agent-type classifiers (lines 230–275)

Three classifiers operate on a household row that already has `liquid_ratio` and `illiquid_ratio` columns. They differ only in how they split the H2M population:

| Function | PH2M / WH2M split criterion |
|----------|----------------------------|
| `classify_agent` (line 230) | `illiquid_ratio ≥ ILLIQUID_MULT` |
| `classify_agent_poverty_split` (line 255) | `pc_income ≤ POVERTY_LINE` |
| `classify_agent_classical` (line 266) | `net_worth ≥ net_worth_cutoff` (passed as argument) |

All three first check `liquid_ratio > LIQUID_THRESH`; if true, the household is Ricardian regardless of illiquid wealth.

`_classify_with_exclusion` (line 239) wraps the baseline classifier with a pre-check: rows with non-positive income or NaN ratios return `"inactive_excluded"` rather than a type label and are removed before the bins are built.

### Dirichlet smoothing (line 278)

**`_smoothed_shares`** takes the raw weighted counts by type within a bin and blends them with `alpha × national_prior`:

```
p_ph2m = (weighted_ph2m + alpha * national_p_ph2m) / (total_weight + alpha)
```

With `ALPHA_SMOOTH = 0.1`, tiny bins receive 10% of their estimate from the national average and 90% from their own data; large bins are essentially unaffected.

---

## 4. Stage 1a — Build POF household frame (lines 432–592)

**`build_pof_household_frame`** reads five POF text files and merges them into one row per consumption unit (identified by `COD_UPA × NUM_DOM × NUM_UC`):

| File | Sheet | Key content used |
|------|-------|-----------------|
| `DOMICILIO.txt` | `Domicílio` | `UF`, `PESO_FINAL` (survey weight) |
| `MORADOR.txt` | `Morador` | Age (`V0403`), sex (`V0404`), education (`NIVEL_INSTRUCAO`), head flag (`V0306==1`), total declared income (`RENDA_TOTAL`) |
| `RENDIMENTO_TRABALHO.txt` | `Rendimento do Trabalho` | Monthly labour income (`V8500_DEFLA`), employment type (`V5302`, `V5303`) |
| `OUTROS_RENDIMENTOS.txt` | `Outros Rendimentos` | Transfers by type: pension (`QUADRO==55`), government (`QUADRO==56`), financial (`QUADRO==57`), other labour (`QUADRO==54`) |
| `ALUGUEL_ESTIMADO.txt` | `Aluguel Estimado` | Imputed rent (`V8000_DEFLA`), annualised as the illiquid real-estate proxy |
| `INVENTARIO.txt` (optional) | `Inventário` | Vehicle inventory for illiquid asset valuation |

**Head-of-household selection.** Rows where `V0306 == 1` identify the head. When a consumption unit has multiple candidates (which happens infrequently), the script takes the one with the lowest `COD_INFORMANTE` via `sort_values + drop_duplicates` — a deterministic tie-break that never drops data. The count of multi-head units is printed as a diagnostic.

**Income aggregation.** All income components are summed at the consumption-unit level:
- `total_labor_income` = sum of `V8500_DEFLA` from `RENDIMENTO_TRABALHO`
- `pension_income`, `govt_transfers`, `financial_income`, `other_labor_inc` from `OUTROS_RENDIMENTOS` by QUADRO code
- `total_transfers` = all rows in `OUTROS_RENDIMENTOS`
- `monthly_income` = `total_labor_income + total_transfers`
- `pc_income` = `monthly_income / max(hh_residents, 1)`

**Vehicle valuation** (when `USE_VEHICLE_VALUATION=True`). `_vehicle_value` (line 127) looks up item code `V9001` in `VEHICLE_BASE_VALUE_2018_BRL` (`"1403001"` = car at 30,000 BRL; `"1403101"` = motorcycle at 5,000 BRL), then depreciates at 8% per year from the acquisition year, flooring at 20% of base value. The per-unit value is multiplied by quantity `V9005` and aggregated to the household.

**Real estate proxy.** Estimated monthly rent (`V8000_DEFLA`) is multiplied by 12 to annualise, serving as a flow-based proxy for the stock of housing wealth (consistent with the KVW capitalisation approach).

The function raises a `ValueError` if duplicate household keys survive the merge, ensuring one row per unit is guaranteed.

---

## 5. Stage 1b — KVW classification and bin shares (lines 595–891)

**`build_pof_bin_shares`** calls `build_pof_household_frame`, computes wealth ratios, runs all three classifiers in parallel, constructs demographic bins, applies Dirichlet smoothing, and writes outputs.

### Wealth ratio construction (lines 621–634)

```
fin_liquid       = financial_income × 12 / SELIC_RATE   # capitalise annual financial income
pen_liquid       = pension_income × PENSION_MULT         # direct proxy (mult=1)
sav_liquid       = (RENDA_TOTAL - monthly_income×12).clip(0) × SAVINGS_FRAC
                                                          # income surplus as savings
# Government-transfer recipients get sav_liquid = 0 (line 628)
liquid_assets    = fin_liquid + pen_liquid + sav_liquid
illiquid_assets  = real_estate_annual + vehicle_value
liquid_ratio     = liquid_assets / monthly_income  [capped at LIQUID_RATIO_CAP]
illiquid_ratio   = illiquid_assets / monthly_income [capped at ILLIQUID_RATIO_CAP]
```

`SELIC_RATE` of 9% converts annual financial income to an implied stock of liquid wealth. `SAVINGS_FRAC = 0.5` conservatively attributes half of declared income surplus to liquid savings. Households receiving government transfers are assumed to have no discretionary savings (`sav_liquid = 0`).

### Exclusion logic (lines 635–692)

Rows with `monthly_income ≤ 0` or NaN ratios are labelled `"inactive_excluded"` by `_classify_with_exclusion`. These rows are removed from the classification but their count and composition (by age, sex, and reason) are written to `results/diagnostics/pof_zero_income_excluded.csv`.

### Three parallel classifiers (lines 704–710)

After exclusion, each retained household gets three type labels:

| Column | Classifier | Purpose |
|--------|-----------|---------|
| `agent_type` | `classify_agent` (baseline KVW) | Canonical output |
| `agent_type_poverty_split` | `classify_agent_poverty_split` | Robustness check |
| `agent_type_classical` | `classify_agent_classical` (median net-worth split) | Robustness check |

### Ordering guard (lines 721–733)

After the baseline classification, the script checks whether the weighted mean income of WH2M households exceeds that of PH2M households. If not (i.e., the classification is economically inverted), it replaces `agent_type` with the result of `classify_agent_classical` at the 55th percentile of H2M net worth (`H2M_NET_WORTH_SPLIT_QUANTILE`). This fallback is printed as a diagnostic message and recorded in the log.

### National shares (lines 748–758)

Weighted sums yield national probabilities (`pof_national`):

```python
pof_national = {"p_ph2m": ..., "p_wh2m": ..., "p_ric": ...}
```

These serve as the Dirichlet prior and as the national fallback probability for unmatched PNADC rows.

### Demographic bins (lines 801–890)

Six dimensions are mapped onto each POF household:

| Dimension | POF source | Values |
|-----------|-----------|--------|
| `macro_region` | `UF` | 5 Brazilian macro-regions |
| `age_group` | `age` (V0403) | 6 cohort bins |
| `gender` | `sex` (V0404) | `male`, `female`, `unknown` |
| `education_group` | `NIVEL_INSTRUCAO` | 4 levels |
| `pc_income_quintile` (strategy A) | `pc_income` | Q1–Q5 via `pd.qcut` on POF data |
| `income_band_absolute` (strategy G) | `pc_income` | B1–B5 via fixed BRL edges |
| `labor_status` (strategy A, 5-way) | derived | `formal`, `self_employed`, `informal`, `unemployed`, `inactive` |
| `labor_status_3way` (strategy G) | derived | `employed`, `unemployed`, `inactive` |

**`_build_bin_key`** (line 954) concatenates all six dimensions with `|` separators into a single string. Example: `"Southeast|35-44|male|secondary|Q3|formal"`.

**Dirichlet smoothing** is applied bin-by-bin via `_smoothed_shares`. The output `bin_shares` DataFrame has one row per unique bin key with columns `p_ph2m`, `p_wh2m`, `p_ric`, `weighted_n`, `raw_n`, `small_bin_flag`.

**Output:** `results/tables/pof_bin_shares.csv`

---

## 6. Stage 2 — PNADC batch preparation (lines 1146–1265)

**`prepare_pnadc_batch`** takes one pandas batch (a slice of the PNADC Parquet), applies the same six demographic mappings, left-joins onto `bin_shares`, fills unmatched rows with national fallback probabilities, renormalises if the three probabilities do not sum to 1, and performs a deterministic Monte Carlo draw.

### Row filtering (lines 1168–1195)

Four conditions must all be satisfied to keep a row:
1. `age ≥ 15` (working-age population)
2. `ref_month_yyyymm` is non-missing (parsed by `_parse_ref_month_yyyymm`)
3. `weight_monthly` is non-missing
4. `UF` (state code) is non-missing

Excluded rows are tallied in a `diagnostics` dict stored in `df.attrs["diagnostics"]`.

### Income quintile assignment (lines 1222–1229)

The canonical path (`per_quarter_quintiles=False`) calls `_income_quintiles_from_pof_edges` (line 920), which applies the POF-derived quintile cut-points to PNADC per-capita income. This ensures Q1–Q5 refer to the same absolute income thresholds in both surveys. The legacy path (`--per-quarter-quintiles`) instead ranks within each calendar quarter of the PNADC batch — less comparable across years but useful for checking seasonal robustness.

### Bin key and probability join (lines 1230–1258)

Each PNADC row gets a `bin_key` built by the same `_build_bin_key` function used on the POF data. A left-merge onto `bin_shares` attaches `p_ph2m`, `p_wh2m`, `p_ric`. Rows whose `bin_key` does not appear in `bin_shares` (unmatched bins) receive the national fallback. An `_unmatched_bin` flag marks these rows for diagnostic counting.

Probability renormalisation: if floating-point arithmetic causes `p_ph2m + p_wh2m + p_ric ≠ 1`, the row is rescaled by its sum.

### Deterministic Monte Carlo draw (lines 1084–1110)

**`_deterministic_agent_type`** assigns a discrete agent type to each PNADC respondent for the MC diagnostic. The draw is deterministic and household-stable:

1. The household ID (`id_rs` or `id_ind`) is hashed with `pd.util.hash_pandas_object`.
2. The hash is divided by 2^64 to produce a uniform U(0,1) draw `u`.
3. The type is `PH2M` if `u ≤ p_ph2m`, `WH2M` if `u ≤ p_ph2m + p_wh2m`, else `Ricardian`.

Because the draw depends only on the household ID (not batch position or row order), the same household always gets the same type across runs.

---

## 7. Stage 3 — Monthly aggregation (lines 1307–1380)

### Expected shares — `aggregate_monthly_expected` (line 1307)

For each row, compute `_w_ph2m = weight_monthly × p_ph2m` (and similarly for WH2M and Ricardian). Group by `(uf_code, year, month, ref_month_yyyymm)` and sum all four weighted columns plus the raw survey weight. Final shares:

```
share_PH2M = _w_ph2m / total_weight
share_H2M  = share_PH2M + share_WH2M
```

This is the **canonical output**: it reflects the expected (probability-weighted) fraction of each state's population in each type, marginalising over demographic-bin uncertainty.

### MC diagnostic — `aggregate_monthly_mc` (line 1333)

Identical groupby, but the weights are `weight_monthly × 1(agent_type == "PH2M")` etc. — i.e., each respondent contributes their full weight to exactly one type, the one drawn in Stage 2. This is a diagnostic: the MC and expected shares should be close if bin sizes are large; divergence signals thin bins or poor matching.

### Combining batches — `_combine_monthly_partials` (line 1359)

After all batches are processed, the partial DataFrames (one per batch) are concatenated and re-grouped by the same four monthly keys. The intermediate `_w_ph2m` columns allow exact re-aggregation: summing weighted numerators and denominators across batches is exact, while averaging shares would not be.

---

## 8. Writing outputs (lines 1738–1839)

### `_write_outputs` (line 1738)

Writes three files per strategy:

| Output file | Description |
|-------------|-------------|
| `results/tables/state_month_htm_shares.parquet` | Canonical expected shares — primary output used by downstream regressions |
| `results/tables/state_month_htm_shares_mc.parquet` | MC diagnostic shares |
| `results/diagnostics/monthly_htm_coverage.csv` | Per-month observation counts, unmatched rates, exclusion diagnostics, and national HtM trends |

### Legacy quarterly rollup — `aggregate_monthly_to_legacy_quarterly` (line 1686)

Re-aggregates the monthly expected output to state × quarter by summing the weighted numerators and denominators. This file (`state_quarter_htm_shares.csv`) is kept for backwards compatibility with older scripts. Suppressed with `--no-legacy-quarterly`.

### Annual trend — `write_temporal_trend_summary` (line 1548)

Collapses state × month shares to annual national shares by weighting each state-month cell by `total_weight`. Written to `results/diagnostics/national_htm_trend_yearly.csv`.

---

## 9. Validation summary (lines 1781–1805)

**`_print_validation_summary`** prints a three-row table to stdout at the end of each strategy run:

| Stage | PH2M | WH2M | Ricardian | Total |
|-------|------|------|-----------|-------|
| 1. POF Classification | ... | ... | ... | 1.00 |
| 3. PNADC monthly expected | ... | ... | ... | 1.00 |
| 4. PNADC monthly MC diagnostic | ... | ... | ... | 1.00 |

All three rows should be close. Systematic divergence between POF and PNADC expected means the demographic bins are not transferring well — usually caused by a mismatch in how labour status or education is coded across the two surveys.

---

## 10. Optional extras

### SELIC sensitivity — `write_selic_sensitivity` (line 1808)

Re-runs `build_pof_bin_shares` (with `write_outputs=False`) at SELIC rates of 6.5%, 9%, and 14%, temporarily overriding the global `SELIC_RATE`. Results — one row per rate, with national PH2M, WH2M, Ricardian shares — are written to `results/diagnostics/selic_sensitivity.csv`. Triggered by `--write-selic-sensitivity`.

### Choropleth maps — `generate_quarterly_choropleths` (line 1842)

Imports helpers from `generate_choropleths.py` (in the same directory) to download the IBGE state boundary shapefile and produce one map per quarter. Silently skipped if the download fails. Suppressed with `--no-choropleth`.

### COVID disruption exclusion (lines 1999–2009)

When `--exclude-covid-disruption` is passed, the script nulls out `share_PH2M`, `share_WH2M`, `share_Ricardian`, `share_H2M`, and `total_weight` for months 2020-04 through 2020-07 in both the expected and MC outputs. This prevents the April–July 2020 labour-market disruption (missing PNADC interviews, atypical employment patterns) from distorting IRF regression estimates.

---

## 11. CLI reference

Run from the repository root:

```bash
python3 scripts/reporting/htm_classification.py [OPTIONS]
```

| Flag | Default | Effect |
|------|---------|--------|
| `--pnad-parquet PATH` | `pnadc_matched_with_periods.parquet` | Override PNADC input file |
| `--batch-size N` | `500000` | Rows per pyarrow batch; reduce if RAM is limited |
| `--bin-strategy {A,G,both}` | `A` | Bin construction method (see §2) |
| `--canonical-strategy {A,G}` | `A` | When `--bin-strategy=both`, write this strategy to the canonical (unsuffixed) filenames |
| `--per-quarter-quintiles` | off | Legacy: assign quintiles within each calendar quarter instead of using POF cut-points |
| `--no-legacy-quarterly` | off | Skip writing `state_quarter_htm_shares.csv` |
| `--vehicle-valuation {fipe-proxy,off}` | `fipe-proxy` | Include or exclude vehicle inventory in illiquid assets |
| `--write-selic-sensitivity` | off | Run sensitivity analysis at three SELIC rates |
| `--exclude-covid-disruption` | off | Null out Apr–Jul 2020 in monthly outputs |
| `--no-choropleth` | off | Skip choropleth map generation |

**Common invocations**

```bash
# Full pipeline (canonical)
python3 scripts/reporting/htm_classification.py

# Custom PNADC file, skip choropleths
python3 scripts/reporting/htm_classification.py \
  --pnad-parquet /data/pnadc_v2.parquet \
  --no-choropleth

# Run both bin strategies, keep strategy A as canonical
python3 scripts/reporting/htm_classification.py \
  --bin-strategy both \
  --canonical-strategy A

# Sensitivity run
python3 scripts/reporting/htm_classification.py \
  --write-selic-sensitivity \
  --no-choropleth
```

---

## Pipeline at a glance

```
POF raw TXTs
    │
    ▼
build_pof_household_frame()          — one row per consumption unit
    │
    ▼
build_pof_bin_shares()               — KVW classification → demographic bins
    │                                  → pof_bin_shares.csv
    │  bin_shares, pof_quintile_edges, pof_national
    ▼
process_pnadc_parquet()              — stream PNADC in batches
    │   for each batch:
    │       prepare_pnadc_batch()    — filter + map demographics + join probs + MC draw
    │       aggregate_monthly_expected()
    │       aggregate_monthly_mc()
    │   _combine_monthly_partials()
    │
    ▼
_write_outputs()
    ├── state_month_htm_shares.parquet        (canonical)
    ├── state_month_htm_shares_mc.parquet     (diagnostic)
    ├── monthly_htm_coverage.csv
    └── state_quarter_htm_shares.csv          (legacy, optional)
```
