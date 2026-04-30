#!/usr/bin/env Rscript
# IRF Heterogeneity Analysis: Both Approaches
# Approach A: State-panel interactions
# Approach B: Individual income LP

library(tidyverse)
library(arrow)
library(lmtest)
library(sandwich)

set.seed(42)

# Create output directories
dir.create("results/tables/irf_interaction", showWarnings = FALSE, recursive = TRUE)
dir.create("results/tables/irf_individual_income", showWarnings = FALSE, recursive = TRUE)
dir.create("results/plots/irf_interaction", showWarnings = FALSE, recursive = TRUE)
dir.create("results/plots/irf_individual_income", showWarnings = FALSE, recursive = TRUE)
dir.create("results/diagnostics", showWarnings = FALSE, recursive = TRUE)

cat("\n=== IRF HETEROGENEITY ANALYSIS ===\n")

# ============================================================================
# LOAD DATA
# ============================================================================

cat("\nLoading data...\n")

# State-month panel
base <- read_csv("results/tables/aggregate_state_monthly_shock_h2m.csv") |>
  filter(!is.na(mp_shock)) |>
  arrange(uf_code, year_month) |>
  group_by(uf_code) |>
  mutate(
    lag_log_c = lag(log(consumption_index + 1)),
    lag_mp_shock = lag(mp_shock)
  ) |>
  ungroup()

# State-quarter HTM shares
htm_shares <- read_csv("results/tables/state_quarter_htm_shares.csv") |>
  mutate(uf_code = as.integer(uf_code))

# Individual types
ind_types <- read_parquet("results/tables/individual_agent_types.parquet")

# PNADC
pnad_raw <- read_parquet("PNAD-C-Treated/pnad_matched.parquet")

cat("  State-month panel:", nrow(base), "rows\n")
cat("  Individual types:", nrow(ind_types), "rows\n")
cat("  PNADC:", nrow(pnad_raw), "rows\n")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

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

get_ci <- function(estimate, se, conf = 0.95) {
  z <- qnorm((1 + conf) / 2)
  list(lower = estimate - z * se, upper = estimate + z * se)
}

# ============================================================================
# APPROACH A: STATE-PANEL INTERACTION LP
# ============================================================================

cat("\n=== APPROACH A: STATE-PANEL INTERACTION LP ===\n")

run_lp_interaction <- function(h, variant = "linear") {
  cat("  h =", h, "...\n")

  d <- base |>
    filter(!is.na(lag_log_c), !is.na(lag_mp_shock)) |>
    arrange(uf_code, year_month) |>
    group_by(uf_code) |>
    mutate(
      log_c = log(consumption_index + 1),
      y_lead = lead(log_c, h),
      y_resp = y_lead - lag_log_c
    ) |>
    ungroup() |>
    filter(!is.na(y_resp))

  if (variant == "linear") {
    d <- d |>
      mutate(share_ph2m = share_PH2M_linear, share_wh2m = share_WH2M_linear)
  } else {
    d <- d |>
      mutate(share_ph2m = share_PH2M_nearest, share_wh2m = share_WH2M_nearest)
  }

  d <- d |>
    mutate(
      shock_x_ph2m = mp_shock * share_ph2m,
      shock_x_wh2m = mp_shock * share_wh2m
    )

  fml <- y_resp ~ mp_shock + shock_x_ph2m + shock_x_wh2m +
                  share_ph2m + share_wh2m +
                  lag_log_c + lag_mp_shock +
                  factor(uf_code) + factor(month_num) + factor(year)

  m <- lm(fml, data = d)
  vcov_c <- vcov_cluster(m, d$uf_code)
  ct <- coeftest(m, vcov. = vcov_c)

  beta_mp <- safe_get(ct, "^mp_shock$")
  beta_mp_ph2m <- safe_get(ct, "shock_x_ph2m")
  beta_mp_wh2m <- safe_get(ct, "shock_x_wh2m")

  irf_ph2m <- beta_mp$estimate + beta_mp_ph2m$estimate
  irf_wh2m <- beta_mp$estimate + beta_mp_wh2m$estimate
  irf_ric <- beta_mp$estimate

  se_ph2m <- sqrt(beta_mp$se^2 + beta_mp_ph2m$se^2)
  se_wh2m <- sqrt(beta_mp$se^2 + beta_mp_wh2m$se^2)
  se_ric <- beta_mp$se

  data.frame(
    horizon = h,
    type = c("PH2M", "WH2M", "Ricardian"),
    irf = c(irf_ph2m, irf_wh2m, irf_ric),
    irf_se = c(se_ph2m, se_wh2m, se_ric)
  )
}

