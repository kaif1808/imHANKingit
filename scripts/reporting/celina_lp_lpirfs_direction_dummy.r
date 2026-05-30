#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(tidyverse)
  library(lpirfs)
})

set.seed(42)
cat("\n=== LPIRFS CONSUMPTION HETEROGENEITY (directional dummies, TWFE only) ===\n\n")

MAX_HORIZON <- 48
LP_HOR      <- MAX_HORIZON + 1
CI_LEVEL    <- 90
CI_MULT     <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)
SE_METHOD   <- "driscoll_kraay"

OUT_TBL <- "results/tables/lp_controls"
OUT_PLT <- "results/plots/lp_controls"
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

SHOCK_SERIES <- c("mp_shock_di", "eps_rr", "eps_sb", "eps_tvp")
SHOCK_LABELS <- c(
  mp_shock_di = "DI Shock",
  eps_rr      = "RR Shock",
  eps_sb      = "SB Shock",
  eps_tvp     = "TVP Shock"
)

CTRL_BASE <- c(
  "lag1_share_ph2m", "lag1_share_wh2m", "log_imports", "log_exports",
  "infl_yoy", "log_bf", "log_credit_pf", "lag1_lc"
)

AGENT_SUFFIXES <- c("ph2m", "wh2m", "ricardian")

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(
    month_num            = month,
    lag1_share_ph2m      = lag1_share_PH2M,
    lag1_share_wh2m      = lag1_share_WH2M,
    lag1_share_ricardian = lag1_share_Ricardian
  )

missing_shocks <- setdiff(SHOCK_SERIES, names(d_raw))
if (length(missing_shocks) > 0) {
  stop(sprintf("Shock columns not found in dataset: %s", paste(missing_shocks, collapse = ", ")))
}

