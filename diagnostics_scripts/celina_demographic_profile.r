#!/usr/bin/env Rscript
# H2M Demographic Profile — POF 2017-18
#
# Characterises the demographic and economic profile of PH2M, WH2M, and
# Unconstrained households using POF 2017-18 microdata. Produces:
#   - Weighted summary statistics table (Section 2)
#   - State-level demographic heatmap (Section 3)
#   - Industry × formality stacked bar (Section 4)
#   - Transmission channel scorecard (Section 5)
#   - PH2M / WH2M share maps (Section 6)
#
# If data/pof/h2m_classified.csv does not exist, Section 0 generates it
# by replicating the KVW classification from htm_classification.py.
#
# Run from project root:
#   Rscript scripts/reporting/celina_demographic_profile.r

suppressPackageStartupMessages({
  library(tidyverse)
  library(readxl)
  library(survey)
})

cat("\n=== H2M DEMOGRAPHIC PROFILE ===\n\n")

# ── Paths and constants ────────────────────────────────────────────────────────
DATA_DIR  <- "Data/Dados_20230713"
DICT_FILE <- file.path("Data", "Documentacao_20230713", "Dicionarios de variaveis.xls")
H2M_FILE  <- "data/pof/h2m_classified.csv"
HTM_SHR   <- "results/tables/state_month_htm_shares.parquet"
OUT_TBL   <- "results/tables/demographics"
OUT_PLT   <- "results/plots/demographics"
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)

# KVW parameters — must match htm_classification.py
SELIC_RATE    <- 0.09
LIQUID_THRESH <- 0.50
ILLIQUID_MULT <- 3L
PENSION_MULT  <- 1
SAVINGS_FRAC  <- 0.50

CI_ALPHA <- 0.05

# ── POF fixed-width reader (mirrors Python read_pof_table) ────────────────────
read_pof_layout <- function(sheet) {
  read_excel(DICT_FILE, sheet = sheet, col_names = FALSE, skip = 1) |>
    select(1:3) |>
    setNames(c("start", "width", "var_name")) |>
    mutate(
      start    = as.integer(start),
      width    = as.integer(width),
      var_name = as.character(var_name)
    ) |>
    filter(!is.na(start), !is.na(width), !is.na(var_name), width > 0)
}

read_pof_table <- function(txt_file, sheet) {
  cat(sprintf("  %-42s", paste0("Reading ", txt_file, " ...")))
  layout <- read_pof_layout(sheet)
  tbl <- readr::read_fwf(
    file.path(DATA_DIR, txt_file),
    col_positions = readr::fwf_positions(
      start      = layout$start,
      end        = layout$start + layout$width - 1L,
      col_names  = layout$var_name
    ),
    col_types      = readr::cols(.default = readr::col_character()),
    show_col_types = FALSE,
    progress       = FALSE
  )
  cat(sprintf(" %d rows\n", nrow(tbl)))
  tbl
}

# ── Helper: UF code → macro-region ────────────────────────────────────────────
uf_to_region <- function(uf) {
  u <- as.integer(uf)
  case_when(
    u %in% c(11,12,13,14,15,16,17)       ~ "Norte",
    u %in% c(21,22,23,24,25,26,27,28,29) ~ "Nordeste",
    u %in% c(31,32,33,35)                ~ "Sudeste",
    u %in% c(41,42,43)                   ~ "Sul",
    u %in% c(50,51,52,53)                ~ "Centro-Oeste",
    TRUE                                  ~ NA_character_
  )
}

# ── Helper: NIVEL_INSTRUCAO → education ───────────────────────────────────────
nivel_to_yrs <- function(n) {
  case_when(n==1 ~ 2, n==2 ~ 4, n==3 ~ 8, n==4 ~ 10,
            n==5 ~ 11, n==6 ~ 14, n==7 ~ 16, TRUE ~ NA_real_)
}

nivel_to_group <- function(n) {
  case_when(
    n == 1          ~ "0-4 years",
    n %in% c(2, 3)  ~ "5-8 years",
    n %in% c(4, 5)  ~ "9-11 years",
    n %in% c(6, 7)  ~ "12+ years",
    TRUE             ~ NA_character_
  )
}

