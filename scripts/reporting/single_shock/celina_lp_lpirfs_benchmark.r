#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(tidyverse)
  library(lpirfs)
})

set.seed(42)
cat("\n=== LPIRFS BENCHMARK (lag1_tfe + cumulative + contractionary) ===\n\n")

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
    log_consumption = log(consumption_index),
    log_imports = log(coalesce(vl_imports, 0) + 1),
    log_exports = log(coalesce(vl_exports, 0) + 1),
    log_bf = log(coalesce(total_value_BF_old, 0) + 1),
    infl_mom = log(ipca_index) - log(lag(ipca_index, 1)),
    infl_yoy_raw = log(ipca_index) - log(lag(ipca_index, 12)),
    infl_yoy = coalesce(infl_yoy_raw, infl_mom * 12),
    lag1_lc = lag(log_consumption),
    lag2_lc = lag(log_consumption, 2),
    # Shock splits outside any horizon transforms.
    mp_shock_pos = pmax(mp_shock, 0),
    mp_shock_neg_abs = abs(pmin(mp_shock, 0)),
    # Interaction terms based on lagged shares.
    mp_pos_x_ph2m = mp_shock_pos * lag1_share_ph2m,
    mp_pos_x_wh2m = mp_shock_pos * lag1_share_wh2m,
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

required_cols <- c(
  "uf_code", "ym_id", "log_consumption", "mp_shock_pos",
  "mp_pos_x_ph2m", "mp_pos_x_wh2m", CTRL_BASE
)
missing_cols <- setdiff(required_cols, names(panel))
if (length(missing_cols) > 0) {
  stop(sprintf("Missing required columns: %s", paste(missing_cols, collapse = ", ")))
}

# Static pre-filter outside horizon loops for lag/shock/control availability.
base_panel <- panel |>
  filter(!if_any(all_of(required_cols), is.na))

bench_input <- base_panel |>
  select(
    uf_code,
    ym_id,
    log_consumption,
    mp_shock_pos,
    mp_pos_x_ph2m,
    mp_pos_x_wh2m,
    all_of(CTRL_BASE)
  )

cat(sprintf("✓ Prefiltered benchmark sample: %d rows\n", nrow(base_panel)))

run_lpirfs <- function(data_set, shock_var, contemp_other, panel_effect, robust_cov, robust_type = NULL, robust_cluster = NULL, robust_maxlag = NULL) {
  lpirfs::lp_lin_panel(
    data_set = data_set,
    endog_data = "log_consumption",
    cumul_mult = TRUE,
    # Cumulative baseline is aligned to t via y_{t+h} - y_t from lpirfs when cumul_mult=TRUE.
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
    confint = CI_MULT,
    hor = LP_HOR
  )
}

extract_series <- function(res_obj, label, se_type, panel_effect_label, shock_var, shock_sd) {
  irf_mean <- as.numeric(res_obj$irf_panel_mean[1, ])
  irf_low <- as.numeric(res_obj$irf_panel_low[1, ])
  irf_up <- as.numeric(res_obj$irf_panel_up[1, ])
  if (!(length(irf_mean) == LP_HOR && length(nobs_h <- map_dbl(res_obj$reg_outputs, ~ as.numeric(tryCatch(stats::nobs(.x), error = function(e) NA_real_)))) == LP_HOR)) {
    stop(sprintf("Unexpected horizon length from lpirfs for %s", label))
  }

  tibble(
    horizon = 0:MAX_HORIZON,
    term = label,
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
    shock_type = "contractionary",
    response_type = "cumulative",
    spec = ifelse(panel_effect_label == "twoways", "lag1_tfe", "lag1_individual_fe"),
    panel_effect = panel_effect_label
  )
}

shock_sd <- c(
  mp_pos_x_ph2m = stats::sd(bench_input$mp_pos_x_ph2m, na.rm = TRUE),
  mp_pos_x_wh2m = stats::sd(bench_input$mp_pos_x_wh2m, na.rm = TRUE)
)

panel_effects <- c("twoways", "individual")
rows <- list()

