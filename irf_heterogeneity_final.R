#!/usr/bin/env Rscript
# Final IRF Heterogeneity Analysis with Visualizations

library(tidyverse)
library(arrow)
library(lmtest)
library(sandwich)

set.seed(42)

dir.create("results/tables/irf_interaction", showWarnings = FALSE, recursive = TRUE)
dir.create("results/tables/irf_individual_income", showWarnings = FALSE, recursive = TRUE)
dir.create("results/plots/irf_interaction", showWarnings = FALSE, recursive = TRUE)
dir.create("results/plots/irf_individual_income", showWarnings = FALSE, recursive = TRUE)

cat("\n=== IRF HETEROGENEITY: FINAL ANALYSIS ===\n\n")

# Load data
base <- read_csv("results/tables/aggregate_state_monthly_shock_h2m.csv") |>
  filter(!is.na(mp_shock)) |>
  arrange(uf_code, year_month) |>
  group_by(uf_code) |>
  mutate(lag_log_c = lag(log(consumption_index + 1)), lag_mp_shock = lag(mp_shock)) |>
  ungroup()

ind_types <- read_parquet("results/tables/individual_agent_types.parquet")
pnad_raw <- read_parquet("PNAD-C-Treated/pnad_matched.parquet")

cat("✓ Data loaded\n")

# Helpers
safe_get <- function(ct, term) {
  idx <- grep(term, rownames(ct), fixed = FALSE)[1]
  if (is.na(idx)) return(data.frame(estimate = NA, se = NA, t_stat = NA, pval = NA))
  data.frame(estimate = ct[idx, 1], se = ct[idx, 2], t_stat = ct[idx, 3], pval = ct[idx, 4], row.names = NULL)
}

vcov_cluster <- function(model, cluster_var) sandwich::vcovCL(model, cluster = cluster_var, type = "HC1")

# ============================================================================
# APPROACH A: STATE-PANEL INTERACTION LP (h=0 to 12 months)
# ============================================================================

cat("\nApproach A: State-panel interaction LP\n")

run_lp_interaction <- function(h) {
  d <- base |>
    filter(!is.na(lag_log_c), !is.na(lag_mp_shock)) |>
    arrange(uf_code, year_month) |>
    group_by(uf_code) |>
    mutate(
      log_c = log(consumption_index + 1),
      y_lead = lead(log_c, h),
      y_resp = y_lead - lag_log_c,
      shock_x_ph2m = mp_shock * share_PH2M_linear,
      shock_x_wh2m = mp_shock * share_WH2M_linear
    ) |>
    ungroup() |>
    filter(!is.na(y_resp))

  fml <- y_resp ~ mp_shock + shock_x_ph2m + shock_x_wh2m +
                  share_PH2M_linear + share_WH2M_linear +
                  lag_log_c + lag_mp_shock +
                  factor(uf_code) + factor(month_num) + factor(year)

  m <- lm(fml, data = d)
  vcov_c <- vcov_cluster(m, d$uf_code)
  ct <- coeftest(m, vcov. = vcov_c)

  beta_mp <- safe_get(ct, "^mp_shock$")
  beta_mp_ph2m <- safe_get(ct, "shock_x_ph2m")
  beta_mp_wh2m <- safe_get(ct, "shock_x_wh2m")

  tibble(
    horizon = h,
    type = c("PH2M", "WH2M", "Ricardian"),
    irf = c(beta_mp$estimate + beta_mp_ph2m$estimate,
            beta_mp$estimate + beta_mp_wh2m$estimate,
            beta_mp$estimate),
    irf_se = c(sqrt(beta_mp$se^2 + beta_mp_ph2m$se^2),
               sqrt(beta_mp$se^2 + beta_mp_wh2m$se^2),
               beta_mp$se)
  )
}

results_a <- map_df(0:12, run_lp_interaction) |>
  mutate(irf_ci_lower = irf - 1.96 * irf_se, irf_ci_upper = irf + 1.96 * irf_se)

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