# ── Helper: industry code → label ─────────────────────────────────────────────
# Adjust the case_when ranges to match the actual dictionary coding.
# Typical POF 2017-18 V5310 uses 1-digit IBGE sector groups:
#   1 = Agriculture/livestock/forestry/fishing
#   2-5 = Mining / Manufacturing / Utilities
#   6 = Construction
#   7-9 = Trade / Transport / Accommodation
#   10-13 = Information / Finance / Real estate / Professional services
#   14-16 = Public administration / Education / Health
#   17-21 = Other personal services
map_industry <- function(code) {
  case_when(
    is.na(code)              ~ "Unknown",
    code == 1                ~ "Agriculture",
    code %in% c(2,3,4,5)    ~ "Manufacturing",
    code == 6                ~ "Construction",
    code %in% c(7,8,9,10,11,12,13) ~ "Services",
    code %in% c(14,15,16)   ~ "Public sector",
    TRUE                     ~ "Other"
  )
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 0: Generate h2m_classified.csv if missing
# ══════════════════════════════════════════════════════════════════════════════
if (!file.exists(H2M_FILE)) {
  cat("── Section 0: Generating h2m_classified.csv ──\n")
  dir.create(dirname(H2M_FILE), recursive = TRUE, showWarnings = FALSE)

  df_dom0 <- read_pof_table("DOMICILIO.txt", "Domicílio") |>
    mutate(across(c(COD_UPA, NUM_DOM, UF, PESO_FINAL), as.numeric)) |>
    select(COD_UPA, NUM_DOM, UF, PESO_FINAL)

  df_mor0 <- read_pof_table("MORADOR.txt", "Morador") |>
    mutate(across(c(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE,
                    V0403, V0404, NIVEL_INSTRUCAO, RENDA_TOTAL), as.numeric)) |>
    rename(age = V0403, sex = V0404) |>
    filter(!is.na(age), age >= 15)

  df_inc0 <- read_pof_table("RENDIMENTO_TRABALHO.txt", "Rendimento do Trabalho") |>
    mutate(across(c(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE, V8500_DEFLA), as.numeric)) |>
    group_by(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE) |>
    summarise(total_labor_income = sum(V8500_DEFLA, na.rm = TRUE), .groups = "drop")

  df_oth0 <- read_pof_table("OUTROS_RENDIMENTOS.txt", "Outros Rendimentos") |>
    mutate(across(c(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE,
                    QUADRO, V8500_DEFLA), as.numeric)) |>
    group_by(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE) |>
    summarise(
      pension_income   = sum(if_else(QUADRO == 55, V8500_DEFLA, 0), na.rm = TRUE),
      govt_transfers   = sum(if_else(QUADRO == 56, V8500_DEFLA, 0), na.rm = TRUE),
      financial_income = sum(if_else(QUADRO == 57, V8500_DEFLA, 0), na.rm = TRUE),
      .groups = "drop"
    )

  df_alug0 <- read_pof_table("ALUGUEL_ESTIMADO.txt", "Aluguel Estimado") |>
    mutate(across(c(COD_UPA, NUM_DOM, NUM_UC, V8000_DEFLA), as.numeric)) |>
    group_by(COD_UPA, NUM_DOM, NUM_UC) |>
    summarise(real_estate_annual = sum(V8000_DEFLA, na.rm = TRUE) * 12, .groups = "drop")

  pof_cl <- df_mor0 |>
    left_join(df_dom0,  by = c("COD_UPA", "NUM_DOM")) |>
    left_join(df_inc0,  by = c("COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE")) |>
    left_join(df_oth0,  by = c("COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE")) |>
    left_join(df_alug0, by = c("COD_UPA", "NUM_DOM", "NUM_UC")) |>
    mutate(
      across(c(total_labor_income, pension_income, govt_transfers,
               financial_income, real_estate_annual), ~coalesce(.x, 0)),
      monthly_income           = pmax(total_labor_income + govt_transfers + pension_income, 1),
      financial_income_annual  = financial_income * 12,
      fin_liquid               = financial_income_annual / SELIC_RATE,
      pen_liquid               = pension_income * PENSION_MULT,
      income_surplus           = pmax(coalesce(as.numeric(RENDA_TOTAL), 0) - monthly_income * 12, 0),
      sav_liquid               = if_else(govt_transfers > 0, 0, income_surplus * SAVINGS_FRAC),
      liquid_assets            = fin_liquid + pen_liquid + sav_liquid,
      illiquid_assets          = real_estate_annual,
      liquid_ratio             = liquid_assets   / monthly_income,
      illiquid_ratio           = illiquid_assets / monthly_income,
      h2m_type = case_when(
        liquid_ratio > LIQUID_THRESH    ~ "Unconstrained",
        illiquid_ratio >= ILLIQUID_MULT ~ "WH2M",
        TRUE                            ~ "PH2M"
      ),
      uf_code = as.integer(UF)
    )

  pof_cl |>
    select(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE, uf_code, h2m_type) |>
    write_csv(H2M_FILE)

  cat(sprintf("  ✓ %s written: %d persons | PH2M=%.1f%% | WH2M=%.1f%% | Unconstrained=%.1f%%\n\n",
              H2M_FILE, nrow(pof_cl),
              100 * mean(pof_cl$h2m_type == "PH2M"),
              100 * mean(pof_cl$h2m_type == "WH2M"),
              100 * mean(pof_cl$h2m_type == "Unconstrained")))
  rm(pof_cl, df_dom0, df_mor0, df_inc0, df_oth0, df_alug0); gc()
} else {
  cat(sprintf("── Section 0: %s found — skipping classification ──\n\n", H2M_FILE))
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Merge demographic variables
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 1: Merge demographic variables ──\n")

h2m <- read_csv(H2M_FILE, show_col_types = FALSE) |>
  mutate(h2m_type = case_when(
    h2m_type %in% c("ph2m", "PH2M") ~ "PH2M",
    h2m_type %in% c("wh2m", "WH2M") ~ "WH2M",
    TRUE                              ~ "Unconstrained"
  ))

# DOMICILIO: weight, state, urban/rural
df_dom <- read_pof_table("DOMICILIO.txt", "Domicílio") |>
  mutate(across(c(COD_UPA, NUM_DOM, UF, PESO_FINAL), as.numeric))

urban_var <- intersect(
  c("TIPO_SITUACAO_REG", "V0206", "V0207", "V0201"),
  names(df_dom)
)[1]
cat(sprintf("  Urban/rural variable detected: %s\n",
            if (is.na(urban_var)) "(none found — urban set to NA)" else urban_var))

df_dom <- df_dom |>
  mutate(
    urban  = if (!is.na(urban_var))
               as.integer(as.numeric(.data[[urban_var]]) == 1L)
             else NA_integer_,
    region = uf_to_region(UF)
  ) |>
  select(COD_UPA, NUM_DOM, UF, PESO_FINAL, urban, region)

# MORADOR: age, sex, education; household head via V0306
df_mor <- read_pof_table("MORADOR.txt", "Morador") |>
  mutate(across(c(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE,
                  V0403, V0404, NIVEL_INSTRUCAO, RENDA_TOTAL), as.numeric)) |>
  rename(age = V0403, sex = V0404)

if ("V0306" %in% names(df_mor)) {
  df_mor <- df_mor |> mutate(is_head = as.numeric(V0306) == 1)
} else {
  df_mor <- df_mor |> mutate(is_head = NA)
  cat("  Note: V0306 (household head) not found in MORADOR dictionary\n")
}

df_mor <- df_mor |>
  mutate(
    sex_cat    = case_when(sex == 1 ~ "Male", sex == 2 ~ "Female", TRUE ~ NA_character_),
    educ_yrs   = nivel_to_yrs(as.integer(NIVEL_INSTRUCAO)),
    educ_group = nivel_to_group(as.integer(NIVEL_INSTRUCAO))
  ) |>
  filter(!is.na(age), age >= 15) |>
  select(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE,
         age, sex_cat, educ_yrs, educ_group, RENDA_TOTAL, is_head)

# Household size
hh_size_tbl <- df_mor |>
  count(COD_UPA, NUM_DOM, NUM_UC, name = "hh_size")

# RENDIMENTO_TRABALHO: formal/informal + industry
df_inc <- read_pof_table("RENDIMENTO_TRABALHO.txt", "Rendimento do Trabalho") |>
  mutate(across(c(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE,
                  V5302, V5303, V8500_DEFLA), as.numeric))

ind_var <- intersect(c("V5310", "V5304", "V5306", "V5305"), names(df_inc))[1]
cat(sprintf("  Industry variable detected: %s\n",
            if (is.na(ind_var)) "(none — industry set to Unknown)" else ind_var))

df_inc_agg <- df_inc |>
  group_by(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE) |>
  summarise(
    total_labor_income = sum(V8500_DEFLA, na.rm = TRUE),
    ctps_formal        = first(V5302),   # 1=CTPS signed (formal), 2=no CTPS
    emp_type           = first(V5303),   # 1=employee, 2=self-employed, 3=employer
    industry_code      = if (!is.na(ind_var))
                           as.numeric(first(.data[[ind_var]]))
                         else NA_real_,
    .groups = "drop"
  ) |>
  mutate(
    employed = total_labor_income > 0,
    formal   = case_when(!employed ~ NA, ctps_formal == 1 ~ TRUE, TRUE ~ FALSE),
    industry = if_else(employed, map_industry(industry_code), "Not employed")
  ) |>
  select(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE,
         total_labor_income, formal, industry, employed)

# OUTROS_RENDIMENTOS: govt transfers + Bolsa Família
df_trans <- read_pof_table("OUTROS_RENDIMENTOS.txt", "Outros Rendimentos") |>
  mutate(across(c(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE,
                  QUADRO, V9001, V8500_DEFLA), as.numeric)) |>
  filter(QUADRO == 56) |>
  group_by(COD_UPA, NUM_DOM, NUM_UC, COD_INFORMANTE) |>
  summarise(
    govt_transfers = sum(V8500_DEFLA, na.rm = TRUE),
    # BF = V9001 code 1801; some dictionary versions use 18
    bolsa_familia  = any(V9001 %in% c(18, 1801), na.rm = TRUE),
    .groups = "drop"
  )

# ── Final merge ───────────────────────────────────────────────────────────────
pof_demo <- h2m |>
  left_join(df_mor,      by = c("COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE")) |>
  left_join(df_dom,      by = c("COD_UPA", "NUM_DOM")) |>
  left_join(hh_size_tbl, by = c("COD_UPA", "NUM_DOM", "NUM_UC")) |>
  left_join(df_inc_agg,  by = c("COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE")) |>
  left_join(df_trans,    by = c("COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE")) |>
  mutate(
    govt_transfers = coalesce(govt_transfers, 0),
    bolsa_familia  = coalesce(bolsa_familia, FALSE),
    total_income   = coalesce(total_labor_income, 0) + govt_transfers,
    pc_income      = if_else(!is.na(hh_size) & hh_size > 0,
                             total_income / hh_size, NA_real_),
    # Pre-compute all indicator columns needed for svyby (no update() needed)
    urban_n      = as.numeric(urban),
    formal_n     = as.numeric(coalesce(formal, FALSE)),
    bolsa_n      = as.numeric(bolsa_familia),
    illiq_n      = as.numeric(h2m_type == "WH2M"),   # by KVW definition
    credit_n     = as.numeric(coalesce(formal, FALSE)), # formal employment proxy
    reg_norte    = as.numeric(coalesce(region == "Norte",        FALSE)),
    reg_nordeste = as.numeric(coalesce(region == "Nordeste",     FALSE)),
    reg_centroeste = as.numeric(coalesce(region == "Centro-Oeste", FALSE)),
    reg_sudeste  = as.numeric(coalesce(region == "Sudeste",      FALSE)),
    reg_sul      = as.numeric(coalesce(region == "Sul",          FALSE)),
    h2m_type     = factor(h2m_type, levels = c("PH2M", "WH2M", "Unconstrained")),
    region       = factor(region,   levels = c("Norte", "Nordeste",
                                                "Centro-Oeste", "Sudeste", "Sul"))
  )

cat(sprintf("  Merged: %d persons | PH2M=%d | WH2M=%d | Unconstrained=%d | NA weight=%d\n\n",
            nrow(pof_demo),
            sum(pof_demo$h2m_type == "PH2M",          na.rm = TRUE),
            sum(pof_demo$h2m_type == "WH2M",          na.rm = TRUE),
            sum(pof_demo$h2m_type == "Unconstrained",  na.rm = TRUE),
            sum(is.na(pof_demo$PESO_FINAL))))

# Survey design (complex sample: UPA clusters, household weights)
svy <- svydesign(
  ids     = ~COD_UPA,
  weights = ~PESO_FINAL,
  data    = pof_demo |> filter(!is.na(PESO_FINAL)),
  nest    = TRUE
)

# ── Weighted statistics helpers ───────────────────────────────────────────────
# Point estimates: weighted.mean over pof_demo (simple, avoids svyby complexity)
wt_mean3 <- function(var) {
  pof_demo |>
    filter(!is.na(PESO_FINAL)) |>
    group_by(h2m_type) |>
    summarise(m = weighted.mean(.data[[var]], PESO_FINAL, na.rm = TRUE),
              .groups = "drop") |>
    pivot_wider(names_from = h2m_type, values_from = m)
}

# Weighted t-test PH2M vs WH2M (survey-design-correct SE)
wt_ttest_p <- function(formula_str) {
  f   <- as.formula(formula_str)
  sub <- subset(svy, h2m_type %in% c("PH2M", "WH2M"))
  tryCatch(svyttest(f, sub)$p.value, error = function(e) NA_real_)
}

# Weighted chi-squared (for categorical)
wt_chisq_p <- function(var, group_var = "h2m_type") {
  f   <- as.formula(sprintf("~%s + %s", var, group_var))
  sub <- subset(svy, h2m_type %in% c("PH2M", "WH2M"))
  tryCatch(svychisq(f, sub, statistic = "F")$p.value, error = function(e) NA_real_)
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Weighted summary statistics by H2M type
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 2: Weighted summary statistics ──\n")

# ── Continuous variables ──────────────────────────────────────────────────────
cont_specs <- list(
  list(var = "age",       label = "Age (years)",             ttest = "age ~ h2m_type"),
  list(var = "educ_yrs",  label = "Education (years)",       ttest = "educ_yrs ~ h2m_type"),
  list(var = "hh_size",   label = "Household size",          ttest = "hh_size ~ h2m_type"),
  list(var = "pc_income", label = "Income p.c. (R$/month)",  ttest = "pc_income ~ h2m_type")
)

cont_rows <- map_dfr(cont_specs, function(s) {
  bind_cols(
    tibble(variable = s$label, type = "continuous"),
    wt_mean3(s$var),
    tibble(p_ph2m_wh2m = wt_ttest_p(s$ttest))
  )
})

# ── Binary proportions ────────────────────────────────────────────────────────
bin_specs <- list(
  list(var = "urban_n",  label = "% Urban",
       ttest = "urban_n ~ h2m_type"),
  list(var = "formal_n", label = "% Formally employed",
       ttest = "formal_n ~ h2m_type"),
  list(var = "bolsa_n",  label = "% Receiving Bolsa Familia",
       ttest = "bolsa_n ~ h2m_type"),
  list(var = "illiq_n",  label = "% With positive illiquid wealth",
       ttest = "illiq_n ~ h2m_type")
)

bin_rows <- map_dfr(bin_specs, function(s) {
  bind_cols(
    tibble(variable = s$label, type = "proportion"),
    wt_mean3(s$var),
    tibble(p_ph2m_wh2m = wt_ttest_p(s$ttest))
  )
})

# ── Regional distribution ─────────────────────────────────────────────────────
reg_specs <- list(
  list(var = "reg_norte",     label = "% Norte",        ttest = "reg_norte ~ h2m_type"),
  list(var = "reg_nordeste",  label = "% Nordeste",     ttest = "reg_nordeste ~ h2m_type"),
  list(var = "reg_centroeste",label = "% Centro-Oeste", ttest = "reg_centroeste ~ h2m_type"),
  list(var = "reg_sudeste",   label = "% Sudeste",      ttest = "reg_sudeste ~ h2m_type"),
  list(var = "reg_sul",       label = "% Sul",          ttest = "reg_sul ~ h2m_type")
)

reg_rows <- map_dfr(reg_specs, function(s) {
  bind_cols(
    tibble(variable = s$label, type = "region"),
    wt_mean3(s$var),
    tibble(p_ph2m_wh2m = wt_ttest_p(s$ttest))
  )
})

# ── Industry distribution ─────────────────────────────────────────────────────
ind_levels <- c("Agriculture", "Manufacturing", "Construction",
                "Services", "Public sector", "Not employed")

pof_demo_sv <- pof_demo |>
  filter(!is.na(PESO_FINAL)) |>
  mutate(across(all_of(paste0("ind_", c("agr","mfg","con","svc","pub","ne"))),
                ~0L, .names = "{.col}"))  # initialise (overwritten below)

# Compute industry indicators in pof_demo once
pof_demo <- pof_demo |>
  mutate(
    ind_agr = as.numeric(coalesce(industry, "") == "Agriculture"),
    ind_mfg = as.numeric(coalesce(industry, "") == "Manufacturing"),
    ind_con = as.numeric(coalesce(industry, "") == "Construction"),
    ind_svc = as.numeric(coalesce(industry, "") == "Services"),
    ind_pub = as.numeric(coalesce(industry, "") == "Public sector"),
    ind_ne  = as.numeric(coalesce(industry, "") == "Not employed")
  )

# Rebuild survey with updated data
svy <- svydesign(
  ids     = ~COD_UPA,
  weights = ~PESO_FINAL,
  data    = pof_demo |> filter(!is.na(PESO_FINAL)),
  nest    = TRUE
)

ind_specs <- list(
  list(var = "ind_agr", label = "Industry: Agriculture",   ttest = "ind_agr ~ h2m_type"),
  list(var = "ind_mfg", label = "Industry: Manufacturing", ttest = "ind_mfg ~ h2m_type"),
  list(var = "ind_con", label = "Industry: Construction",  ttest = "ind_con ~ h2m_type"),
  list(var = "ind_svc", label = "Industry: Services",      ttest = "ind_svc ~ h2m_type"),
  list(var = "ind_pub", label = "Industry: Public sector", ttest = "ind_pub ~ h2m_type"),
  list(var = "ind_ne",  label = "Industry: Not employed",  ttest = "ind_ne ~ h2m_type")
)

ind_rows <- map_dfr(ind_specs, function(s) {
  bind_cols(
    tibble(variable = s$label, type = "industry"),
    wt_mean3(s$var),
    tibble(p_ph2m_wh2m = wt_ttest_p(s$ttest))
  )
})

# ── Combine and save ──────────────────────────────────────────────────────────
summary_tbl <- bind_rows(cont_rows, bin_rows, reg_rows, ind_rows) |>
  mutate(
    across(c(PH2M, WH2M, Unconstrained), ~round(.x, 4)),
    p_ph2m_wh2m = round(p_ph2m_wh2m, 4),
    sig_flag    = if_else(!is.na(p_ph2m_wh2m) & p_ph2m_wh2m < CI_ALPHA, "*", "")
  )

write_csv(summary_tbl, file.path(OUT_TBL, "h2m_demographic_profile.csv"))
cat("  ✓ h2m_demographic_profile.csv\n\n")

cat("  Summary (continuous + binary, * = sig at 5%):\n")
summary_tbl |>
  filter(type %in% c("continuous", "proportion")) |>
  transmute(variable,
            PH2M          = round(PH2M, 3),
            WH2M          = round(WH2M, 3),
            Unconstrained = round(Unconstrained, 3),
            p             = round(p_ph2m_wh2m, 3),
            sig           = sig_flag) |>
  print(n = Inf)
cat("\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: State-level demographic profiles + heatmap
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 3: State-level profiles and heatmap ──\n")

state_demo <- pof_demo |>
  filter(!is.na(PESO_FINAL), h2m_type %in% c("PH2M", "WH2M")) |>
  group_by(UF, h2m_type) |>
  summarise(
    mean_age       = weighted.mean(age,     PESO_FINAL, na.rm = TRUE),
    mean_educ      = weighted.mean(educ_yrs, PESO_FINAL, na.rm = TRUE),
    pct_informal   = 1 - weighted.mean(formal_n, PESO_FINAL, na.rm = TRUE),
    pct_bolsa      = weighted.mean(bolsa_n,  PESO_FINAL, na.rm = TRUE),
    .groups = "drop"
  ) |>
  mutate(uf_code = as.integer(UF))

write_csv(state_demo, file.path(OUT_TBL, "state_demo_by_type.csv"))
cat("  ✓ state_demo_by_type.csv\n")

# State-level H2M shares
if (file.exists(HTM_SHR) && requireNamespace("arrow", quietly = TRUE)) {
  state_shares <- arrow::read_parquet(HTM_SHR) |>
    group_by(uf_code) |>
    summarise(across(c(share_PH2M, share_WH2M), mean, na.rm = TRUE), .groups = "drop")
} else {
  state_shares <- pof_demo |>
    filter(!is.na(PESO_FINAL)) |>
    group_by(uf_code = as.integer(UF)) |>
    summarise(
      share_PH2M = weighted.mean(h2m_type == "PH2M", PESO_FINAL, na.rm = TRUE),
      share_WH2M = weighted.mean(h2m_type == "WH2M", PESO_FINAL, na.rm = TRUE),
      .groups = "drop"
    )
}

# Northeast share by state (all types)
ne_by_state <- pof_demo |>
  filter(!is.na(PESO_FINAL)) |>
  group_by(uf_code = as.integer(UF)) |>
  summarise(pct_northeast = weighted.mean(reg_nordeste, PESO_FINAL, na.rm = TRUE),
            .groups = "drop")

state_ph2m <- state_shares |>
  left_join(
    state_demo |>
      filter(h2m_type == "PH2M") |>
      select(uf_code, mean_age_ph2m = mean_age, mean_educ_ph2m = mean_educ,
             pct_informal_ph2m = pct_informal, pct_bolsa_ph2m = pct_bolsa),
    by = "uf_code"
  ) |>
  left_join(ne_by_state, by = "uf_code")

corr_specs <- list(
  list(var = "mean_age_ph2m",     label = "Mean age (PH2M)"),
  list(var = "mean_educ_ph2m",    label = "Mean educ yrs (PH2M)"),
  list(var = "pct_informal_ph2m", label = "Informality rate (PH2M)"),
  list(var = "pct_bolsa_ph2m",    label = "Bolsa Familia rate (PH2M)"),
  list(var = "pct_northeast",     label = "% Nordeste (all HH)")
)

corr_tbl <- map_dfr(corr_specs, function(s) {
  x  <- state_ph2m$share_PH2M
  y  <- state_ph2m[[s$var]]
  ok <- !is.na(x) & !is.na(y)
  if (sum(ok) < 5) return(NULL)
  ct <- cor.test(x[ok], y[ok])
  tibble(characteristic = s$label,
         corr    = round(ct$estimate, 3),
         p_value = round(ct$p.value, 3),
         sig     = ct$p.value < 0.10)
})

cat("\n  Correlation: state PH2M share vs demographic characteristics:\n")
print(corr_tbl, n = Inf)

p_heat <- corr_tbl |>
  mutate(
    sig_label    = sprintf("r = %.2f%s", corr, if_else(sig, "*", "")),
    characteristic = factor(characteristic, levels = rev(corr_tbl$characteristic))
  ) |>
  ggplot(aes(x = 0.5, y = characteristic, fill = corr, label = sig_label)) +
  geom_tile(colour = "white", linewidth = 0.6) +
  geom_text(size = 3.8, fontface = "bold") +
  scale_fill_gradient2(low = "#d62728", mid = "white", high = "#1f77b4",
                       midpoint = 0, limits = c(-1, 1), name = "r") +
  scale_x_continuous(breaks = NULL) +
  labs(
    title    = "Section 3: Correlation of State PH2M Share with Demographics",
    subtitle = "27 Brazilian states  ·  * = p < 0.10",
    x = NULL, y = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    axis.text.y   = element_text(size = 10),
    panel.border  = element_blank(), panel.grid = element_blank(),
    plot.title    = element_text(hjust = 0.5, size = 11),
    plot.subtitle = element_text(hjust = 0.5, size = 8.5, colour = "gray40"),
    legend.position = "right"
  )

ggsave(file.path(OUT_PLT, "s3_state_demographic_heatmap.png"),
       p_heat, width = 9, height = 5, dpi = 300)
cat("  ✓ s3_state_demographic_heatmap.png\n\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Industry × formality stacked bar
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 4: Industry × formality decomposition ──\n")

IND_ORDER <- c("Agriculture", "Manufacturing", "Construction",
               "Services", "Public sector", "Other", "Unknown", "Not employed")
IND_COLORS <- c(
  Agriculture    = "#4daf4a", Manufacturing = "#377eb8",
  Construction   = "#ff7f00", Services      = "#984ea3",
  `Public sector`= "#e41a1c", Other         = "gray60",
  Unknown        = "gray40",  `Not employed`= "gray80"
)

ind_formal_df <- pof_demo |>
  filter(!is.na(PESO_FINAL)) |>
  mutate(
    industry  = coalesce(industry, "Unknown"),
    formality = case_when(
      industry == "Not employed"    ~ "Not employed",
      coalesce(formal, FALSE)       ~ "Formal",
      TRUE                          ~ "Informal"
    ),
    industry  = factor(industry, levels = IND_ORDER)
  ) |>
  group_by(h2m_type, industry, formality) |>
  summarise(wt = sum(PESO_FINAL, na.rm = TRUE), .groups = "drop") |>
  group_by(h2m_type) |>
  mutate(share = wt / sum(wt)) |>
  ungroup() |>
  mutate(formality = factor(formality, levels = c("Formal", "Informal", "Not employed")))

p_ind <- ggplot(ind_formal_df,
                aes(x = h2m_type, y = share,
                    fill = industry, alpha = formality)) +
  geom_col(position = "stack", colour = "white", linewidth = 0.25) +
  scale_fill_manual(values = IND_COLORS, name = "Industry") +
  scale_alpha_manual(
    values = c(Formal = 1.0, Informal = 0.55, `Not employed` = 0.30),
    name   = "Employment status"
  ) +
  scale_y_continuous(labels = scales::percent_format(accuracy = 1)) +
  labs(
    title    = "Section 4: Industry Distribution by H2M Type",
    subtitle = "Solid = formal  ·  Semi-transparent = informal  ·  Light = not employed",
    x = "H2M type", y = "Share of persons"
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.major.x = element_blank(), panel.grid.minor = element_blank(),
    legend.position    = "right",
    plot.title         = element_text(hjust = 0.5, size = 11),
    plot.subtitle      = element_text(hjust = 0.5, size = 8.5, colour = "gray40")
  )

ggsave(file.path(OUT_PLT, "s4_industry_formality.png"),
       p_ind, width = 10, height = 6, dpi = 300)
cat("  ✓ s4_industry_formality.png\n\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Transmission channel scorecard
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 5: Transmission channel scorecard ──\n")

channel_specs <- list(
  list(var = "credit_n",  channel = "Credit channel",
       description = "% with formal employment (credit-access proxy)"),
  list(var = "formal_n",  channel = "Labour income channel",
       description = "% formally employed"),
  list(var = "illiq_n",   channel = "Asset price channel",
       description = "% with positive illiquid wealth (0% by def. for PH2M)"),
  list(var = "bolsa_n",   channel = "Fiscal transfer channel",
       description = "% receiving Bolsa Familia")
)

scorecard_long <- map_dfr(channel_specs, function(s) {
  wide <- wt_mean3(s$var)
  bind_cols(
    tibble(channel = s$channel, description = s$description),
    wide
  )
})

scorecard_wide <- scorecard_long |>
  mutate(across(c(PH2M, WH2M, Unconstrained),
                ~scales::percent(round(.x, 4), accuracy = 0.1)))

write_csv(scorecard_wide, file.path(OUT_TBL, "transmission_channel_exposure.csv"))
cat("  ✓ transmission_channel_exposure.csv\n\n")
cat("  Scorecard:\n")
print(scorecard_wide, n = Inf)
cat("\n")

# Heatmap version
p_score <- scorecard_long |>
  pivot_longer(c(PH2M, WH2M, Unconstrained),
               names_to = "h2m_type", values_to = "share") |>
  mutate(
    h2m_type = factor(h2m_type, levels = c("PH2M", "WH2M", "Unconstrained")),
    label    = scales::percent(share, accuracy = 0.1),
    channel  = factor(channel, levels = rev(channel_specs |>
                                              map_chr("channel")))
  ) |>
  ggplot(aes(x = h2m_type, y = channel, fill = share, label = label)) +
  geom_tile(colour = "white", linewidth = 0.8) +
  geom_text(size = 3.8, fontface = "bold") +
  scale_fill_gradient(low = "#fff7bc", high = "#d62728",
                      name  = "Share",
                      labels = scales::percent_format()) +
  labs(
    title    = "Section 5: Transmission Channel Exposure by H2M Type",
    subtitle = "Share of persons exposed to each monetary policy transmission channel",
    x = "H2M type", y = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.border  = element_blank(), panel.grid = element_blank(),
    axis.text.y   = element_text(size = 10),
    plot.title    = element_text(hjust = 0.5, size = 11),
    plot.subtitle = element_text(hjust = 0.5, size = 8.5, colour = "gray40")
  )

ggsave(file.path(OUT_PLT, "s5_transmission_scorecard.png"),
       p_score, width = 9, height = 4.5, dpi = 300)
cat("  ✓ s5_transmission_scorecard.png\n\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: State-level maps (PH2M and WH2M shares)
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 6: State-level H2M share maps ──\n")

if (!requireNamespace("geobr", quietly = TRUE)) {
  cat("  geobr not installed — skipping maps.\n")
  cat("  Install with: install.packages('geobr')\n\n")
} else {
  suppressPackageStartupMessages(library(geobr))

  states_sf <- tryCatch(
    geobr::read_state(year = 2018, showProgress = FALSE),
    error = function(e) {
      cat(sprintf("  geobr download failed (%s) — skipping maps\n\n",
                  conditionMessage(e)))
      NULL
    }
  )

  if (!is.null(states_sf)) {
    map_df <- states_sf |>
      left_join(state_shares |> rename(code_state = uf_code), by = "code_state")

    map_theme <- theme_void(base_size = 11) +
      theme(
        legend.position   = "bottom",
        legend.key.width  = unit(1.8, "cm"),
        legend.key.height = unit(0.4, "cm"),
        plot.title        = element_text(hjust = 0.5, size = 11),
        plot.subtitle     = element_text(hjust = 0.5, size = 8.5, colour = "gray40")
      )

    make_map <- function(fill_col, title_str, fill_label) {
      ggplot(map_df) +
        geom_sf(aes(fill = .data[[fill_col]]),
                colour = "white", linewidth = 0.3) +
        geom_sf_text(aes(label = abbrev_state), size = 2.4, colour = "gray15") +
        scale_fill_gradient(
          low = "#fff7bc", high = "#d62728",
          name = fill_label,
          labels = scales::percent_format(accuracy = 1),
          na.value = "gray85"
        ) +
        labs(title    = title_str,
             subtitle = "POF 2017-18 · KVW classification · Weighted household shares") +
        map_theme
    }

    p_ph2m_map <- make_map("share_PH2M", "PH2M (Poor H2M) Share", "PH2M share")
    p_wh2m_map <- make_map("share_WH2M", "WH2M (Wealthy H2M) Share", "WH2M share")

    if (requireNamespace("patchwork", quietly = TRUE)) {
      suppressPackageStartupMessages(library(patchwork))
      p_combined <- (p_ph2m_map | p_wh2m_map) +
        plot_annotation(
          title    = "Section 6: Geographic Distribution of H2M Types",
          subtitle = "Left: Poor H2M (PH2M)  ·  Right: Wealthy H2M (WH2M)",
          theme    = theme(
            plot.title    = element_text(hjust = 0.5, size = 12),
            plot.subtitle = element_text(hjust = 0.5, size = 9, colour = "gray40")
          )
        )
      ggsave(file.path(OUT_PLT, "s6_htm_maps.png"),
             p_combined, width = 14, height = 7, dpi = 300)
      cat("  ✓ s6_htm_maps.png (combined)\n\n")
    } else {
      ggsave(file.path(OUT_PLT, "s6_ph2m_map.png"),
             p_ph2m_map, width = 7, height = 7, dpi = 300)
      ggsave(file.path(OUT_PLT, "s6_wh2m_map.png"),
             p_wh2m_map, width = 7, height = 7, dpi = 300)
      cat("  ✓ s6_ph2m_map.png + s6_wh2m_map.png\n\n")
    }
  }
}

# ══════════════════════════════════════════════════════════════════════════════
cat("=== DEMOGRAPHIC PROFILE DONE ===\n\n")
cat(sprintf("Tables → %s/\n", OUT_TBL))
cat("  h2m_demographic_profile.csv\n")
cat("  state_demo_by_type.csv\n")
cat("  transmission_channel_exposure.csv\n")
cat(sprintf("\nPlots  → %s/\n", OUT_PLT))
cat("  s3_state_demographic_heatmap.png\n")
cat("  s4_industry_formality.png\n")
cat("  s5_transmission_scorecard.png\n")
cat("  s6_htm_maps.png\n\n")
cat("Notes:\n")
cat("  - Section 0 auto-generates h2m_classified.csv if missing.\n")
cat("  - Industry codes in map_industry() assume 1-digit IBGE sector groups;\n")
cat("    verify V5310 (or detected variable) against your data dictionary.\n")
cat("  - Bolsa Familia: QUADRO=56 & V9001 in {18, 1801}; adjust if needed.\n")
cat("  - Urban/rural: auto-detected from TIPO_SITUACAO_REG / V0206 / V0207 / V0201.\n")
cat("  - APC requires DESPESA_INDIVIDUAL.txt and is not included here.\n")
