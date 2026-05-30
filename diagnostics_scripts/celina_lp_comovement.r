#!/usr/bin/env Rscript
# Comovement LPs — two parts:
#
# PART A — Granger-type LP (no MP shock, variable predicts another)
#   State-panel TWFE: lagged growth in X predicts cumulative response in Y
#   Four directions: consumption→income, consumption→wealth,
#                    income→consumption, wealth→consumption
#   CIs: cluster-robust (vcovCL, HC1, clustered on state)
#
# PART B — Overlay comparison plots
#   Loads TWFE results (consumption spec) for income, wealth, and consumption
#   and overlays all three on the same panel per (shock × direction × HtM)
#   to visualise comovement in MP shock responses
#
# Dataset: state_month_lp_dataset_.csv
# Output: results/tables/lp_comovement/
#         results/plots/lp_comovement/

library(tidyverse)
library(sandwich)

set.seed(42)
cat("\n=== COMOVEMENT LPs ===\n\n")

MAX_HORIZON <- 48L
CI_MULT     <- qnorm(0.95)   # 90% CI

OUT_TBL <- "results/tables/lp_comovement"
OUT_PLT <- "results/plots/lp_comovement"
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)

# ── Load data ──────────────────────────────────────────────────────────────────

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset_.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(
    month_num       = month,
    lag1_share_ph2m = lag1_share_PH2M,
    lag1_share_wh2m = lag1_share_WH2M
  )

cat(sprintf("✓ Loaded: %d rows, %d states, years %d–%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code),
            min(d_raw$year), max(d_raw$year)))

# ── Theme ──────────────────────────────────────────────────────────────────────

irf_theme <- function() {
  theme_bw(base_size = 11) +
    theme(
      panel.grid.minor       = element_blank(),
      panel.grid.major       = element_line(color = "gray92", linewidth = 0.3),
      strip.background       = element_blank(),
      strip.text             = element_text(size = 10, face = "bold"),
      legend.position        = "inside",
      legend.position.inside = c(0.97, 0.97),
      legend.justification   = c(1, 1),
      legend.background      = element_rect(fill = alpha("white", 0.85), color = NA),
      legend.title           = element_blank(),
      legend.text            = element_text(size = 9),
      axis.title             = element_text(size = 10),
      plot.title             = element_text(size = 11, hjust = 0.5),
      plot.subtitle          = element_text(size = 8.5, hjust = 0.5, color = "gray40")
    )
}

vcov_cl <- function(m, cl) sandwich::vcovCL(m, cluster = cl, type = "HC1")

get_coef <- function(m, vc, term) {
  idx <- grep(paste0("^", term, "$"), rownames(vc), perl = TRUE)[1]
  if (is.na(idx)) return(c(b = NA_real_, se = NA_real_))
  c(b  = as.numeric(coef(m)[rownames(vc)[idx]]),
    se = sqrt(as.numeric(vc[idx, idx])))
}

# ════════════════════════════════════════════════════════════════════════════════
# PART A — Granger-type comovement LP (no MP shock)
# ════════════════════════════════════════════════════════════════════════════════

cat("\n── PART A: Granger-type comovement LPs ──────────────────────────────────\n\n")

# Build full panel with all variables
panel <- d_raw |>
  arrange(uf_code, year, month_num) |>
  group_by(uf_code) |>
  mutate(
    log_consumption  = log(consumption_index),
    log_income_sa    = log(mean_income_sa),
    asinh_wealth     = asinh(net_liquid_proxy),
    log_real_imports = log(real_imports + 1),
    log_real_exports = log(real_exports + 1),
    log_bf_raw         = log(coalesce(total_value_BF_old, 0) + 1),
    log_bf_growth      = log_bf_raw - lag(log_bf_raw, 1),
    lag1_log_bf_growth = lag(log_bf_growth, 1),
    infl_mom         = log(ipca_index) - log(lag(ipca_index, 1)),
    infl_yoy_raw     = log(ipca_index) - log(lag(ipca_index, 12)),
    infl_yoy         = coalesce(infl_yoy_raw, infl_mom * 12),
    # lagged levels
    lag1_lc          = lag(log_consumption),
    lag2_lc          = lag(log_consumption, 2),
    lag1_li          = lag(log_income_sa),
    lag2_li          = lag(log_income_sa, 2),
    lag1_aw          = lag(asinh_wealth),
    lag2_aw          = lag(asinh_wealth, 2),
    # lagged growth (predictor for Granger LP)
    lag1_d_lc        = lag1_lc - lag2_lc,   # lagged consumption growth
    lag1_d_li        = lag1_li - lag2_li,   # lagged income growth
    lag1_d_aw        = lag1_aw - lag2_aw,   # lagged wealth growth
    ym               = year * 100L + month_num
  ) |>
  ungroup()

