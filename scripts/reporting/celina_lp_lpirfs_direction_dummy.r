#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(tidyverse)
  library(lpirfs)
})

set.seed(42)
cat("\n=== LPIRFS CONSUMPTION HETEROGENEITY (directional dummies, TWFE only) ===\n\n")

MAX_HORIZON <- 48
LP_HOR <- MAX_HORIZON + 1
CI_LEVEL <- 90
CI_MULT <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)
SE_METHOD <- "driscoll_kraay"

OUT_TBL <- "results/tables/lp_controls"
OUT_PLT <- "results/plots/lp_controls"
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(
    month_num = month,
    lag1_share_ph2m = lag1_share_PH2M,
    lag1_share_wh2m = lag1_share_WH2M,
    lag1_share_ricardian = lag1_share_Ricardian
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
    log_consumption = log(consumption_index),
    log_imports = log(coalesce(vl_imports, 0) + 1),
    log_exports = log(coalesce(vl_exports, 0) + 1),
    log_bf = log(coalesce(total_value_BF_old, 0) + 1),
    infl_mom = log(ipca_index) - log(lag(ipca_index, 1)),
    infl_yoy_raw = log(ipca_index) - log(lag(ipca_index, 12)),
    infl_yoy = coalesce(infl_yoy_raw, infl_mom * 12),
    lag1_lc = lag(log_consumption),
    mp_shock_pos = pmax(mp_shock, 0),
    mp_shock_neg_abs = abs(pmin(mp_shock, 0)),
    mp_pos_x_ph2m = mp_shock_pos * lag1_share_ph2m,
    mp_neg_x_ph2m = mp_shock_neg_abs * lag1_share_ph2m,
    mp_pos_x_wh2m = mp_shock_pos * lag1_share_wh2m,
    mp_neg_x_wh2m = mp_shock_neg_abs * lag1_share_wh2m,
    mp_pos_x_ricardian = mp_shock_pos * lag1_share_ricardian,
    mp_neg_x_ricardian = mp_shock_neg_abs * lag1_share_ricardian,
    ym_id = year * 100L + month_num
  ) |>
  ungroup()

if (!"log_credit_pf" %in% names(panel)) {
  stop("Expected column missing: log_credit_pf")
}

CTRL_BASE <- c(
  "lag1_share_ph2m", "lag1_share_wh2m", "log_imports", "log_exports",
  "infl_yoy", "log_bf", "log_credit_pf", "lag1_lc"
)

shock_terms <- c(
  "mp_pos_x_ph2m", "mp_neg_x_ph2m",
  "mp_pos_x_wh2m", "mp_neg_x_wh2m",
  "mp_pos_x_ricardian", "mp_neg_x_ricardian"
)
required_cols <- c("uf_code", "ym_id", "log_consumption", shock_terms, CTRL_BASE)
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
    log_consumption,
    all_of(shock_terms),
    all_of(CTRL_BASE)
  )

cat(sprintf("✓ Prefiltered sample: %d rows\n", nrow(base_panel)))

run_lpirfs <- function(data_set, shock_var, contemp_others) {
  lpirfs::lp_lin_panel(
    data_set = data_set,
    endog_data = "log_consumption",
    cumul_mult = TRUE,
    shock = shock_var,
    diff_shock = FALSE,
    panel_model = "within",
    panel_effect = "twoways",
    robust_cov = "vcovSCC",
    robust_type = "HC1",
    robust_maxlag = 6,
    c_exog_data = contemp_others,
    l_exog_data = CTRL_BASE,
    lags_exog_data = 1,
    confint = CI_MULT,
    hor = LP_HOR
  )
}

extract_series <- function(res_obj, term, shock_sd) {
  irf_mean <- as.numeric(res_obj$irf_panel_mean[1, ])
  irf_low <- as.numeric(res_obj$irf_panel_low[1, ])
  irf_up <- as.numeric(res_obj$irf_panel_up[1, ])
  nobs_h <- map_dbl(res_obj$reg_outputs, ~ as.numeric(tryCatch(stats::nobs(.x), error = function(e) NA_real_)))

  if (!(length(irf_mean) == LP_HOR && length(nobs_h) == LP_HOR)) {
    stop(sprintf("Unexpected horizon length from lp_lin_panel for %s", term))
  }

  tibble(
    horizon = 0:MAX_HORIZON,
    term = term,
    estimate = irf_mean,
    ci_low = irf_low,
    ci_high = irf_up,
    se = (ci_high - estimate) / CI_MULT,
    shock_sd = shock_sd,
    estimate_1sd = estimate * shock_sd,
    ci_low_1sd = ci_low * shock_sd,
    ci_high_1sd = ci_high * shock_sd,
    nobs = nobs_h,
    se_method = SE_METHOD,
    response_type = "cumulative",
    spec = "twfe_directional_dummies"
  )
}