for (pe in panel_effects) {
  cat(sprintf("→ Running panel_effect=%s benchmark...\n", pe))

  res_se_ph2m <- run_lpirfs(
    data_set = bench_input,
    shock_var = "mp_pos_x_ph2m",
    contemp_other = "mp_pos_x_wh2m",
    panel_effect = pe,
    robust_cov = "vcovSCC",
    robust_type = "HC1",
    robust_maxlag = 6
  )
  res_se_wh2m <- run_lpirfs(
    data_set = bench_input,
    shock_var = "mp_pos_x_wh2m",
    contemp_other = "mp_pos_x_ph2m",
    panel_effect = pe,
    robust_cov = "vcovSCC",
    robust_type = "HC1",
    robust_maxlag = 6
  )

  rows[[length(rows) + 1]] <- extract_series(res_se_ph2m, "mp_pos_x_ph2m", SE_METHOD, pe, "mp_pos_x_ph2m", shock_sd[["mp_pos_x_ph2m"]])
  rows[[length(rows) + 1]] <- extract_series(res_se_wh2m, "mp_pos_x_wh2m", SE_METHOD, pe, "mp_pos_x_wh2m", shock_sd[["mp_pos_x_wh2m"]])
}

out_df <- bind_rows(rows)

out_csv <- file.path(OUT_TBL, "irf_con_cumulative_lag1_lpirfs_benchmark_dk_only_dual_fe.csv")
write_csv(out_df, out_csv)
cat(sprintf("✓ Saved benchmark table: %s\n", out_csv))

plot_df <- out_df |>
  mutate(
    term_label = recode(
      term,
      mp_pos_x_ph2m = "PH2M exposure x MP shock",
      mp_pos_x_wh2m = "WH2M exposure x MP shock"
    ),
    panel_effect_label = recode(
      panel_effect,
      twoways = "Two-way FE",
      individual = "State FE"
    )
  )

p <- ggplot(plot_df, aes(x = horizon, y = estimate_1sd, linetype = panel_effect_label)) +
  geom_hline(yintercept = 0, color = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.14, color = NA, fill = "#1f77b4") +
  geom_line(linewidth = 0.9, color = "#1f77b4") +
  facet_wrap(~term_label, nrow = 1, scales = "free_y") +
  scale_linetype_manual(values = c("Two-way FE" = "solid", "State FE" = "22")) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title = "Cumulative Contractionary LP IRFs (lpirfs benchmark)",
    subtitle = sprintf(
      "Baseline y[t+h]-y[t]; fixed-included log_credit_pf; plotted as response to 1-SD shock (PH2M SD=%.4f, WH2M SD=%.4f); 90%% CI",
      shock_sd[["mp_pos_x_ph2m"]], shock_sd[["mp_pos_x_wh2m"]]
    ),
    x = "Horizon (months)",
    y = "Cumulative log response (for 1-SD interaction shock)",
    linetype = "Panel effect"
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
    legend.position = "bottom"
  )

out_png <- file.path(OUT_PLT, "irf_con_cumulative_lag1_lpirfs_benchmark_dk_only_dual_fe.png")
ggsave(out_png, p, width = 10, height = 4.5, dpi = 300)
cat(sprintf("✓ Saved benchmark plot: %s\n", out_png))

# Structural verification checks requested in benchmark plan.
check_h <- identical(sort(unique(out_df$horizon)), 0:MAX_HORIZON)
term_counts <- out_df |>
  count(se_method, term, panel_effect) |>
  pull(n)
check_terms <- all(term_counts == (MAX_HORIZON + 1))
check_nobs <- out_df |>
  group_by(se_method, term, panel_effect) |>
  summarise(non_increasing = all(diff(nobs) <= 0, na.rm = TRUE), .groups = "drop")

cat("\nVerification:\n")
cat(sprintf("  - horizons exactly 0:%d: %s\n", MAX_HORIZON, ifelse(check_h, "OK", "FAIL")))
cat(sprintf("  - full coefficient paths present: %s\n", ifelse(check_terms, "OK", "FAIL")))
cat("  - nobs weakly non-increasing by series:\n")
print(check_nobs)

cat("\nNotes:\n")
cat("  - Cumulative baseline switched to t (y[t+h]-y[t]) in benchmark path.\n")
cat("  - With two-way FE, common shock level is collinear with time effects; interaction terms are estimated as shocks in separate benchmark runs.\n")
cat("  - Added individual (state FE only) panel effect as a separate control spec.\n")
cat("  - Single SE method used for clarity: Driscoll-Kraay.\n")
cat("  - log_credit_pf is always included to avoid horizon-specific composition drift.\n")
cat("  - Table reports both per-1-unit and per-1-SD shock magnitudes.\n")

cat("\n=== LPIRFS BENCHMARK COMPLETE ===\n")