# Common controls (no MP shock)
CTRL_COMMON <- c("lag1_share_ph2m", "lag1_share_wh2m",
                 "log_real_imports", "log_real_exports",
                 "infl_yoy", "log_bf_growth", "lag1_log_bf_growth",
                 "dummy_2015", "dummy_2016", "dummy_2020")

# ── Define Granger LP pairs ────────────────────────────────────────────────────
# predictor: lagged growth in X; DV: cumulative change in Y; own-lag of Y as control

GRANGER_PAIRS <- list(
  con_to_inc = list(
    label      = "Consumption → Income",
    predictor  = "lag1_d_lc",
    dv         = "log_income_sa",
    own_lag    = "lag1_li",
    pred_label = "Lagged consumption growth",
    dv_label   = "Cumulative log income response"
  ),
  con_to_wea = list(
    label      = "Consumption → Wealth",
    predictor  = "lag1_d_lc",
    dv         = "asinh_wealth",
    own_lag    = "lag1_aw",
    pred_label = "Lagged consumption growth",
    dv_label   = "Cumulative asinh(wealth) response"
  ),
  inc_to_con = list(
    label      = "Income → Consumption",
    predictor  = "lag1_d_li",
    dv         = "log_consumption",
    own_lag    = "lag1_lc",
    pred_label = "Lagged income growth",
    dv_label   = "Cumulative log consumption response"
  ),
  wea_to_con = list(
    label      = "Wealth → Consumption",
    predictor  = "lag1_d_aw",
    dv         = "log_consumption",
    own_lag    = "lag1_lc",
    pred_label = "Lagged wealth (asinh) growth",
    dv_label   = "Cumulative log consumption response"
  )
)

RTYPES <- c("cumulative", "marginal")

granger_all <- list()

for (pair_name in names(GRANGER_PAIRS)) {
  pair       <- GRANGER_PAIRS[[pair_name]]
  pair_lab   <- pair$label       # extract before tibble to avoid $ conflict
  pair_pred  <- pair$predictor
  pair_dv    <- pair$dv
  pair_lag   <- pair$own_lag
  cat(sprintf("  Running: %s\n", pair_lab))

  for (rtype in RTYPES) {
    rows <- vector("list", MAX_HORIZON + 1)

    for (h in 0:MAX_HORIZON) {
      d <- panel |>
        filter(!is.na(.data[[pair_pred]]),
               !is.na(.data[[pair_lag]]),
               !is.na(.data[[pair_dv]])) |>
        filter(if_all(all_of(CTRL_COMMON), ~ !is.na(.))) |>
        arrange(uf_code, year, month_num) |>
        group_by(uf_code) |>
        mutate(y_resp = if (rtype == "cumulative") {
          lead(.data[[pair_dv]], h) - .data[[pair_lag]]
        } else if (h == 0) {
          .data[[pair_dv]] - .data[[pair_lag]]
        } else {
          lead(.data[[pair_dv]], h) - lead(.data[[pair_dv]], h - 1)
        }) |>
        ungroup() |>
        filter(!is.na(y_resp))

      fml <- as.formula(paste(
        "y_resp ~", pair_pred, "+", pair_lag, "+",
        paste(CTRL_COMMON, collapse = " + "),
        "+ factor(uf_code) + factor(ym)"
      ))

      m  <- lm(fml, data = d)
      vc <- vcov_cl(m, d$uf_code)
      b  <- get_coef(m, vc, pair_pred)

      rows[[h + 1]] <- tibble(
        horizon       = h,
        b_pred        = b[["b"]],
        se_pred       = b[["se"]],
        ci_lo         = b[["b"]] - CI_MULT * b[["se"]],
        ci_hi         = b[["b"]] + CI_MULT * b[["se"]],
        nobs          = nrow(d),
        pair          = pair_name,
        pair_label    = pair_lab,
        response_type = rtype
      )
    }

    key <- paste(pair_name, rtype, sep = "_")
    res <- bind_rows(rows)
    granger_all[[key]] <- res

    csv_name <- sprintf("granger_%s_%s.csv", pair_name, rtype)
    write_csv(res, file.path(OUT_TBL, csv_name))
    cat(sprintf("    ✓ %s | %s\n", pair$label, rtype))
  }
}

granger_combined <- bind_rows(granger_all)
write_csv(granger_combined, file.path(OUT_TBL, "granger_all.csv"))
cat(sprintf("\n✓ Granger combined: %d rows → %s/granger_all.csv\n",
            nrow(granger_combined), OUT_TBL))

# ── Granger plots ──────────────────────────────────────────────────────────────

PAIR_COLOURS <- c(
  con_to_inc = "#1f77b4",
  con_to_wea = "#2ca02c",
  inc_to_con = "#d62728",
  wea_to_con = "#9467bd"
)