results_a <- map_df(0:12, \(h) run_lp_interaction(h, variant = "linear"))

results_a <- results_a |>
  mutate(
    irf_ci_lower = irf - 1.96 * irf_se,
    irf_ci_upper = irf + 1.96 * irf_se
  )

results_a_cir <- results_a |>
  group_by(type) |>
  arrange(horizon) |>
  mutate(
    cir = cumsum(irf),
    cir_se = sqrt(cumsum(irf_se^2)),
    cir_ci_lower = cir - 1.96 * cir_se,
    cir_ci_upper = cir + 1.96 * cir_se
  ) |>
  ungroup()

write_csv(results_a, "results/tables/irf_interaction/implied_type_irfs_linear.csv")
write_csv(results_a_cir, "results/tables/irf_interaction/implied_type_irfs_cir_linear.csv")

cat("\nApproach A h=0 results:\n")
print(results_a |> filter(horizon == 0))

# ============================================================================
# APPROACH B: INDIVIDUAL INCOME LP
# ============================================================================

cat("\n=== APPROACH B: INDIVIDUAL INCOME LP ===\n")

# Prepare individual income panel
cat("Preparing individual income panel...\n")

pnad_income <- pnad_raw |>
  filter(!is.na(id_ind)) |>
  select(id_ind, Ano, Trimestre, rendimento_habitual_real) |>
  distinct()

ind_income <- ind_types |>
  select(id_ind, id_dom, year, quarter, uf_code, weight, agent_type) |>
  left_join(
    pnad_income,
    by = c("id_ind", "year" = "Ano", "quarter" = "Trimestre")
  )

merge_diag <- ind_income |>
  summarise(
    n_total = n(),
    n_has_income = sum(!is.na(rendimento_habitual_real)),
    pct_missing = 100 * mean(is.na(rendimento_habitual_real))
  )

write_csv(merge_diag, "results/diagnostics/individual_income_merge.csv")
cat("Income merge diagnostics:\n")
print(merge_diag)

ind_income <- ind_income |>
  filter(!is.na(rendimento_habitual_real)) |>
  mutate(log_inc = log(rendimento_habitual_real + 1))

# Merge quarterly shocks
cat("Merging quarterly shocks...\n")

shock_qtr <- base |>
  mutate(quarter = ceiling(month_num / 3)) |>
  group_by(uf_code, year, quarter) |>
  summarise(
    mp_shock_qtr = mean(mp_shock, na.rm = TRUE),
    .groups = "drop"
  )

ind_income <- ind_income |>
  left_join(shock_qtr, by = c("uf_code", "year", "quarter")) |>
  filter(!is.na(mp_shock_qtr))

cat("Individual income panel with shocks:", nrow(ind_income), "rows\n")

# Individual LP by type
cat("Running individual LP by type...\n")

run_lp_individual <- function(h, type_filter, data) {
  d <- data |>
    filter(agent_type == type_filter) |>
    group_by(id_ind) |>
    arrange(year, quarter) |>
    mutate(
      log_inc_lag = lag(log_inc, 1),
      y_lead = lead(log_inc, h),
      y_resp = y_lead - log_inc_lag,
      shock_lag = lag(mp_shock_qtr, 1)
    ) |>
    ungroup() |>
    filter(!is.na(y_resp), !is.na(log_inc_lag), !is.na(shock_lag))

  # Build formula dynamically based on factor levels
  formula_parts <- c("y_resp ~ mp_shock_qtr + log_inc_lag + shock_lag")
  if (n_distinct(d$uf_code) > 1) formula_parts <- c(formula_parts, "+ factor(uf_code)")
  if (n_distinct(d$year) > 1) formula_parts <- c(formula_parts, "+ factor(year)")
  if (n_distinct(d$quarter) > 1) formula_parts <- c(formula_parts, "+ factor(quarter)")

  fml <- as.formula(paste(formula_parts, collapse = " "))

  m <- lm(fml, data = d, weights = d$weight)
  vcov_c <- vcov_cluster(m, d$uf_code)
  ct <- coeftest(m, vcov. = vcov_c)

  coef_shock <- safe_get(ct, "^mp_shock_qtr$")

  list(
    irf = coef_shock$estimate,
    irf_se = coef_shock$se,
    irf_pval = coef_shock$pval,
    n_obs = nrow(d),
    n_unique_ind = n_distinct(d$id_ind),
    n_clusters = length(unique(d$uf_code))
  )
}

