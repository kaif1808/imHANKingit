#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(tidyverse)
  library(lpirfs)
})

set.seed(42)
cat("\n=== LPIRFS INCOME HETEROGENEITY (direction dummy) ===\n\n")

MAX_HORIZON <- 48
LP_HOR <- MAX_HORIZON + 1
CI_LEVEL <- 90
CI_MULT <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)
SE_METHOD <- "driscoll_kraay"

OUT_TBL <- "results/tables/lp_income"
OUT_PLT <- "results/plots/lp_income"
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(
    month_num = month,
    lag1_share_ph2m = lag1_share_PH2M,
    lag1_share_wh2m = lag1_share_WH2M
  )

if (!"mp_shock" %in% names(d_raw)) {
  if ("mp_shock_di" %in% names(d_raw)) {
    d_raw <- d_raw |> mutate(mp_shock = mp_shock_di)
  } else {
    stop("Neither mp_shock nor mp_shock_di found in dataset")
  }
}

cat(sprintf("✓ Loaded: %d rows, %d states, years %d-%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code), min(d_raw$year), max(d_raw$year)))

panel <- d_raw |>
  arrange(uf_code, year, month_num) |>
  group_by(uf_code) |>
  mutate(
    log_income_sa = log(mean_income_sa),
    log_imports = log(coalesce(vl_imports, 0) + 1),
    log_exports = log(coalesce(vl_exports, 0) + 1),
    log_bf = log(coalesce(total_value_BF_old, 0) + 1),
    infl_mom = log(ipca_index) - log(lag(ipca_index, 1)),
    infl_yoy_raw = log(ipca_index) - log(lag(ipca_index, 12)),
    infl_yoy = coalesce(infl_yoy_raw, infl_mom * 12),
    lag1_li = lag(log_income_sa),
    mp_shock_pos = pmax(mp_shock, 0),
    mp_shock_neg_abs = abs(pmin(mp_shock, 0)),
    mp_shock_abs = abs(mp_shock),
    # Direction dummy: 1 if contractionary (positive DI shock), 0 otherwise.
    shock_dir_con = as.integer(mp_shock > 0),
    mp_abs_x_ph2m = mp_shock_abs * lag1_share_ph2m,
    mp_abs_x_wh2m = mp_shock_abs * lag1_share_wh2m,
    ym_id = year * 100L + month_num
  ) |>
  ungroup()

if (!"log_credit_pf" %in% names(panel)) {
  stop("Expected column missing: log_credit_pf")
}

CTRL_BASE <- c(
  "lag1_share_ph2m", "lag1_share_wh2m", "log_imports", "log_exports",
  "infl_yoy", "log_bf", "log_credit_pf", "lag1_li"
)

required_cols <- c(
  "uf_code", "ym_id", "log_income_sa", "shock_dir_con",
  "mp_abs_x_ph2m", "mp_abs_x_wh2m", CTRL_BASE
)
missing_cols <- setdiff(required_cols, names(panel))
if (length(missing_cols) > 0) {
  stop(sprintf("Missing required columns: %s", paste(missing_cols, collapse = ", ")))
}

base_panel <- panel |>
  filter(!if_any(all_of(required_cols), is.na))

bench_input <- base_panel |>
  select(
    uf_code,
    ym_id,
    log_income_sa,
    shock_dir_con,
    mp_abs_x_ph2m,
    mp_abs_x_wh2m,
    all_of(CTRL_BASE)
  )

cat(sprintf("✓ Prefiltered sample: %d rows\n", nrow(base_panel)))
cat(sprintf("  shock_dir_con==1 share: %.3f\n", mean(bench_input$shock_dir_con, na.rm = TRUE)))

run_nl_lpirfs <- function(data_set, shock_var, contemp_other, panel_effect, robust_cov, robust_type = NULL, robust_cluster = NULL, robust_maxlag = NULL) {
  lpirfs::lp_nl_panel(
    data_set = data_set,
    endog_data = "log_income_sa",
    cumul_mult = TRUE,
    shock = shock_var,
    diff_shock = FALSE,
    panel_model = "within",
    panel_effect = panel_effect,
    robust_cov = robust_cov,
    robust_type = robust_type,
    robust_cluster = robust_cluster,
    robust_maxlag = robust_maxlag,
    c_exog_data = contemp_other,
    l_exog_data = CTRL_BASE,
    lags_exog_data = 1,
    switching = "shock_dir_con",
    use_logistic = FALSE,
    lag_switching = FALSE,
    confint = CI_MULT,
    hor = LP_HOR
  )
}

extract_regime_series <- function(res_obj, label, se_type, panel_effect_label, shock_sd, regime) {
  if (regime == "expansionary") {
    irf_mean <- as.numeric(res_obj$irf_s1_mean[1, ])
    irf_low <- as.numeric(res_obj$irf_s1_low[1, ])
    irf_up <- as.numeric(res_obj$irf_s1_up[1, ])
  } else {
    irf_mean <- as.numeric(res_obj$irf_s2_mean[1, ])
    irf_low <- as.numeric(res_obj$irf_s2_low[1, ])
    irf_up <- as.numeric(res_obj$irf_s2_up[1, ])
  }

  nobs_h <- map_dbl(res_obj$xy_data_sets, nrow)

  if (!(length(irf_mean) == LP_HOR && length(nobs_h) == LP_HOR)) {
    stop(sprintf("Unexpected horizon length from lp_nl_panel for %s (%s)", label, regime))
  }

  tibble(
    horizon = 0:MAX_HORIZON,
    term = label,
    regime = regime,
    estimate = irf_mean,
    ci_low = irf_low,
    ci_high = irf_up,
    se = (ci_high - estimate) / CI_MULT,
    shock_sd = shock_sd,
    estimate_1sd = estimate * shock_sd,
    ci_low_1sd = ci_low * shock_sd,
    ci_high_1sd = ci_high * shock_sd,
    nobs = nobs_h,
    se_method = se_type,
    response_type = "cumulative",
    spec = ifelse(panel_effect_label == "twoways", "lag1_tfe_direction_dummy", "lag1_individual_fe_direction_dummy"),
    panel_effect = panel_effect_label
  )
}

shock_sd <- c(
  mp_abs_x_ph2m = stats::sd(bench_input$mp_abs_x_ph2m, na.rm = TRUE),
  mp_abs_x_wh2m = stats::sd(bench_input$mp_abs_x_wh2m, na.rm = TRUE)
)

panel_effects <- c("twoways", "individual")
rows <- list()

for (pe in panel_effects) {
  cat(sprintf("→ Running panel_effect=%s nonlinear benchmark...\n", pe))

  res_ph2m <- run_nl_lpirfs(
    data_set = bench_input,
    shock_var = "mp_abs_x_ph2m",
    contemp_other = "mp_abs_x_wh2m",
    panel_effect = pe,
    robust_cov = "vcovSCC",
    robust_type = "HC1",
    robust_maxlag = 6
  )

  res_wh2m <- run_nl_lpirfs(
    data_set = bench_input,
    shock_var = "mp_abs_x_wh2m",
    contemp_other = "mp_abs_x_ph2m",
    panel_effect = pe,
    robust_cov = "vcovSCC",
    robust_type = "HC1",
    robust_maxlag = 6
  )

  for (reg in c("expansionary", "contractionary")) {
    rows[[length(rows) + 1]] <- extract_regime_series(res_ph2m, "mp_abs_x_ph2m", SE_METHOD, pe, shock_sd[["mp_abs_x_ph2m"]], reg)
    rows[[length(rows) + 1]] <- extract_regime_series(res_wh2m, "mp_abs_x_wh2m", SE_METHOD, pe, shock_sd[["mp_abs_x_wh2m"]], reg)
  }
}

out_df <- bind_rows(rows)

# Add explicit contractionary-expansionary differential by term/FE/horizon.
out_diff <- out_df |>
  select(horizon, term, panel_effect, se_method, regime, estimate, ci_low, ci_high, estimate_1sd, ci_low_1sd, ci_high_1sd, nobs) |>
  pivot_wider(
    names_from = regime,
    values_from = c(estimate, ci_low, ci_high, estimate_1sd, ci_low_1sd, ci_high_1sd, nobs)
  ) |>
  transmute(
    horizon,
    term,
    panel_effect,
    se_method,
    regime = "con_minus_exp",
    estimate = estimate_contractionary - estimate_expansionary,
    ci_low = ci_low_contractionary - ci_high_expansionary,
    ci_high = ci_high_contractionary - ci_low_expansionary,
    estimate_1sd = estimate_1sd_contractionary - estimate_1sd_expansionary,
    ci_low_1sd = ci_low_1sd_contractionary - ci_high_1sd_expansionary,
    ci_high_1sd = ci_high_1sd_contractionary - ci_low_1sd_expansionary,
    nobs = pmin(nobs_contractionary, nobs_expansionary, na.rm = TRUE),
    shock_sd = NA_real_,
    response_type = "cumulative",
    spec = ifelse(panel_effect == "twoways", "lag1_tfe_direction_dummy", "lag1_individual_fe_direction_dummy")
  )

out_all <- bind_rows(out_df, out_diff)

out_csv <- file.path(OUT_TBL, "irf_income_direction_dummy_lpirfs_dk_only_dual_fe.csv")
write_csv(out_all, out_csv)
cat(sprintf("✓ Saved benchmark table: %s\n", out_csv))

plot_df <- out_all |>
  filter(regime %in% c("expansionary", "contractionary")) |>
  mutate(
    term_label = recode(
      term,
      mp_abs_x_ph2m = "PH2M exposure x |MP shock|",
      mp_abs_x_wh2m = "WH2M exposure x |MP shock|"
    ),
    panel_effect_label = recode(
      panel_effect,
      twoways = "Two-way FE",
      individual = "State FE"
    ),
    regime_label = recode(
      regime,
      expansionary = "Expansionary regime",
      contractionary = "Contractionary regime"
    )
  )

p <- ggplot(plot_df, aes(x = horizon, y = estimate_1sd, color = regime_label, fill = regime_label, linetype = panel_effect_label)) +
  geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.10, color = NA) +
  geom_line(linewidth = 0.9) +
  facet_wrap(~term_label, nrow = 1, scales = "free_y") +
  scale_color_manual(values = c("Expansionary regime" = "#1b9e77", "Contractionary regime" = "#d95f02")) +
  scale_fill_manual(values = c("Expansionary regime" = "#1b9e77", "Contractionary regime" = "#d95f02")) +
  scale_linetype_manual(values = c("Two-way FE" = "solid", "State FE" = "22")) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title = "Income LP IRFs with Shock-Direction Regimes (lpirfs nonlinear panel)",
    subtitle = sprintf(
      "Outcome: log(mean_income_sa); switching dummy = 1(contractionary), 0(expansionary); response to 1-SD shock (PH2M SD=%.4f, WH2M SD=%.4f); 90%% CI",
      shock_sd[["mp_abs_x_ph2m"]], shock_sd[["mp_abs_x_wh2m"]]
    ),
    x = "Horizon (months)",
    y = "Cumulative log income response (for 1-SD interaction shock)",
    color = "Regime",
    fill = "Regime",
    linetype = "Panel effect"
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
    legend.position = "bottom"
  )