cat(sprintf("✓ Loaded: %d rows, %d states, years %d-%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code), min(d_raw$year), max(d_raw$year)))
cat(sprintf("✓ Running %d shock series: %s\n\n", length(SHOCK_SERIES), paste(SHOCK_SERIES, collapse = ", ")))

base_panel <- d_raw |>
  arrange(uf_code, year, month_num) |>
  group_by(uf_code) |>
  mutate(
    log_consumption = log(consumption_index),
    log_imports     = log(coalesce(vl_imports, 0) + 1),
    log_exports     = log(coalesce(vl_exports, 0) + 1),
    log_bf          = log(coalesce(total_value_BF_old, 0) + 1),
    infl_mom        = log(ipca_index) - log(lag(ipca_index, 1)),
    infl_yoy_raw    = log(ipca_index) - log(lag(ipca_index, 12)),
    infl_yoy        = coalesce(infl_yoy_raw, infl_mom * 12),
    lag1_lc         = lag(log_consumption),
    ym_id           = year * 100L + month_num
  ) |>
  ungroup()

if (!"log_credit_pf" %in% names(base_panel)) stop("Expected column missing: log_credit_pf")

# ── helper: build shock-specific directional interaction columns ───────────────
build_shock_panel <- function(panel, shock_col) {
  shock_vec   <- panel[[shock_col]]
  pos_vec     <- pmax(shock_vec, 0)
  neg_vec     <- abs(pmin(shock_vec, 0))

  panel |>
    mutate(
      s_pos            = pos_vec,
      s_neg            = neg_vec,
      s_pos_x_ph2m      = s_pos * lag1_share_ph2m,
      s_neg_x_ph2m      = s_neg * lag1_share_ph2m,
      s_pos_x_wh2m      = s_pos * lag1_share_wh2m,
      s_neg_x_wh2m      = s_neg * lag1_share_wh2m,
      s_pos_x_ricardian = s_pos * lag1_share_ricardian,
      s_neg_x_ricardian = s_neg * lag1_share_ricardian
    )
}

SHOCK_TERMS <- c(
  "s_pos_x_ph2m", "s_neg_x_ph2m",
  "s_pos_x_wh2m", "s_neg_x_wh2m",
  "s_pos_x_ricardian", "s_neg_x_ricardian"
)

TERM_LABELS <- c(
  s_pos_x_ph2m      = "PH2M × Contractionary",
  s_neg_x_ph2m      = "PH2M × Expansionary",
  s_pos_x_wh2m      = "WH2M × Contractionary",
  s_neg_x_wh2m      = "WH2M × Expansionary",
  s_pos_x_ricardian = "Ricardian × Contractionary",
  s_neg_x_ricardian = "Ricardian × Expansionary"
)

# ── LP runner ─────────────────────────────────────────────────────────────────
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

extract_series <- function(res_obj, term, shock_col, shock_sd) {
  irf_mean <- as.numeric(res_obj$irf_panel_mean[1, ])
  irf_low  <- as.numeric(res_obj$irf_panel_low[1, ])
  irf_up   <- as.numeric(res_obj$irf_panel_up[1, ])
  nobs_h   <- map_dbl(res_obj$reg_outputs,
                      ~ as.numeric(tryCatch(stats::nobs(.x), error = function(e) NA_real_)))

  if (length(irf_mean) != LP_HOR || length(nobs_h) != LP_HOR) {
    stop(sprintf("Unexpected horizon length for %s / %s", shock_col, term))
  }

  tibble(
    horizon       = 0:MAX_HORIZON,
    shock_series  = shock_col,
    term          = term,
    estimate      = irf_mean,
    ci_low        = irf_low,
    ci_high       = irf_up,
    se            = (ci_high - estimate) / CI_MULT,
    shock_sd      = shock_sd,
    estimate_1sd  = estimate * shock_sd,
    ci_low_1sd    = ci_low  * shock_sd,
    ci_high_1sd   = ci_high * shock_sd,
    nobs          = nobs_h,
    se_method     = SE_METHOD,
    response_type = "cumulative",
    spec          = "twfe_directional_dummies"
  )
}

# ── outer loop over shock series ──────────────────────────────────────────────
all_rows <- list()

for (shock_col in SHOCK_SERIES) {
  cat(sprintf("── Shock series: %s ──\n", shock_col))

  s_panel <- build_shock_panel(base_panel, shock_col)

  req_cols <- c("uf_code", "ym_id", "log_consumption", SHOCK_TERMS, CTRL_BASE)
  s_panel  <- s_panel |> filter(!if_any(all_of(req_cols), is.na))

  lp_input <- s_panel |> select(all_of(req_cols))
  shock_sd  <- sapply(SHOCK_TERMS, function(v) stats::sd(lp_input[[v]], na.rm = TRUE))

  cat(sprintf("  ✓ Effective sample: %d rows\n", nrow(lp_input)))

  for (term in SHOCK_TERMS) {
    cat(sprintf("  → %s\n", term))
    others <- setdiff(SHOCK_TERMS, term)
    res    <- run_lpirfs(lp_input, term, others)
    all_rows[[length(all_rows) + 1]] <- extract_series(res, term, shock_col, shock_sd[[term]])
  }
  cat("\n")
}

out_df  <- bind_rows(all_rows)
out_csv <- file.path(OUT_TBL, "irf_consumption_directional_dummies_twfe_dk_allshocks.csv")
write_csv(out_df, out_csv)
cat(sprintf("✓ Saved combined table: %s\n", out_csv))

# ── per-shock 6-panel plots ───────────────────────────────────────────────────
panel_order <- c(
  "PH2M × Contractionary", "PH2M × Expansionary",
  "WH2M × Contractionary", "WH2M × Expansionary",
  "Ricardian × Contractionary", "Ricardian × Expansionary"
)

for (shock_col in SHOCK_SERIES) {
  plot_df <- out_df |>
    filter(shock_series == shock_col) |>
    mutate(
      panel_label = factor(TERM_LABELS[term], levels = panel_order)
    )

  shock_label <- SHOCK_LABELS[[shock_col]]
  p <- ggplot(plot_df, aes(x = horizon, y = estimate_1sd)) +
    geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
                alpha = 0.16, color = NA, fill = "#1f77b4") +
    geom_line(linewidth = 0.9, color = "#1f77b4") +
    facet_wrap(~panel_label, nrow = 3, ncol = 2, scales = "free_y") +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
    labs(
      title    = sprintf("Consumption LP IRFs — %s (TWFE, directional dummies)", shock_label),
      subtitle = "Driscoll-Kraay 90% CI; responses scaled to 1-SD of each directional interaction",
      x        = "Horizon (months)",
      y        = "Cumulative log consumption response (1-SD shock)"
    ) +
    theme_bw(base_size = 11) +
    theme(
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
      legend.position  = "none"
    )

  out_png <- file.path(OUT_PLT,
    sprintf("irf_consumption_directional_dummies_twfe_dk_%s_6panel.png", shock_col))
  ggsave(out_png, p, width = 11, height = 12, dpi = 300)
  cat(sprintf("✓ Saved plot: %s\n", out_png))
}

# ── verification ──────────────────────────────────────────────────────────────
expected_rows <- length(SHOCK_SERIES) * length(SHOCK_TERMS) * (MAX_HORIZON + 1)
check_n    <- nrow(out_df) == expected_rows
check_h    <- all(out_df |> group_by(shock_series, term) |>
                  summarise(ok = identical(sort(horizon), 0:MAX_HORIZON), .groups = "drop") |>
                  pull(ok))
check_nobs <- out_df |>
  group_by(shock_series, term) |>
  summarise(non_increasing = all(diff(nobs) <= 0, na.rm = TRUE), .groups = "drop")

cat("\nVerification:\n")
cat(sprintf("  - total rows (%d expected): %s\n", expected_rows, ifelse(check_n, "OK", "FAIL")))
cat(sprintf("  - horizons 0:%d for all series: %s\n", MAX_HORIZON, ifelse(check_h, "OK", "FAIL")))
cat("  - nobs weakly non-increasing by series:\n")
print(check_nobs, n = Inf)

cat("\nNotes:\n")
cat("  - TWFE only (panel_effect='twoways').\n")
cat(sprintf("  - %d shock series × 6 directional interaction terms = %d LPs.\n",
            length(SHOCK_SERIES), length(SHOCK_SERIES) * length(SHOCK_TERMS)))
cat("  - Each LP controls for the other 5 directional terms (same shock) contemporaneously.\n")

cat("\n=== LPIRFS CONSUMPTION HETEROGENEITY COMPLETE ===\n")