results_b_list <- expand_grid(h = 0:8, type = c("PH2M", "WH2M", "Ricardian")) |>
  mutate(
    result = pmap(list(h, type), function(hh, tt) run_lp_individual(hh, tt, ind_income))
  ) |>
  unnest_wider(result)

results_b <- results_b_list |>
  select(h, type, irf, irf_se, irf_pval) |>
  rename(horizon = h)

write_csv(results_b, "results/tables/irf_individual_income/irfs_by_type.csv")

cat("\nApproach B h=0 results:\n")
print(results_b |> filter(horizon == 0))

# Cumulative IRF for Approach B
results_b_cir <- results_b |>
  group_by(type) |>
  arrange(horizon) |>
  mutate(
    cir = cumsum(irf),
    cir_se = sqrt(cumsum(irf_se^2)),
    cir_ci_lower = cir - 1.96 * cir_se,
    cir_ci_upper = cir + 1.96 * cir_se,
    irf_ci_lower = irf - 1.96 * irf_se,
    irf_ci_upper = irf + 1.96 * irf_se
  ) |>
  ungroup()

write_csv(results_b_cir, "results/tables/irf_individual_income/irfs_cir_by_type.csv")

# ============================================================================
# MASTER RESULTS SYNTHESIS
# ============================================================================

cat("\n=== MASTER RESULTS SYNTHESIS ===\n")

master_a <- results_a_cir |>
  rename(
    impulse_estimate = irf,
    impulse_se = irf_se,
    impulse_ci_lower = irf_ci_lower,
    impulse_ci_upper = irf_ci_upper,
    cir_estimate = cir,
    cir_se = cir_se,
    cir_ci_lower = cir_ci_lower,
    cir_ci_upper = cir_ci_upper
  ) |>
  mutate(
    approach = "state_interaction",
    outcome = "consumption",
    frequency = "monthly",
    se_method = "clustered",
    n_obs = NA,
    n_clusters = NA,
    pvalue = NA
  ) |>
  select(approach, outcome, frequency, type, horizon,
         impulse_estimate, impulse_se, impulse_ci_lower, impulse_ci_upper, pvalue,
         cir_estimate, cir_se, cir_ci_lower, cir_ci_upper,
         n_obs, n_clusters, se_method)

master_b <- results_b_cir |>
  rename(
    impulse_estimate = irf,
    impulse_se = irf_se,
    impulse_ci_lower = irf_ci_lower,
    impulse_ci_upper = irf_ci_upper,
    cir_estimate = cir,
    cir_se = cir_se,
    cir_ci_lower = cir_ci_lower,
    cir_ci_upper = cir_ci_upper,
    pvalue = irf_pval
  ) |>
  mutate(
    approach = "individual_income",
    outcome = "income",
    frequency = "quarterly",
    se_method = "clustered",
    n_obs = NA,
    n_clusters = NA
  ) |>
  select(approach, outcome, frequency, type, horizon,
         impulse_estimate, impulse_se, impulse_ci_lower, impulse_ci_upper, pvalue,
         cir_estimate, cir_se, cir_ci_lower, cir_ci_upper,
         n_obs, n_clusters, se_method)

master_results <- bind_rows(master_a, master_b)

write_parquet(master_results, "results/tables/irf_master_results.parquet")

cat("\nMaster results table dimensions:", nrow(master_results), "rows\n")
cat("Approaches:", paste(unique(master_results$approach), collapse = ", "), "\n")

# ============================================================================
# SUMMARY & CROSS-APPROACH CONSISTENCY
# ============================================================================

cat("\n=== CROSS-APPROACH CONSISTENCY CHECK ===\n")

a_order <- results_a_cir |> filter(horizon == 0) |> arrange(desc(irf)) |> pull(type)
b_order <- results_b_cir |> filter(horizon == 0) |> arrange(desc(irf)) |> pull(type)

cat("Approach A type ranking (h=0):", paste(a_order, collapse=" > "), "\n")
cat("Approach B type ranking (h=0):", paste(b_order, collapse=" > "), "\n")

if (identical(a_order, b_order)) {
  cat("✓ Directional consistency confirmed\n")
} else {
  cat("⚠ Type rankings differ between approaches (directional consistency check)\n")
}

cat("\nApproach A consumption IRF at h=0:\n")
print(results_a_cir |> filter(horizon == 0) |> select(type, irf, irf_se))

cat("\nApproach B income IRF at h=0:\n")
print(results_b_cir |> filter(horizon == 0) |> select(type, irf, irf_se))

cat("\n✓ Analysis complete. Results saved to results/tables/ and results/diagnostics/\n")
