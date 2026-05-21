#!/usr/bin/env Rscript
# Multi-shock version of celina_lp_lpirfs_direction_dummy.r
# Loops over 4 MP shock series; saves per-shock CSVs/PNGs + combined comparison outputs.
# Spec: TWFE, 4 directional interaction terms per shock, Driscoll-Kraay SE.

suppressPackageStartupMessages({
  library(tidyverse)
  library(lpirfs)
})

set.seed(42)
cat("\n=== LPIRFS CONSUMPTION DIRECTIONAL DUMMIES MULTI-SHOCK ===\n\n")

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

SHOCK_COLORS <- c(
  "DI Surprise"        = "#1f77b4",
  "Recursive Residual" = "#d62728",
  "Sign-Based"         = "#2ca02c",
  "Time-Varying Param" = "#ff7f0e"
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

run_lpirfs <- function(data_set, shock_var, contemp_others) {
  lpirfs::lp_lin_panel(
    data_set       = data_set,
    endog_data     = "log_consumption",
    cumul_mult     = TRUE,
    shock          = shock_var,
    diff_shock     = FALSE,
    panel_model    = "within",
    panel_effect   = "twoways",
    robust_cov     = "vcovSCC",
    robust_type    = "HC1",
    robust_maxlag  = 6,
    c_exog_data    = contemp_others,
    l_exog_data    = CTRL_BASE,
    lags_exog_data = 1,
    confint        = CI_MULT,
    hor            = LP_HOR
  )
}

extract_series <- function(res_obj, term, shock_series_name, shock_sd) {
  irf_mean <- as.numeric(res_obj$irf_panel_mean[1, ])
  irf_low  <- as.numeric(res_obj$irf_panel_low[1, ])
  irf_up   <- as.numeric(res_obj$irf_panel_up[1, ])
  nobs_h   <- map_dbl(res_obj$reg_outputs,
                      ~ as.numeric(tryCatch(stats::nobs(.x), error = function(e) NA_real_)))

  if (!(length(irf_mean) == LP_HOR && length(nobs_h) == LP_HOR)) {
    stop(sprintf("Unexpected horizon length from lp_lin_panel for %s", term))
  }

  tibble(
    horizon       = 0:MAX_HORIZON,
    term          = term,
    estimate      = irf_mean,
    ci_low        = irf_low,
    ci_high       = irf_up,
    se            = (ci_high - estimate) / CI_MULT,
    shock_sd      = shock_sd,
    estimate_1sd  = estimate * shock_sd,
    ci_low_1sd    = ci_low   * shock_sd,
    ci_high_1sd   = ci_high  * shock_sd,
    nobs          = nobs_h,
    se_method     = SE_METHOD,
    response_type = "cumulative",
    spec          = "twfe_directional_dummies",
    shock_series  = shock_series_name
  )
}

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
      shock_neg_abs    = abs(pmin(.data[[shock_var]], 0)),
      pos_x_ph2m       = shock_pos     * lag1_share_ph2m,
      neg_x_ph2m       = shock_neg_abs * lag1_share_ph2m,
      pos_x_wh2m       = shock_pos     * lag1_share_wh2m,
      neg_x_wh2m       = shock_neg_abs * lag1_share_wh2m,
      ym_id            = year * 100L + month_num
    ) |>
    ungroup()

  if (!"log_credit_pf" %in% names(panel)) stop("Expected column missing: log_credit_pf")

  t_pos_ph2m <- paste0(shock_var, "_pos_x_ph2m")
  t_neg_ph2m <- paste0(shock_var, "_neg_x_ph2m")
  t_pos_wh2m <- paste0(shock_var, "_pos_x_wh2m")
  t_neg_wh2m <- paste0(shock_var, "_neg_x_wh2m")

  panel <- panel |>
    rename(!!t_pos_ph2m := pos_x_ph2m,
           !!t_neg_ph2m := neg_x_ph2m,
           !!t_pos_wh2m := pos_x_wh2m,
           !!t_neg_wh2m := neg_x_wh2m)

  shock_terms  <- c(t_pos_ph2m, t_neg_ph2m, t_pos_wh2m, t_neg_wh2m)
  required_cols <- c("uf_code", "ym_id", "log_consumption", shock_terms, CTRL_BASE)
  missing_cols  <- setdiff(required_cols, names(panel))
  if (length(missing_cols) > 0) {
    stop(sprintf("Missing required columns for %s: %s",
                 shock_var, paste(missing_cols, collapse = ", ")))
  }

  bench_input <- panel |>
    filter(!if_any(all_of(required_cols), is.na)) |>
    select(uf_code, ym_id, log_consumption,
           all_of(shock_terms), all_of(CTRL_BASE))

  cat(sprintf("  Prefiltered sample: %d rows\n", nrow(bench_input)))

  shock_sd <- sapply(shock_terms, function(v) stats::sd(bench_input[[v]], na.rm = TRUE))

  rows <- list()
  for (term in shock_terms) {
    cat(sprintf("  → Running TWFE LP for %s ...\n", term))
    others <- setdiff(shock_terms, term)
    res    <- run_lpirfs(bench_input, term, others)
    rows[[length(rows) + 1]] <- extract_series(res, term, shock_label, shock_sd[[term]])
  }

  shock_df <- bind_rows(rows)

  out_csv <- file.path(OUT_TBL, sprintf("irf_consumption_directional_%s_twfe_dk.csv", shock_var))
  write_csv(shock_df, out_csv)
  cat(sprintf("  ✓ Saved: %s\n", out_csv))

  plot_df <- shock_df |>
    mutate(
      panel_label = case_when(
        grepl("_pos_x_ph2m$", term) ~ "PH2M x Contractionary shock",
        grepl("_neg_x_ph2m$", term) ~ "PH2M x Expansionary shock",
        grepl("_pos_x_wh2m$", term) ~ "WH2M x Contractionary shock",
        grepl("_neg_x_wh2m$", term) ~ "WH2M x Expansionary shock"
      )
    )

  p <- ggplot(plot_df, aes(x = horizon, y = estimate_1sd)) +
    geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
                alpha = 0.16, color = NA, fill = "#1f77b4") +
    geom_line(linewidth = 0.9, color = "#1f77b4") +
    facet_wrap(~panel_label, nrow = 2, ncol = 2, scales = "free_y") +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
    labs(
      title    = sprintf("Consumption LP IRFs — Directional Dummies — %s (%s)", shock_label, shock_var),
      subtitle = "Outcome: log(consumption_index); TWFE; Driscoll-Kraay 90% CI; 1-SD scaling",
      x        = "Horizon (months)",
      y        = "Cumulative log consumption response (1-SD directional interaction shock)"
    ) +
    theme_bw(base_size = 11) +
    theme(
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
      legend.position  = "none"
    )

  out_png <- file.path(OUT_PLT, sprintf("irf_consumption_directional_%s_4panel.png", shock_var))
  ggsave(out_png, p, width = 11, height = 8.5, dpi = 300)
  cat(sprintf("  ✓ Saved plot: %s\n", out_png))

  all_shock_results[[shock_var]] <- shock_df
}