cat("✓ Approach A complete (h=0 to 12 months)\n")
print(results_a |> filter(horizon == 0) |> select(type, irf, irf_se))

# ============================================================================
# APPROACH B: INDIVIDUAL INCOME LP (h=0 to 8 quarters)
# ============================================================================

cat("\nApproach B: Individual income LP\n")

# Prepare individual data
pnad_income <- pnad_raw |>
  filter(!is.na(id_ind)) |>
  select(id_ind, Ano, Trimestre, rendimento_habitual_real) |>
  distinct()

ind_income <- ind_types |>
  select(id_ind, id_dom, year, quarter, uf_code, weight, agent_type) |>
  left_join(pnad_income, by = c("id_ind", "year" = "Ano", "quarter" = "Trimestre")) |>
  filter(!is.na(rendimento_habitual_real)) |>
  mutate(log_inc = log(rendimento_habitual_real + 1))

shock_qtr <- base |>
  mutate(quarter = ceiling(month_num / 3)) |>
  group_by(uf_code, year, quarter) |>
  summarise(mp_shock_qtr = mean(mp_shock, na.rm = TRUE), .groups = "drop")

ind_income <- ind_income |>
  left_join(shock_qtr, by = c("uf_code", "year", "quarter")) |>
  filter(!is.na(mp_shock_qtr))

cat("  Individual sample:", nrow(ind_income), "rows\n")

run_lp_individual <- function(h, type_filter) {
  d <- ind_income |>
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

  # Return NAs if no data
  if (nrow(d) == 0) {
    return(list(irf = NA, irf_se = NA, irf_pval = NA))
  }

  formula_parts <- c("y_resp ~ mp_shock_qtr + log_inc_lag + shock_lag")
  if (n_distinct(d$uf_code) > 1) formula_parts <- c(formula_parts, "+ factor(uf_code)")
  if (n_distinct(d$year) > 1) formula_parts <- c(formula_parts, "+ factor(year)")
  if (n_distinct(d$quarter) > 1) formula_parts <- c(formula_parts, "+ factor(quarter)")

  fml <- as.formula(paste(formula_parts, collapse = " "))

  tryCatch({
    m <- lm(fml, data = d, weights = d$weight)
    vcov_c <- vcov_cluster(m, d$uf_code)
    ct <- coeftest(m, vcov. = vcov_c)
    coef_shock <- safe_get(ct, "^mp_shock_qtr$")
    list(irf = coef_shock$estimate, irf_se = coef_shock$se, irf_pval = coef_shock$pval)
  }, error = function(e) {
    list(irf = NA, irf_se = NA, irf_pval = NA)
  })
}

results_b <- expand_grid(h = 0:8, type = c("PH2M", "WH2M", "Ricardian")) |>
  mutate(result = pmap(list(h, type), run_lp_individual)) |>
  unnest_wider(result) |>
  rename(horizon = h) |>
  mutate(irf_ci_lower = irf - 1.96 * irf_se, irf_ci_upper = irf + 1.96 * irf_se)

results_b_cir <- results_b |>
  group_by(type) |>
  arrange(horizon) |>
  mutate(
    cir = cumsum(irf),
    cir_se = sqrt(cumsum(irf_se^2)),
    cir_ci_lower = cir - 1.96 * cir_se,
    cir_ci_upper = cir + 1.96 * cir_se
  ) |>
  ungroup()

write_csv(results_b, "results/tables/irf_individual_income/irfs_by_type.csv")
write_csv(results_b_cir, "results/tables/irf_individual_income/irfs_cir_by_type.csv")

cat("✓ Approach B complete (h=0 to 8 quarters)\n")
print(results_b |> filter(horizon == 0) |> select(type, irf, irf_se))

# ============================================================================
# VISUALIZATIONS
# ============================================================================