shock_sd <- sapply(shock_terms, function(v) stats::sd(bench_input[[v]], na.rm = TRUE))
rows <- list()

for (term in shock_terms) {
  cat(sprintf("→ Running TWFE LP for %s ...\n", term))
  others <- setdiff(shock_terms, term)
  res <- run_lpirfs(bench_input, term, others)
  rows[[length(rows) + 1]] <- extract_series(res, term, shock_sd[[term]])
}

out_df <- bind_rows(rows)
out_csv <- file.path(OUT_TBL, "irf_consumption_directional_dummies_twfe_dk.csv")
write_csv(out_df, out_csv)
cat(sprintf("✓ Saved benchmark table: %s\n", out_csv))

plot_df <- out_df |>
  mutate(
    panel_label = recode(
      term,
      mp_pos_x_ph2m       = "PH2M x Contractionary shock",
      mp_neg_x_ph2m       = "PH2M x Expansionary shock",
      mp_pos_x_wh2m       = "WH2M x Contractionary shock",
      mp_neg_x_wh2m       = "WH2M x Expansionary shock",
      mp_pos_x_ricardian  = "Ricardian x Contractionary shock",
      mp_neg_x_ricardian  = "Ricardian x Expansionary shock"
    ),
    panel_label = factor(panel_label, levels = c(
      "PH2M x Contractionary shock", "PH2M x Expansionary shock",
      "WH2M x Contractionary shock", "WH2M x Expansionary shock",
      "Ricardian x Contractionary shock", "Ricardian x Expansionary shock"
    ))
  )

p <- ggplot(plot_df, aes(x = horizon, y = estimate_1sd)) +
  geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.16, color = NA, fill = "#1f77b4") +
  geom_line(linewidth = 0.9, color = "#1f77b4") +
  facet_wrap(~panel_label, nrow = 3, ncol = 2, scales = "free_y") +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title = "Consumption LP IRFs with Directional Dummies (TWFE)",
    subtitle = "Outcome: log(consumption_index); one LP per directional interaction shock; Driscoll-Kraay 90% CI; responses scaled to 1-SD of each shock",
    x = "Horizon (months)",
    y = "Cumulative log consumption response (for 1-SD directional interaction shock)"
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
    legend.position = "none"
  )

out_png <- file.path(OUT_PLT, "irf_consumption_directional_dummies_twfe_dk_6panel.png")
ggsave(out_png, p, width = 11, height = 12, dpi = 300)
cat(sprintf("✓ Saved benchmark plot: %s\n", out_png))

check_h <- identical(sort(unique(out_df$horizon)), 0:MAX_HORIZON)
term_counts <- out_df |> count(term) |> pull(n)
check_terms <- all(term_counts == (MAX_HORIZON + 1))
check_nobs <- out_df |>
  group_by(term) |>
  summarise(non_increasing = all(diff(nobs) <= 0, na.rm = TRUE), .groups = "drop")

cat("\nVerification:\n")
cat(sprintf("  - horizons exactly 0:%d: %s\n", MAX_HORIZON, ifelse(check_h, "OK", "FAIL")))
cat(sprintf("  - full coefficient paths present (6 directional terms): %s\n", ifelse(check_terms, "OK", "FAIL")))
cat("  - nobs weakly non-increasing by series:\n")
print(check_nobs)

cat("\nNotes:\n")
cat("  - TWFE only (panel_effect='twoways').\n")
cat("  - Directional heterogeneity via separate directional shock interactions, not lp_nl_panel.\n")
cat("  - Each LP includes the other three directional shocks as contemporaneous controls.\n")

cat("\n=== LPIRFS CONSUMPTION HETEROGENEITY COMPLETE ===\n")
