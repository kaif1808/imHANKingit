#!/usr/bin/env Rscript
library(tidyverse)
library(arrow)
library(lmtest)
library(sandwich)

cat("Testing Approach B...\n")

# Load data
base <- read_csv("results/tables/aggregate_state_monthly_shock_h2m.csv") |>
  filter(!is.na(mp_shock))

ind_types <- read_parquet("results/tables/individual_agent_types.parquet")
pnad_raw <- read_parquet("PNAD-C-Treated/pnad_matched.parquet")

cat("Data loaded\n")

# Prepare individual income
pnad_income <- pnad_raw |>
  filter(!is.na(id_ind)) |>
  select(id_ind, Ano, Trimestre, rendimento_habitual_real) |>
  distinct()

ind_income <- ind_types |>
  select(id_ind, id_dom, year, quarter, uf_code, weight, agent_type) |>
  left_join(pnad_income, by = c("id_ind", "year" = "Ano", "quarter" = "Trimestre")) |>
  filter(!is.na(rendimento_habitual_real)) |>
  mutate(log_inc = log(rendimento_habitual_real + 1))

cat("Individual income prepared:", nrow(ind_income), "rows\n")

# Merge quarterly shocks
shock_qtr <- base |>
  mutate(quarter = ceiling(month_num / 3)) |>
  group_by(uf_code, year, quarter) |>
  summarise(mp_shock_qtr = mean(mp_shock, na.rm = TRUE), .groups = "drop")

ind_income <- ind_income |>
  left_join(shock_qtr, by = c("uf_code", "year", "quarter")) |>
  filter(!is.na(mp_shock_qtr))

cat("With shocks:", nrow(ind_income), "rows\n")

# Helper functions
safe_get <- function(ct, term) {
  idx <- grep(term, rownames(ct), fixed = FALSE)
  if (length(idx) == 0) {
    return(data.frame(estimate = NA, se = NA, t_stat = NA, pval = NA))
  }
  idx <- idx[1]
  data.frame(
    estimate = ct[idx, 1],
    se = ct[idx, 2],
    t_stat = ct[idx, 3],
    pval = ct[idx, 4],
    row.names = NULL
  )
}

vcov_cluster <- function(model, cluster_var) {
  sandwich::vcovCL(model, cluster = cluster_var, type = "HC1")
}

# Test for one type and horizon
cat("\nTesting Ricardian type, h=0...\n")

d <- ind_income |>
  filter(agent_type == "Ricardian") |>
  group_by(id_ind) |>
  arrange(year, quarter) |>
  mutate(
    log_inc_lag = lag(log_inc, 1),
    y_lead = lead(log_inc, 0),
    y_resp = y_lead - log_inc_lag,
    shock_lag = lag(mp_shock_qtr, 1)
  ) |>
  ungroup() |>
  filter(!is.na(y_resp), !is.na(log_inc_lag), !is.na(shock_lag))

cat("Sample size:", nrow(d), "\n")
cat("Unique individuals:", n_distinct(d$id_ind), "\n")
cat("States:", n_distinct(d$uf_code), "\n")
cat("Years:", n_distinct(d$year), "\n")
cat("Quarters:", n_distinct(d$quarter), "\n")

# Build formula
formula_parts <- c("y_resp ~ mp_shock_qtr + log_inc_lag + shock_lag")
if (n_distinct(d$uf_code) > 1) formula_parts <- c(formula_parts, "+ factor(uf_code)")
if (n_distinct(d$year) > 1) formula_parts <- c(formula_parts, "+ factor(year)")
if (n_distinct(d$quarter) > 1) formula_parts <- c(formula_parts, "+ factor(quarter)")

fml <- as.formula(paste(formula_parts, collapse = " "))
cat("Formula:", as.character(fml), "\n")

# Fit model
cat("Fitting model...\n")
m <- lm(fml, data = d, weights = d$weight)

cat("Model fitted. Getting VCV...\n")
vcov_c <- vcov_cluster(m, d$uf_code)

cat("Running coeftest...\n")
ct <- coeftest(m, vcov. = vcov_c)

cat("Getting shock coefficient...\n")
coef_shock <- safe_get(ct, "^mp_shock_qtr$")

cat("\nResult for Ricardian h=0:\n")
print(coef_shock)

cat("\n✓ Approach B test successful\n")
