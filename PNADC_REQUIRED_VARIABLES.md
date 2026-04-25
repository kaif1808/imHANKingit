# PNAD-C Required Variable Inventory

This document lists all PNAD-C columns referenced by `htm_classification.py` for the PNAD-C stage of the pipeline.

## Variables used in both schema variants

These are referenced regardless of whether the file is in pretreated (DataZoom-like) or raw PNAD-C format.

| Variable | Required? | Where used |
|---|---|---|
| `UF` | Yes | Converted to `uf_code`, then mapped to macro-region bins and used for state-level aggregation. |
| `Ano` | Yes | Converted to `year`; also used in household-size grouping for pretreated data. |
| `Trimestre` | Yes | Converted to `quarter`; also used in household-size grouping for pretreated data and reporting. |

## Pretreated format (`test5.csv`, `test6.csv`, `test7.csv`)

Activated when `faixa_idade` exists and `V2009` does not.

### Required input columns

| Variable | Required? | Where used |
|---|---|---|
| `faixa_idade` | Yes | Converted to numeric age (`age`) for age filter and age-group binning. |
| `sexo` | Yes | Mapped to `sex_code` (`Homem`/`Mulher`) for gender binning. |
| `faixa_educ` | Yes | Converted to `vd3004` proxy for education-group binning. |
| `Habitual` | Yes | Used as survey weight (`weight`) for weighted shares and aggregation. |
| `rendimento_habitual_real` | Yes | Used as labor income proxy (`rendimento`) to compute per-capita income. |
| `ID_DOMICILIO` | Yes | Used with `Ano` and `Trimestre` to infer household size (`hh_size`) by count. |

### Conditionally used input columns (labor-status refinement)

These are not strictly mandatory in code (missing columns are skipped), but they materially affect labor-status classification and therefore bin matching quality.

| Variable | Required? | Where used |
|---|---|---|
| `formal` | Conditional | If present, `formal == 1` classifies worker as formal. |
| `conta_propria` | Conditional | If present, `conta_propria == 1` classifies worker as self-employed. |
| `informal` | Conditional | If present, helps classify worker as informal. |
| `ocupado` | Conditional | If present, `ocupado == 1` also triggers informal classification fallback. |
| `desocupado` | Conditional | If present, `desocupado == 1` classifies worker as unemployed. |
| `fora_forca_trab` | Conditional/read-only | Coerced if present, but not directly read in classifier logic; useful for upstream consistency. |

### Derived columns (not required in source file)

`year`, `quarter`, `uf_code`, `age`, `sex_code`, `vd3004`, `weight`, `rendimento`, `hh_size`, `pc_income_pnadc`, `macro_region`, `age_group`, `gender`, `education_group`, `labor_status`, `pc_income_quintile`, `bin_key`.

### Minimal pretreated input checklist

- `UF`
- `Ano`
- `Trimestre`
- `faixa_idade`
- `sexo`
- `faixa_educ`
- `Habitual`
- `rendimento_habitual_real`
- `ID_DOMICILIO`
- Recommended for labor quality: `formal`, `conta_propria`, `informal`, `ocupado`, `desocupado`, `fora_forca_trab`

## Raw PNAD-C panel format

Activated when `V2009` exists (or `faixa_idade` is absent).

### Required input columns

| Variable | Required? | Where used |
|---|---|---|
| `V2009` | Yes | Age (`age`) for age filter and age-group binning. |
| `V2007` | Yes | Sex code (`sex_code`) for gender binning. |
| `VD3004` | Yes | Education code (`vd3004`) for education-group binning. |
| `V1028` | Yes | Survey weight (`weight`) for weighted shares and aggregation. |
| `V2001` | Yes | Household size (`hh_size`) for per-capita income computation. |

### Optional but used if present

| Variable | Required? | Where used |
|---|---|---|
| `rendimento_habitual_real` | Optional | Read via `pnadc.get(...)`; if absent, defaults to `NaN` then 0. |

### Conditionally used input columns (labor-status refinement)

| Variable | Required? | Where used |
|---|---|---|
| `formal` | Conditional | If present, `formal == 1` classifies worker as formal. |
| `conta_propria` | Conditional | If present, `conta_propria == 1` classifies worker as self-employed. |
| `informal` | Conditional | If present, helps classify worker as informal. |
| `ocupado` | Conditional | If present, `ocupado == 1` also triggers informal classification fallback. |
| `desocupado` | Conditional | If present, `desocupado == 1` classifies worker as unemployed. |
| `fora_forca_trab` | Conditional/read-only | Coerced if present, but not directly read in classifier logic; useful for upstream consistency. |

### Derived columns (not required in source file)

`year`, `quarter`, `uf_code`, `age`, `sex_code`, `vd3004`, `weight`, `rendimento`, `hh_size`, `pc_income_pnadc`, `macro_region`, `age_group`, `gender`, `education_group`, `labor_status`, `pc_income_quintile`, `bin_key`.

### Minimal raw-format input checklist

- `UF`
- `Ano`
- `Trimestre`
- `V2009`
- `V2007`
- `VD3004`
- `V1028`
- `V2001`
- Optional: `rendimento_habitual_real`
- Recommended for labor quality: `formal`, `conta_propria`, `informal`, `ocupado`, `desocupado`, `fora_forca_trab`

## Notes on strictness

- The script will fail if required columns in each branch are missing.
- Labor-status columns are treated permissively in code, but missing them reduces labor-status granularity and! may worsen POF-to-PNAD-C bin alignment.