PAIR_LABELS <- sapply(GRANGER_PAIRS, `[[`, "label")

granger_df <- granger_combined |>
  mutate(
    pair = factor(pair, levels = names(GRANGER_PAIRS)),
    response_type = factor(response_type, levels = c("cumulative", "marginal"),
                           labels = c("Cumulative", "Marginal"))
  )

# 4-panel: one panel per pair, both cumulative and marginal overlaid
for (rt_lab in c("Cumulative", "Marginal")) {
  ytitle <- if (rt_lab == "Cumulative") "Cumulative response to 1-unit lagged growth" else "Marginal response to 1-unit lagged growth"

  p <- granger_df |>
    filter(response_type == rt_lab) |>
    ggplot(aes(x = horizon, y = b_pred)) +
    geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi, fill = pair), alpha = 0.15, color = NA) +
    geom_line(aes(color = pair), linewidth = 0.9) +
    facet_wrap(~ pair_label, nrow = 2, ncol = 2, scales = "free_y") +
    scale_color_manual(values = PAIR_COLOURS, guide = "none") +
    scale_fill_manual( values = PAIR_COLOURS, guide = "none") +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
    labs(
      title    = sprintf("Granger-type Comovement LP (%s)", rt_lab),
      subtitle = "State-panel TWFE · cluster-robust 90% CI · no MP shock · lagged growth as predictor",
      x = "Horizon (months)", y = ytitle
    ) + irf_theme()

  fname <- sprintf("granger_comovement_%s_4panel.png", tolower(rt_lab))
  ggsave(file.path(OUT_PLT, fname), p, width = 10, height = 8, dpi = 300)
  cat(sprintf("  ✓ %s\n", fname))
}

# All pairs + both rtypes: 4×2 grid
p_grid <- granger_df |>
  ggplot(aes(x = horizon, y = b_pred)) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi, fill = pair), alpha = 0.15, color = NA) +
  geom_line(aes(color = pair), linewidth = 0.9) +
  facet_grid(response_type ~ pair_label, scales = "free_y") +
  scale_color_manual(values = PAIR_COLOURS, guide = "none") +
  scale_fill_manual( values = PAIR_COLOURS, guide = "none") +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "Granger-type Comovement LPs — All Pairs",
    subtitle = "State-panel TWFE · cluster-robust 90% CI · no MP shock · lagged growth as predictor",
    x = "Horizon (months)", y = "Response to 1-unit lagged growth"
  ) + irf_theme()

ggsave(file.path(OUT_PLT, "granger_comovement_all_8panel.png"),
       p_grid, width = 14, height = 7, dpi = 300)
cat("  ✓ granger_comovement_all_8panel.png\n")

# ════════════════════════════════════════════════════════════════════════════════
# PART B — Overlay: income, wealth, consumption TWFE responses
# ════════════════════════════════════════════════════════════════════════════════

cat("\n── PART B: Overlay comparison plots ─────────────────────────────────────\n\n")

CON_PATH <- "results/tables/lp_consumption_twfe/irf_consumption_twfe_all.csv"
INC_PATH <- "results/tables/lp_income_twfe_consumption_spec/irf_income_twfe_all.csv"
WEA_PATH <- "results/tables/lp_wealth_twfe_consumption_spec/irf_wealth_twfe_all.csv"