cat("\nGenerating visualizations...\n")

# Approach A: IRFs
p_irfs_a <- results_a_cir |>
  ggplot(aes(x = horizon, y = irf, color = type, fill = type)) +
  geom_ribbon(aes(ymin = irf_ci_lower, ymax = irf_ci_upper), alpha = 0.2, color = NA) +
  geom_line(size = 1) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "gray50") +
  labs(title = "Approach A: Consumption IRF by Agent Type", x = "Horizon (months)", y = "IRF",
       color = "Type", fill = "Type") +
  theme_minimal() + theme(legend.position = "bottom")

ggsave("results/plots/irf_interaction/irfs.png", p_irfs_a, width = 10, height = 6, dpi = 300)

# Approach A: Cumulative IRFs
p_cir_a <- results_a_cir |>
  ggplot(aes(x = horizon, y = cir, color = type, fill = type)) +
  geom_ribbon(aes(ymin = cir_ci_lower, ymax = cir_ci_upper), alpha = 0.2, color = NA) +
  geom_line(size = 1) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "gray50") +
  labs(title = "Approach A: Cumulative Consumption IRF", x = "Horizon (months)", y = "CIR",
       color = "Type", fill = "Type") +
  theme_minimal() + theme(legend.position = "bottom")

ggsave("results/plots/irf_interaction/cumulative_irfs.png", p_cir_a, width = 10, height = 6, dpi = 300)

# Approach B: IRFs
p_irfs_b <- results_b_cir |>
  ggplot(aes(x = horizon, y = irf, color = type, fill = type)) +
  geom_ribbon(aes(ymin = irf_ci_lower, ymax = irf_ci_upper), alpha = 0.2, color = NA) +
  geom_line(size = 1) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "gray50") +
  labs(title = "Approach B: Income IRF by Agent Type", x = "Horizon (quarters)", y = "IRF",
       color = "Type", fill = "Type") +
  theme_minimal() + theme(legend.position = "bottom")

ggsave("results/plots/irf_individual_income/irfs.png", p_irfs_b, width = 10, height = 6, dpi = 300)

# Approach B: Cumulative IRFs
p_cir_b <- results_b_cir |>
  ggplot(aes(x = horizon, y = cir, color = type, fill = type)) +
  geom_ribbon(aes(ymin = cir_ci_lower, ymax = cir_ci_upper), alpha = 0.2, color = NA) +
  geom_line(size = 1) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "gray50") +
  labs(title = "Approach B: Cumulative Income IRF", x = "Horizon (quarters)", y = "CIR",
       color = "Type", fill = "Type") +
  theme_minimal() + theme(legend.position = "bottom")

ggsave("results/plots/irf_individual_income/cumulative_irfs.png", p_cir_b, width = 10, height = 6, dpi = 300)

cat("✓ Visualizations complete\n")

# ============================================================================
# MASTER RESULTS & SUMMARY
# ============================================================================

cat("\n=== SUMMARY ===\n\n")

# Cross-approach consistency
a_order <- results_a_cir |> filter(horizon == 0) |> arrange(desc(irf)) |> pull(type)
b_order <- results_b_cir |> filter(horizon == 0) |> arrange(desc(irf)) |> pull(type)

cat("Type ranking (h=0):\n")
cat("  Approach A (consumption):", paste(a_order, collapse=" > "), "\n")
cat("  Approach B (income):     ", paste(b_order, collapse=" > "), "\n")

if (identical(a_order, b_order)) {
  cat("  ✓ Directional consistency confirmed\n")
} else {
  cat("  ⚠ Type rankings differ\n")
}

cat("\nKey results saved to:\n")
cat("  - results/tables/irf_interaction/\n")
cat("  - results/tables/irf_individual_income/\n")
cat("  - results/plots/irf_interaction/\n")
cat("  - results/plots/irf_individual_income/\n")

cat("\n✓ Analysis complete\n")