# ── Comparison: all shocks combined ────────────────────────────────────────────

combined_df <- bind_rows(all_shock_results)

out_csv_all <- file.path(OUT_TBL, "irf_consumption_directional_all_shocks.csv")
write_csv(combined_df, out_csv_all)
cat(sprintf("\n✓ Saved combined table: %s\n", out_csv_all))

comparison_df <- combined_df |>
  mutate(
    panel_label = case_when(
      grepl("_pos_x_ph2m$", term) ~ "PH2M x Contractionary shock",
      grepl("_neg_x_ph2m$", term) ~ "PH2M x Expansionary shock",
      grepl("_pos_x_wh2m$", term) ~ "WH2M x Contractionary shock",
      grepl("_neg_x_wh2m$", term) ~ "WH2M x Expansionary shock"
    )
  )

p_comp <- ggplot(comparison_df,
                 aes(x = horizon, y = estimate_1sd,
                     color = shock_series, fill = shock_series)) +
  geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
              alpha = 0.08, color = NA) +
  geom_line(linewidth = 0.75) +
  facet_wrap(~panel_label, nrow = 2, ncol = 2, scales = "free_y") +
  scale_color_manual(values = SHOCK_COLORS) +
  scale_fill_manual(values  = SHOCK_COLORS) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "Consumption LP IRFs — Directional Dummies — All Shock Series (TWFE)",
    subtitle = "Driscoll-Kraay 90% CI; 1-SD scaling; 4 shock series overlaid",
    x        = "Horizon (months)",
    y        = "Cumulative log consumption response (1-SD directional interaction shock)",
    color    = "Shock series", fill = "Shock series"
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
    legend.position  = "bottom"
  )

out_png_comp <- file.path(OUT_PLT, "irf_consumption_directional_all_shocks_comparison.png")
ggsave(out_png_comp, p_comp, width = 11, height = 9, dpi = 300)
cat(sprintf("✓ Saved comparison plot: %s\n", out_png_comp))

cat("\n=== LPIRFS CONSUMPTION DIRECTIONAL DUMMIES MULTI-SHOCK COMPLETE ===\n")