missing_paths <- Filter(Negate(file.exists), c(CON_PATH, INC_PATH, WEA_PATH))
if (length(missing_paths) > 0) {
  cat("WARNING: missing TWFE result files — skipping overlay plots:\n")
  cat(paste(" ", missing_paths, collapse = "\n"), "\n")
} else {

  con_df <- read_csv(CON_PATH, show_col_types = FALSE) |> mutate(outcome = "Consumption")
  inc_df <- read_csv(INC_PATH, show_col_types = FALSE) |> mutate(outcome = "Income")
  wea_df <- read_csv(WEA_PATH, show_col_types = FALSE) |> mutate(outcome = "Wealth (asinh)")

  overlay <- bind_rows(con_df, inc_df, wea_df) |>
    mutate(
      outcome   = factor(outcome, levels = c("Consumption", "Income", "Wealth (asinh)")),
      shock_col = factor(shock_col, levels = c("mp_shock_di", "eps_rr", "eps_sb", "eps_tvp")),
      direction = factor(direction,
                         levels = c("Full (Signed)", "Contractionary", "Expansionary")),
      htm_type  = factor(htm_type, levels = c("PH2M", "WH2M"))
    )

  OUTCOME_COLOURS <- c(
    "Consumption"    = "#1f77b4",
    "Income"         = "#d62728",
    "Wealth (asinh)" = "#2ca02c"
  )

  ALL_SHOCKS <- c(
    mp_shock_di = "DI Surprise",
    eps_rr      = "eps_rr (OLS)",
    eps_sb      = "eps_sb (Bai-Perron)",
    eps_tvp     = "eps_tvp (TVP-Bayes)"
  )

  cat("  Generating overlay plots...\n")

  # 1. Per shock: 6-panel (direction × HtM), three outcomes overlaid
  for (sc in levels(overlay$shock_col)) {
    sl <- ALL_SHOCKS[[sc]]

    p <- overlay |>
      filter(shock_col == sc) |>
      ggplot(aes(x = horizon, y = estimate_1sd,
                 color = outcome, fill = outcome)) +
      geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
      geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.12, color = NA) +
      geom_line(linewidth = 0.85) +
      facet_grid(htm_type ~ direction, scales = "free_y") +
      scale_color_manual(values = OUTCOME_COLOURS) +
      scale_fill_manual( values = OUTCOME_COLOURS) +
      scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
      labs(
        title    = sprintf("Consumption, Income & Wealth LP IRFs — %s (TWFE)", sl),
        subtitle = "state+time FE · DK 90% CI · 1-SD shock · consumption spec · comovement comparison",
        x = "Horizon (months)", y = "Cumulative response (1-SD shock, own scale)"
      ) + irf_theme()

    fname <- sprintf("overlay_twfe_%s_6panel.png", sc)
    ggsave(file.path(OUT_PLT, fname), p, width = 12, height = 7, dpi = 300)
    cat(sprintf("    ✓ %s\n", fname))
  }

  # 2. Per direction × HtM: all shocks as facets, three outcomes overlaid
  for (dir_val in levels(overlay$direction)) {
    for (htm_val in levels(overlay$htm_type)) {
      dir_slug <- gsub("[^a-z0-9]+", "_", tolower(dir_val))
      htm_slug <- tolower(htm_val)

      p <- overlay |>
        filter(direction == dir_val, htm_type == htm_val) |>
        ggplot(aes(x = horizon, y = estimate_1sd,
                   color = outcome, fill = outcome)) +
        geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
        geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.12, color = NA) +
        geom_line(linewidth = 0.85) +
        facet_wrap(~ shock_col, nrow = 2,
                   labeller = labeller(shock_col = ALL_SHOCKS)) +
        scale_color_manual(values = OUTCOME_COLOURS) +
        scale_fill_manual( values = OUTCOME_COLOURS) +
        scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
        labs(
          title    = sprintf("Comovement — %s | %s (all shocks)", dir_val, htm_val),
          subtitle = "Consumption, Income & Wealth TWFE IRFs · DK 90% CI · 1-SD shock",
          x = "Horizon (months)", y = "Cumulative response (1-SD shock, own scale)"
        ) + irf_theme()

      fname <- sprintf("overlay_twfe_%s_%s_allshocks.png", dir_slug, htm_slug)
      ggsave(file.path(OUT_PLT, fname), p, width = 10, height = 8, dpi = 300)
      cat(sprintf("    ✓ %s\n", fname))
    }
  }

  # 3. Summary: lag1, contractionary + expansionary, PH2M + WH2M — 4-panel
  p_sum <- overlay |>
    filter(direction %in% c("Contractionary", "Expansionary")) |>
    ggplot(aes(x = horizon, y = estimate_1sd,
               color = outcome, fill = outcome)) +
    geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.10, color = NA) +
    geom_line(linewidth = 0.85) +
    facet_grid(htm_type ~ direction, scales = "free_y") +
    scale_color_manual(values = OUTCOME_COLOURS) +
    scale_fill_manual( values = OUTCOME_COLOURS) +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
    labs(
      title    = "Comovement — Consumption, Income & Wealth (TWFE, all shocks pooled view)",
      subtitle = "DK 90% CI · 1-SD shock · all 4 shocks overlaid",
      x = "Horizon (months)", y = "Cumulative response (1-SD shock, own scale)"
    ) + irf_theme()

  ggsave(file.path(OUT_PLT, "overlay_twfe_summary_4panel.png"),
         p_sum, width = 10, height = 7, dpi = 300)
  cat("    ✓ overlay_twfe_summary_4panel.png\n")

  write_csv(overlay, file.path(OUT_TBL, "overlay_twfe_all_outcomes.csv"))
  cat(sprintf("\n✓ Overlay combined: %d rows → %s/overlay_twfe_all_outcomes.csv\n",
              nrow(overlay), OUT_TBL))
}

cat(sprintf("\n✓ All plots → %s/\n", OUT_PLT))
cat("\n=== COMOVEMENT LP DONE ===\n")
cat(sprintf("  Tables: %s/\n", OUT_TBL))
cat(sprintf("  Plots:  %s/\n", OUT_PLT))