out_png <- file.path(OUT_PLT, "irf_income_direction_dummy_lpirfs_dk_only_dual_fe.png")
ggsave(out_png, p, width = 10.5, height = 4.8, dpi = 300)
cat(sprintf("✓ Saved benchmark plot: %s\n", out_png))

check_h <- identical(sort(unique(out_all$horizon)), 0:MAX_HORIZON)
term_counts <- out_all |>
  filter(regime %in% c("expansionary", "contractionary")) |>
  count(se_method, term, panel_effect, regime) |>
  pull(n)
check_terms <- all(term_counts == (MAX_HORIZON + 1))
check_nobs <- out_all |>
  filter(regime %in% c("expansionary", "contractionary")) |>
  group_by(se_method, term, panel_effect, regime) |>
  summarise(non_increasing = all(diff(nobs) <= 0, na.rm = TRUE), .groups = "drop")

cat("\nVerification:\n")
cat(sprintf("  - horizons exactly 0:%d: %s\n", MAX_HORIZON, ifelse(check_h, "OK", "FAIL")))
cat(sprintf("  - full coefficient paths present (both regimes): %s\n", ifelse(check_terms, "OK", "FAIL")))
cat("  - nobs weakly non-increasing by series:\n")
print(check_nobs)

cat("\nNotes:\n")
cat("  - Direction heterogeneity uses lp_nl_panel switching dummy (shock_dir_con).\n")
cat("  - Regime mapping with use_logistic=FALSE and lag_switching=FALSE: state 1=expansionary, state 2=contractionary.\n")
cat("  - Also exported con_minus_exp differential rows in table for direct heterogeneity readout.\n")
cat("  - Single SE method used for clarity: Driscoll-Kraay.\n")

cat("\n=== LPIRFS INCOME HETEROGENEITY COMPLETE ===\n")
