#!/usr/bin/env Rscript
# Multi-shock version of celina_lp_lpirfs_benchmark.r
# Loops over 4 MP shock series; saves per-shock CSVs/PNGs + combined comparison outputs.
# Spec: contractionary only (shock_pos), TWFE + individual FE, Driscoll-Kraay SE.

suppressPackageStartupMessages({
  library(tidyverse)
  library(lpirfs)
})

set.seed(42)
cat("\n=== LPIRFS BENCHMARK MULTI-SHOCK ===\n\n")

MAX_HORIZON <- 48
LP_HOR <- MAX_HORIZON + 1
CI_LEVEL <- 90
CI_MULT <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)
SE_METHOD <- "driscoll_kraay"

OUT_TBL <- "results/tables/lp_controls/multishock"
OUT_PLT <- "results/plots/lp_controls/multishock"
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)

SHOCKS <- list(
  mp_shock_di = "DI Surprise",
  eps_rr      = "Recursive Residual",
  eps_sb      = "Sign-Based",
  eps_tvp     = "Time-Varying Param"
)

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(
    month_num       = month,
    lag1_share_ph2m = lag1_share_PH2M,
    lag1_share_wh2m = lag1_share_WH2M
  )

cat(sprintf("✓ Loaded: %d rows, %d states, years %d-%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code), min(d_raw$year), max(d_raw$year)))

missing_shocks <- setdiff(names(SHOCKS), names(d_raw))
if (length(missing_shocks) > 0) {
  stop(sprintf("Shock columns not found in dataset: %s", paste(missing_shocks, collapse = ", ")))
}

CTRL_BASE <- c(
  "lag1_share_ph2m", "lag1_share_wh2m", "log_imports", "log_exports",
  "infl_yoy", "log_bf", "log_credit_pf", "lag1_lc"
)

run_lpirfs <- function(data_set, shock_var, contemp_other, panel_effect) {
  lpirfs::lp_lin_panel(
    data_set      = data_set,
    endog_data    = "log_consumption",
    cumul_mult    = TRUE,
    shock         = shock_var,
    diff_shock    = FALSE,
    panel_model   = "within",
    panel_effect  = panel_effect,
    robust_cov    = "vcovSCC",
    robust_type   = "HC1",
    robust_maxlag = 6,
    c_exog_data   = contemp_other,
    l_exog_data   = CTRL_BASE,
    lags_exog_data = 1,
    confint       = CI_MULT,
    hor           = LP_HOR
  )
}

extract_series <- function(res_obj, label, panel_effect_label, shock_series_name, shock_sd) {
  irf_mean <- as.numeric(res_obj$irf_panel_mean[1, ])
  irf_low  <- as.numeric(res_obj$irf_panel_low[1, ])
  irf_up   <- as.numeric(res_obj$irf_panel_up[1, ])
  nobs_h   <- map_dbl(res_obj$reg_outputs,
                      ~ as.numeric(tryCatch(stats::nobs(.x), error = function(e) NA_real_)))

  tibble(
    horizon        = 0:MAX_HORIZON,
    term           = label,
    estimate       = irf_mean,
    ci_low         = irf_low,
    ci_high        = irf_up,
    se             = (ci_high - estimate) / CI_MULT,
    shock_sd       = shock_sd,
    estimate_1sd   = estimate * shock_sd,
    ci_low_1sd     = ci_low  * shock_sd,
    ci_high_1sd    = ci_high * shock_sd,
    nobs           = nobs_h,
    se_method      = SE_METHOD,
    shock_type     = "contractionary",
    response_type  = "cumulative",
    spec           = ifelse(panel_effect_label == "twoways", "lag1_tfe", "lag1_individual_fe"),
    panel_effect   = panel_effect_label,
    shock_series   = shock_series_name
  )
}

panel_effects <- c("twoways", "individual")
all_shock_results <- list()

for (shock_var in names(SHOCKS)) {
  shock_label <- SHOCKS[[shock_var]]
  cat(sprintf("\n── Shock: %s (%s) ──\n", shock_var, shock_label))

  panel <- d_raw |>
    arrange(uf_code, year, month_num) |>
    group_by(uf_code) |>
    mutate(
      log_consumption  = log(consumption_index),
      log_imports      = log(coalesce(vl_imports, 0) + 1),
      log_exports      = log(coalesce(vl_exports, 0) + 1),
      log_bf           = log(coalesce(total_value_BF_old, 0) + 1),
      infl_mom         = log(ipca_index) - log(lag(ipca_index, 1)),
      infl_yoy_raw     = log(ipca_index) - log(lag(ipca_index, 12)),
      infl_yoy         = coalesce(infl_yoy_raw, infl_mom * 12),
      lag1_lc          = lag(log_consumption),
      shock_pos        = pmax(.data[[shock_var]], 0),
      pos_x_ph2m       = shock_pos * lag1_share_ph2m,
      pos_x_wh2m       = shock_pos * lag1_share_wh2m,
      ym_id            = year * 100L + month_num
    ) |>
    ungroup()

  if (!"log_credit_pf" %in% names(panel)) stop("Expected column missing: log_credit_pf")

  term_ph2m <- paste0(shock_var, "_pos_x_ph2m")
  term_wh2m <- paste0(shock_var, "_pos_x_wh2m")

  panel <- panel |>
    rename(!!term_ph2m := pos_x_ph2m,
           !!term_wh2m := pos_x_wh2m)

  required_cols <- c("uf_code", "ym_id", "log_consumption",
                     term_ph2m, term_wh2m, CTRL_BASE)
  missing_cols <- setdiff(required_cols, names(panel))
  if (length(missing_cols) > 0) {
    stop(sprintf("Missing required columns for %s: %s",
                 shock_var, paste(missing_cols, collapse = ", ")))
  }

  bench_input <- panel |>
    filter(!if_any(all_of(required_cols), is.na)) |>
    select(uf_code, ym_id, log_consumption,
           all_of(c(term_ph2m, term_wh2m)), all_of(CTRL_BASE))

  cat(sprintf("  Prefiltered sample: %d rows\n", nrow(bench_input)))

  shock_sd <- c(
    stats::sd(bench_input[[term_ph2m]], na.rm = TRUE),
    stats::sd(bench_input[[term_wh2m]], na.rm = TRUE)
  )
  names(shock_sd) <- c(term_ph2m, term_wh2m)

  rows <- list()
  for (pe in panel_effects) {
    cat(sprintf("  → panel_effect=%s ...\n", pe))

    res_ph2m <- run_lpirfs(bench_input, term_ph2m, term_wh2m, pe)
    res_wh2m <- run_lpirfs(bench_input, term_wh2m, term_ph2m, pe)

    rows[[length(rows) + 1]] <- extract_series(res_ph2m, term_ph2m, pe, shock_label, shock_sd[[term_ph2m]])
    rows[[length(rows) + 1]] <- extract_series(res_wh2m, term_wh2m, pe, shock_label, shock_sd[[term_wh2m]])
  }

  shock_df <- bind_rows(rows)

  out_csv <- file.path(OUT_TBL, sprintf("irf_benchmark_%s_dk_dual_fe.csv", shock_var))
  write_csv(shock_df, out_csv)
  cat(sprintf("  ✓ Saved: %s\n", out_csv))

  plot_df <- shock_df |>
    mutate(
      term_label = recode(term,
        !!term_ph2m := "PH2M exposure x MP shock",
        !!term_wh2m := "WH2M exposure x MP shock"
      ),
      panel_effect_label = recode(panel_effect,
        twoways    = "Two-way FE",
        individual = "State FE"
      )
    )

  p <- ggplot(plot_df, aes(x = horizon, y = estimate_1sd, linetype = panel_effect_label)) +
    geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
                alpha = 0.14, color = NA, fill = "#1f77b4") +
    geom_line(linewidth = 0.9, color = "#1f77b4") +
    facet_wrap(~term_label, nrow = 1, scales = "free_y") +
    scale_linetype_manual(values = c("Two-way FE" = "solid", "State FE" = "22")) +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
    labs(
      title    = sprintf("Cumulative Contractionary LP IRFs — %s (%s)", shock_label, shock_var),
      subtitle = "Baseline y[t+h]-y[t]; 90% Driscoll-Kraay CI; 1-SD shock scaling",
      x        = "Horizon (months)",
      y        = "Cumulative log response (1-SD interaction shock)",
      linetype = "Panel effect"
    ) +
    theme_bw(base_size = 11) +
    theme(
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
      legend.position  = "bottom"
    )

  out_png <- file.path(OUT_PLT, sprintf("irf_benchmark_%s_dk_dual_fe.png", shock_var))
  ggsave(out_png, p, width = 10, height = 4.5, dpi = 300)
  cat(sprintf("  ✓ Saved plot: %s\n", out_png))

  all_shock_results[[shock_var]] <- shock_df
}

# ── Comparison: all shocks combined ────────────────────────────────────────────

combined_df <- bind_rows(all_shock_results)

out_csv_all <- file.path(OUT_TBL, "irf_benchmark_all_shocks_comparison.csv")
write_csv(combined_df, out_csv_all)
cat(sprintf("\n✓ Saved combined table: %s\n", out_csv_all))

SHOCK_COLORS <- c(
  "DI Surprise"       = "#1f77b4",
  "Recursive Residual"= "#d62728",
  "Sign-Based"        = "#2ca02c",
  "Time-Varying Param"= "#ff7f0e"
)

first_shock     <- names(SHOCKS)[1]
term_ph2m_first <- paste0(first_shock, "_pos_x_ph2m")
term_wh2m_first <- paste0(first_shock, "_pos_x_wh2m")

comparison_df <- combined_df |>
  filter(panel_effect == "twoways") |>
  mutate(
    term_label = case_when(
      grepl("_pos_x_ph2m$", term) ~ "PH2M exposure x MP shock",
      grepl("_pos_x_wh2m$", term) ~ "WH2M exposure x MP shock",
      TRUE ~ term
    )
  )

p_comp <- ggplot(comparison_df,
                 aes(x = horizon, y = estimate_1sd,
                     color = shock_series, fill = shock_series)) +
  geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
              alpha = 0.10, color = NA) +
  geom_line(linewidth = 0.8) +
  facet_wrap(~term_label, nrow = 1, scales = "free_y") +
  scale_color_manual(values = SHOCK_COLORS) +
  scale_fill_manual(values  = SHOCK_COLORS) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "Benchmark LP IRFs — All Shock Series Comparison (TWFE)",
    subtitle = "Contractionary only; Driscoll-Kraay 90% CI; 1-SD scaling",
    x        = "Horizon (months)",
    y        = "Cumulative log response (1-SD interaction shock)",
    color    = "Shock series", fill = "Shock series"
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
    legend.position  = "bottom"
  )

out_png_comp <- file.path(OUT_PLT, "irf_benchmark_all_shocks_comparison.png")
ggsave(out_png_comp, p_comp, width = 11, height = 5, dpi = 300)
cat(sprintf("✓ Saved comparison plot: %s\n", out_png_comp))

cat("\n=== LPIRFS BENCHMARK MULTI-SHOCK COMPLETE ===\n")
