#!/usr/bin/env Rscript
# Consumption LP — TWFE — All Shocks (DI + narrative) — directional splits
#
# Execution order:
#   1. PRE-TESTS    : stationarity (IPS/ADF) + Ljung-Box on mp_shock_di
#   2. MAIN LP      : TWFE, DK SE, 2 lags, outcome = log(consumption_index)
#   3. BOOTSTRAP    : wild cluster bootstrap CI on main LP estimates
#   4. HP-FILTER LP : same spec, outcome = % deviation from HP-filtered trend
#   5. COMPARISON   : overlay plots of log vs HP-filter IRFs
#   6. LEAD TEST    : placebo lead test on eps_rr only

suppressPackageStartupMessages({
  library(tidyverse)
  library(lpirfs)
  library(plm)      # purtest / IPS
  library(tseries)  # adf.test fallback
  library(mFilter)  # hpfilter
  library(R6)
  library(torch)
})

cat("\n=== CONSUMPTION LP - TWFE - ALL SHOCKS (directional + PH2M/WH2M) ===\n\n")

MAX_HORIZON <- 24L
LP_HOR      <- MAX_HORIZON + 1L
CI_LEVEL    <- 90
CI_MULT     <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)
SE_METHOD   <- "driscoll_kraay"
N_BOOT      <- 99   # set to 99 for a test run
HP_LAMBDA   <- 129600

parse_args <- function() {
  args <- commandArgs(trailingOnly = TRUE)
  cfg <- list(
    bootstrap_backend = "metal",
    n_boot = N_BOOT,
    batch_size = 256L,
    seed = 42L
  )
  if (length(args) == 0) return(cfg)
  for (arg in args) {
    if (grepl("^--bootstrap-backend=", arg)) {
      cfg$bootstrap_backend <- sub("^--bootstrap-backend=", "", arg)
    }
    if (grepl("^--n-boot=", arg)) {
      cfg$n_boot <- as.integer(sub("^--n-boot=", "", arg))
    }
    if (grepl("^--batch-size=", arg)) {
      cfg$batch_size <- as.integer(sub("^--batch-size=", "", arg))
    }
    if (grepl("^--seed=", arg)) {
      cfg$seed <- as.integer(sub("^--seed=", "", arg))
    }
  }
  cfg
}

RUNTIME <- parse_args()
if (!identical(RUNTIME$bootstrap_backend, "metal")) {
  stop("This rewrite only supports --bootstrap-backend=metal")
}
N_BOOT <- RUNTIME$n_boot
set.seed(RUNTIME$seed)

BASE       <- "/Users/kai/Desktop/imHANKingit"
OUT_TBL    <- file.path(BASE, "results/tables/lp_consumption_twfe")
OUT_PLT    <- file.path(BASE, "results/plots/lp_consumption_twfe")
OUT_TBL_HP <- file.path(BASE, "results/tables/lp_consumption_twfe_hp")
OUT_PLT_HP <- file.path(BASE, "results/plots/lp_consumption_twfe_hp")
OUT_PLT_CMP <- file.path(BASE, "results/plots/lp_consumption_twfe_comparison")
for (d in c(OUT_TBL, OUT_PLT, OUT_TBL_HP, OUT_PLT_HP, OUT_PLT_CMP))
  dir.create(d, recursive = TRUE, showWarnings = FALSE)

# ---- Load data ---------------------------------------------------------------

lp_path <- file.path(BASE, "results/datasets/basic_state_month_lp/state_month_lp_dataset_.csv")
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(
    month_num       = month,
    lag1_share_ph2m = lag1_share_PH2M,
    lag1_share_wh2m = lag1_share_WH2M
  )

required_raw <- c("consumption_index", "mp_shock_di", "eps_rr", "eps_sb", "eps_tvp",
                  "lag1_share_ph2m", "lag1_share_wh2m",
                  "dummy_2015", "dummy_2016", "dummy_2020",
                  "log_credit_pf", "ipca_index", "vl_imports", "vl_exports",
                  "total_value_BF_old", "population")
missing_raw <- setdiff(required_raw, names(d_raw))
if (length(missing_raw) > 0) stop("Missing columns: ", paste(missing_raw, collapse = ", "))

cat(sprintf("Loaded: %d rows, %d states, years %d-%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code),
            min(d_raw$year), max(d_raw$year)))

# ---- Definitions -------------------------------------------------------------

ALL_SHOCKS <- c(
  mp_shock_di = "DI Surprise",
  eps_rr      = "eps_rr (OLS)"
)

DIRECTIONS <- list(
  full = list(label = "Full (Signed)",  fn = function(x) x,               prefix = "mp"),
  con  = list(label = "Contractionary", fn = function(x) pmax(x, 0),      prefix = "mp_pos"),
  exp  = list(label = "Expansionary",   fn = function(x) abs(pmin(x, 0)), prefix = "mp_neg")
)

HTM_TYPES <- list(
  ph2m = list(label = "PH2M", share = "lag1_share_ph2m"),
  wh2m = list(label = "WH2M", share = "lag1_share_wh2m")
)

CTRL_LAGGED <- c("lag1_share_ph2m", "lag1_share_wh2m",
                 "log_real_imports", "log_real_exports",
                 "infl_yoy", "log_bf", "log_credit_pf",
                 "lag1_lc")

CTRL_DUMMIES <- c("dummy_2015", "dummy_2016", "dummy_2020")

# ---- Helpers -----------------------------------------------------------------

extract_series <- function(res_obj, shock_col, shock_label, dir_label, htm_label,
                           shock_sd, term_name, spec_tag = "log") {
  irf_mean <- as.numeric(res_obj$irf_panel_mean[1, ])
  irf_low  <- as.numeric(res_obj$irf_panel_low[1, ])
  irf_up   <- as.numeric(res_obj$irf_panel_up[1, ])
  nobs_h   <- map_dbl(res_obj$reg_outputs,
                      ~ as.numeric(tryCatch(stats::nobs(.x), error = function(e) NA_real_)))
  if (length(irf_mean) != LP_HOR)
    stop(sprintf("Unexpected horizon length for %s", term_name))
  tibble(
    horizon       = 0:MAX_HORIZON,
    shock_col     = shock_col,
    shock_label   = shock_label,
    direction     = dir_label,
    htm_type      = htm_label,
    term          = term_name,
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
    spec          = spec_tag
  )
}

irf_theme <- function() {
  theme_bw(base_size = 11) +
    theme(
      panel.grid.minor       = element_blank(),
      panel.grid.major       = element_line(color = "gray92", linewidth = 0.3),
      strip.background       = element_blank(),
      strip.text             = element_text(size = 10, face = "bold"),
      legend.position        = "bottom",
      legend.background      = element_rect(fill = alpha("white", 0.85), color = NA),
      legend.title           = element_blank(),
      legend.text            = element_text(size = 9),
      axis.title             = element_text(size = 10),
      plot.title             = element_text(size = 11, hjust = 0.5),
      plot.subtitle          = element_text(size = 8.5, hjust = 0.5, color = "gray40")
    )
}

SHOCK_COLOURS <- c(
  mp_shock_di = "#333333",
  eps_rr      = "#1f77b4"
)

SPEC_COLOURS <- c("log(consumption)" = "#1f77b4", "% dev HP trend" = "#d62728")

# ---- Wild cluster bootstrap --------------------------------------------------

MetalBootstrapRunner <- R6Class(
  "MetalBootstrapRunner",
  public = list(
    n_boot = NULL,
    batch_size = NULL,
    device = NULL,
    tensor_dtype = NULL,
    initialize = function(n_boot, batch_size) {
      self$n_boot <- as.integer(n_boot)
      self$batch_size <- as.integer(batch_size)
      self$device <- torch_device("mps")
      self$tensor_dtype <- torch_float32()
      x <- torch_randn(c(2, 2), device = self$device)
      invisible(x$to(device = "cpu"))
    },
    run_bootstrap = function(input, shock_var, ctrl_all, outcome_col = "log_consumption") {
      states <- unique(input$uf_code)
      results <- vector("list", LP_HOR)
      shock_bt <- paste0("`", shock_var, "`")
      alpha <- (1 - CI_LEVEL / 100) / 2
      for (h in 0:MAX_HORIZON) {
        df_h <- input |>
          group_by(uf_code) |>
          mutate(y_h = .data[[outcome_col]] - lag(.data[[outcome_col]], h)) |>
          ungroup() |>
          filter(!is.na(y_h)) |>
          mutate(time_fe = factor(ym_id))
        rhs <- paste(c(shock_bt, ctrl_all, "time_fe"), collapse = " + ")
        fml <- as.formula(paste("y_h ~", rhs))
        df_dm <- df_h |>
          group_by(uf_code) |>
          mutate(across(c(y_h, all_of(c(shock_var, ctrl_all))),
                        ~ . - mean(., na.rm = TRUE))) |>
          ungroup()
        fit <- tryCatch(lm(fml, data = df_dm), error = function(e) NULL)
        if (is.null(fit)) {
          results[[h + 1]] <- tibble(horizon = h, boot_low = NA_real_, boot_high = NA_real_)
          next
        }
        X <- model.matrix(fml, data = df_dm)
        coef_names <- colnames(X)
        shock_idx <- which(coef_names == shock_var)
        if (length(shock_idx) == 0) {
          results[[h + 1]] <- tibble(horizon = h, boot_low = NA_real_, boot_high = NA_real_)
          next
        }
        fitted_vals <- as.numeric(fitted(fit))
        resid_vals <- as.numeric(residuals(fit))
        df_dm$state_idx <- as.integer(factor(df_dm$uf_code, levels = states))
        state_idx <- df_dm$state_idx
        X_t <- torch_tensor(X, dtype = self$tensor_dtype, device = self$device)
        XtX_t <- torch_matmul(X_t$transpose(1, 2), X_t)
        eye_t <- torch_eye(X_t$size(2), dtype = self$tensor_dtype, device = self$device)
        XtX_inv_t <- linalg_inv(XtX_t + 1e-8 * eye_t)
        Xtr_t <- torch_tensor(resid_vals, dtype = self$tensor_dtype, device = self$device)$unsqueeze(2)
        Xtf_t <- torch_tensor(fitted_vals, dtype = self$tensor_dtype, device = self$device)$unsqueeze(2)
        beta_boot <- numeric(0)
        chunks <- ceiling(self$n_boot / self$batch_size)
        for (chunk_id in seq_len(chunks)) {
          start_idx <- (chunk_id - 1L) * self$batch_size + 1L
          end_idx <- min(chunk_id * self$batch_size, self$n_boot)
          n_chunk <- end_idx - start_idx + 1L
          sign_states <- matrix(sample(c(-1, 1), n_chunk * length(states), replace = TRUE),
                                nrow = n_chunk, ncol = length(states))
          sign_obs <- sign_states[, state_idx, drop = FALSE]
          sign_t <- torch_tensor(sign_obs, dtype = self$tensor_dtype, device = self$device)
          y_wc_t <- Xtf_t$transpose(1, 2)$expand(c(n_chunk, -1)) + sign_t * Xtr_t$transpose(1, 2)$expand(c(n_chunk, -1))
          y_wc_t <- y_wc_t$unsqueeze(3)
          Xt_batch_t <- X_t$unsqueeze(1)$expand(c(n_chunk, -1, -1))$transpose(2, 3)
          Xt_y_t <- torch_matmul(Xt_batch_t, y_wc_t)
          inv_batch_t <- XtX_inv_t$unsqueeze(1)$expand(c(n_chunk, -1, -1))
          beta_t <- torch_matmul(inv_batch_t, Xt_y_t)$squeeze(3)
          beta_vec <- as.numeric(beta_t[, shock_idx]$to(device = "cpu"))
          beta_boot <- c(beta_boot, beta_vec)
        }
        beta_boot <- beta_boot[is.finite(beta_boot)]
        if (length(beta_boot) < 10) {
          results[[h + 1]] <- tibble(horizon = h, boot_low = NA_real_, boot_high = NA_real_)
          next
        }
        results[[h + 1]] <- tibble(
          horizon = h,
          boot_low = as.numeric(quantile(beta_boot, alpha)),
          boot_high = as.numeric(quantile(beta_boot, 1 - alpha))
        )
      }
      bind_rows(results)
    }
  )
)

# ---- Panel builders ----------------------------------------------------------

build_panel_base <- function(shock_col, outcome_var = "log") {
  base <- d_raw |>
    mutate(mp_shock = .data[[shock_col]]) |>
    arrange(uf_code, year, month_num) |>
    group_by(uf_code) |>
    mutate(
      log_consumption  = log(consumption_index),
      log_real_imports = log(coalesce(vl_imports / ipca_index, 0) + 1),
      log_real_exports = log(coalesce(vl_exports / ipca_index, 0) + 1),
      log_bf           = log(coalesce(total_value_BF_old, 0) + 1),
      infl_mom         = log(ipca_index) - log(lag(ipca_index, 1)),
      infl_yoy_raw     = log(ipca_index) - log(lag(ipca_index, 12)),
      infl_yoy         = coalesce(infl_yoy_raw, infl_mom * 12),
      ym_id            = year * 100L + month_num
    ) |>
    ungroup()

  if (outcome_var == "hp") {
    base <- base |>
      group_by(uf_code) |>
      mutate(
        hp_trend   = {
          x <- consumption_index
          if (sum(!is.na(x)) > 2) {
            tryCatch(
              as.numeric(mFilter::hpfilter(x[!is.na(x)], freq = HP_LAMBDA,
                                           type = "lambda")$trend),
              error = function(e) rep(NA_real_, sum(!is.na(x)))
            )
          } else rep(NA_real_, length(x))
        },
        pct_dev_hp = (consumption_index - hp_trend) / hp_trend * 100,
        lag1_lc    = lag(pct_dev_hp)
      ) |>
      ungroup()
  } else {
    base <- base |>
      group_by(uf_code) |>
      mutate(lag1_lc = lag(log_consumption)) |>
      ungroup()
  }
  base
}

build_input <- function(panel_base, dir_def, outcome_col) {
  ph2m_term <- paste0(dir_def$prefix, "_x_ph2m")
  wh2m_term <- paste0(dir_def$prefix, "_x_wh2m")
  panel_dir <- panel_base |>
    mutate(
      shock_d      = dir_def$fn(mp_shock),
      !!ph2m_term := shock_d * lag1_share_ph2m,
      !!wh2m_term := shock_d * lag1_share_wh2m
    )
  all_cols <- c("uf_code", "ym_id", outcome_col,
                ph2m_term, wh2m_term, CTRL_LAGGED, CTRL_DUMMIES)
  list(
    input     = panel_dir |> filter(!if_any(all_of(all_cols), is.na)) |>
                             select(all_of(all_cols)),
    ph2m_term = ph2m_term,
    wh2m_term = wh2m_term
  )
}

bootstrap_runner <- MetalBootstrapRunner$new(
  n_boot = N_BOOT,
  batch_size = RUNTIME$batch_size
)

# ---- LP + bootstrap block ----------------------------------------------------
# Runs main LP, saves CSVs, then runs bootstrap and saves overlaid plots

run_lp_block <- function(outcome_col, spec_tag, out_tbl, out_plt, label_suffix,
                         run_boot = FALSE) {
  results      <- list()
  boot_results <- list()

  for (shock_col in names(ALL_SHOCKS)) {
    shock_label <- ALL_SHOCKS[[shock_col]]
    cat(sprintf("\n  Shock: %s\n", shock_label))
    panel_base <- build_panel_base(shock_col, outcome_var = spec_tag)

    for (dir_name in names(DIRECTIONS)) {
      dir_def   <- DIRECTIONS[[dir_name]]
      dir_label <- dir_def$label
      built     <- build_input(panel_base, dir_def, outcome_col)
      input     <- built$input

      cat(sprintf("  [%s | %s]  n = %d rows\n", shock_label, dir_label, nrow(input)))

      for (htm_name in names(HTM_TYPES)) {
        htm_label   <- HTM_TYPES[[htm_name]]$label
        shock_var   <- if (htm_name == "ph2m") built$ph2m_term else built$wh2m_term
        contemp_htm <- if (htm_name == "ph2m") built$wh2m_term else built$ph2m_term
        contemp_all <- c(contemp_htm, CTRL_DUMMIES)
        shock_sd    <- stats::sd(input[[shock_var]], na.rm = TRUE)
        key         <- paste(shock_col, dir_name, htm_name, sep = "_")

        cat(sprintf("    -> LP [%s]: %s  (sd = %.5f)\n", spec_tag, shock_var, shock_sd))

        # Main LP
        res <- lpirfs::lp_lin_panel(
          data_set       = input,
          endog_data     = outcome_col,
          cumul_mult     = TRUE,
          shock          = shock_var,
          diff_shock     = FALSE,
          panel_model    = "within",
          panel_effect   = "twoways",
          robust_cov     = "vcovSCC",
          robust_type    = "HC1",
          robust_maxlag  = 6,
          c_exog_data    = contemp_all,
          l_exog_data    = CTRL_LAGGED,
          lags_exog_data = 2,
          confint        = CI_MULT,
          hor            = LP_HOR
        )

        result <- extract_series(res, shock_col, shock_label, dir_label, htm_label,
                                 shock_sd, shock_var, spec_tag)
        results[[key]] <- result
        write_csv(result, file.path(out_tbl,
                  sprintf("irf_%s_%s_%s_%s.csv", spec_tag, shock_col, dir_name, htm_name)))

        # Bootstrap
        if (run_boot) {
          cat(sprintf("      -> Bootstrap (B=%d)...\n", N_BOOT))
          boot_ci <- bootstrap_runner$run_bootstrap(
            input, shock_var, c(contemp_all, CTRL_LAGGED),
            outcome_col = outcome_col
          ) |>
            mutate(
              shock_col     = shock_col,
              direction     = dir_label,
              htm_type      = htm_label,
              shock_var     = shock_var,
              boot_low_1sd  = boot_low  * shock_sd,
              boot_high_1sd = boot_high * shock_sd
            )
          boot_results[[key]] <- boot_ci
          write_csv(boot_ci, file.path(out_tbl,
                    sprintf("boot_%s_%s_%s_%s.csv", spec_tag, shock_col, dir_name, htm_name)))

          # Plot: DK + boot CI overlaid
          plot_data <- result |>
            left_join(boot_ci |> select(horizon, boot_low_1sd, boot_high_1sd),
                      by = "horizon")

          p <- ggplot(plot_data, aes(x = horizon)) +
            geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
            geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
                        alpha = 0.18, fill = "#1f77b4", color = NA) +
            geom_ribbon(aes(ymin = boot_low_1sd, ymax = boot_high_1sd),
                        fill = NA, color = "#d62728", linewidth = 0.6, linetype = "dashed") +
            geom_line(aes(y = estimate_1sd), linewidth = 0.9, color = "#1f77b4") +
            scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
            labs(
              title    = sprintf("LP [%s] - %s | %s | %s",
                                 label_suffix, shock_label, dir_label, htm_label),
              subtitle = sprintf("Blue = DK 90%% CI | Red = Wild Cluster Boot 90%% CI | SD=%.5f",
                                 shock_sd),
              x = "Horizon (months)",
              y = sprintf("Cumulative response (1-SD) [%s]", label_suffix)
            ) + irf_theme()

          ggsave(file.path(out_plt,
                 sprintf("irf_%s_%s_%s_%s.png", spec_tag, shock_col, dir_name, htm_name)),
                 p, width = 8, height = 4.5, dpi = 300)
          cat(sprintf("      saved irf_%s_%s_%s_%s.png\n", spec_tag, shock_col, dir_name, htm_name))

        } else {
          # No bootstrap — plain DK plot
          p <- ggplot(result, aes(x = horizon, y = estimate_1sd)) +
            geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
            geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
                        alpha = 0.18, fill = "#1f77b4", color = NA) +
            geom_line(linewidth = 0.9, color = "#1f77b4") +
            scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
            labs(
              title    = sprintf("LP [%s] - %s | %s | %s",
                                 label_suffix, shock_label, dir_label, htm_label),
              subtitle = sprintf("DK 90%% CI | 2 lags | 1-SD shock (SD=%.5f)", shock_sd),
              x = "Horizon (months)",
              y = sprintf("Cumulative response (1-SD) [%s]", label_suffix)
            ) + irf_theme()

          ggsave(file.path(out_plt,
                 sprintf("irf_%s_%s_%s_%s.png", spec_tag, shock_col, dir_name, htm_name)),
                 p, width = 8, height = 4.5, dpi = 300)
        }
      }
    }
  }

  # Combined CSV
  combined <- bind_rows(results)
  write_csv(combined, file.path(out_tbl, sprintf("irf_%s_all.csv", spec_tag)))
  cat(sprintf("\n  Combined [%s]: %d rows saved\n", spec_tag, nrow(combined)))

  # Per-shock 6-panel plots
  plot_df <- combined |>
    mutate(
      shock_col = factor(shock_col, levels = names(ALL_SHOCKS)),
      direction = factor(direction, levels = c("Full (Signed)", "Contractionary", "Expansionary")),
      htm_type  = factor(htm_type,  levels = c("PH2M", "WH2M"))
    )

  for (sc in names(ALL_SHOCKS)) {
    sl <- ALL_SHOCKS[[sc]]
    p <- plot_df |>
      filter(shock_col == sc) |>
      ggplot(aes(x = horizon, y = estimate_1sd)) +
      geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
      geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
                  alpha = 0.18, fill = "#1f77b4", color = NA) +
      geom_line(linewidth = 0.9, color = "#1f77b4") +
      facet_grid(htm_type ~ direction, scales = "free_y") +
      scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
      labs(
        title    = sprintf("LP IRFs [%s] - %s (TWFE)", label_suffix, sl),
        subtitle = sprintf("state+time FE | DK 90%% CI | 2 lags | 1-SD shock"),
        x = "Horizon (months)",
        y = sprintf("Cumulative response (1-SD) [%s]", label_suffix)
      ) + irf_theme()
    ggsave(file.path(out_plt, sprintf("irf_%s_%s_6panel.png", spec_tag, sc)),
           p, width = 12, height = 7, dpi = 300)
    cat(sprintf("  saved irf_%s_%s_6panel.png\n", spec_tag, sc))
  }

  # All-shocks 6-panel
  p_all <- plot_df |>
    ggplot(aes(x = horizon, y = estimate_1sd, color = shock_col, fill = shock_col)) +
    geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.10, color = NA) +
    geom_line(linewidth = 0.85) +
    facet_grid(htm_type ~ direction, scales = "free_y") +
    scale_color_manual(values = SHOCK_COLOURS, labels = ALL_SHOCKS) +
    scale_fill_manual( values = SHOCK_COLOURS, labels = ALL_SHOCKS) +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
    labs(
      title    = sprintf("LP IRFs [%s] - All Shocks (TWFE)", label_suffix),
      subtitle = "state+time FE | DK 90% CI | 2 lags | 1-SD shock",
      x = "Horizon (months)",
      y = sprintf("Cumulative response (1-SD) [%s]", label_suffix)
    ) + irf_theme()
  ggsave(file.path(out_plt, sprintf("irf_%s_all_shocks_6panel.png", spec_tag)),
         p_all, width = 12, height = 7, dpi = 300)
  cat(sprintf("  saved irf_%s_all_shocks_6panel.png\n", spec_tag))

  invisible(combined)
}

DiagnosticsOrchestrator <- R6Class(
  "DiagnosticsOrchestrator",
  public = list(
    run_log_lp = function() {
      run_lp_block(
        outcome_col  = "log_consumption",
        spec_tag     = "log",
        out_tbl      = OUT_TBL,
        out_plt      = OUT_PLT,
        label_suffix = "log(consumption)",
        run_boot     = TRUE
      )
    },
    run_hp_lp = function() {
      run_lp_block(
        outcome_col  = "pct_dev_hp",
        spec_tag     = "hp",
        out_tbl      = OUT_TBL_HP,
        out_plt      = OUT_PLT_HP,
        label_suffix = "% dev from HP trend",
        run_boot     = FALSE
      )
    }
  )
)

# ==============================================================================
# STEP 1 - PRE-ESTIMATION TESTS
# ==============================================================================

cat("\n\n=== STEP 1: PRE-ESTIMATION TESTS ===\n")

diag_panel <- d_raw |>
  arrange(uf_code, year, month_num) |>
  group_by(uf_code) |>
  mutate(
    log_consumption = log(consumption_index),
    ym_id           = year * 100L + month_num
  ) |>
  ungroup()

# 1a. Stationarity: IPS on log(consumption_index)
# Note: unit root in levels is expected and not a problem — the LP outcome is
# cumulative log differences (stationary). This test is reported for completeness.
cat("\n--- Stationarity: IPS on log(consumption_index) ---\n")
cat("    H0: all panels have a unit root\n")
cat("    Note: LP uses cumulative log differences so I(1) in levels is not a concern\n\n")

pdata <- pdata.frame(
  diag_panel |> select(uf_code, ym_id, log_consumption),
  index = c("uf_code", "ym_id")
)

ips_result <- tryCatch(
  purtest(log_consumption ~ 1, data = pdata, index = c("uf_code", "ym_id"),
          test = "ips", lags = 4, exo = "intercept"),
  error = function(e) { cat("  purtest error:", conditionMessage(e), "\n"); NULL }
)

if (!is.null(ips_result)) {
  print(summary(ips_result))
} else {
  cat("  Fallback: ADF per state\n")
  adf_pvals <- diag_panel |>
    group_by(uf_code) |>
    summarise(
      adf_p = tryCatch(
        tseries::adf.test(ts(log_consumption, frequency = 12),
                          alternative = "stationary")$p.value,
        error = function(e) NA_real_),
      .groups = "drop"
    )
  print(adf_pvals)
  cat(sprintf("\n  Median ADF p-value: %.4f\n", median(adf_pvals$adf_p, na.rm = TRUE)))
  cat(sprintf("  States rejecting H0 at 5%%: %d / %d\n",
              sum(adf_pvals$adf_p < 0.05, na.rm = TRUE), nrow(adf_pvals)))
  write_csv(adf_pvals, file.path(OUT_TBL, "stationarity_adf_per_state.csv"))
}

# 1b. Ljung-Box on mp_shock_di
cat("\n--- Ljung-Box: mp_shock_di ---\n")
cat("    H0: no autocorrelation in shock series\n\n")

di_series <- diag_panel |>
  distinct(ym_id, mp_shock_di) |>
  arrange(ym_id) |>
  pull(mp_shock_di) |>
  na.omit()

lb_results <- map_dfr(c(6, 12, 24), function(lag) {
  test <- Box.test(di_series, lag = lag, type = "Ljung-Box")
  tibble(lags = lag, statistic = round(test$statistic, 4), p_value = round(test$p.value, 4))
})

print(lb_results)
write_csv(lb_results, file.path(OUT_TBL, "ljung_box_mp_shock_di.csv"))

if (all(lb_results$p_value > 0.05)) {
  cat("\n  OK: No autocorrelation in mp_shock_di\n")
} else {
  cat("\n  WARNING: Autocorrelation detected in mp_shock_di\n")
}

# ==============================================================================
# STEP 2 - MAIN LP: log(consumption_index), with bootstrap
# ==============================================================================

cat("\n\n=== STEP 2: MAIN LP + BOOTSTRAP — outcome: log(consumption_index) ===\n")
cat(sprintf("    Bootstrap: B = %d | Set N_BOOT = 99 to test first\n\n", N_BOOT))

orchestrator <- DiagnosticsOrchestrator$new()
results_log <- orchestrator$run_log_lp()

# ==============================================================================
# STEP 3 - HP-FILTER LP: % deviation from HP trend, no bootstrap
# ==============================================================================

cat("\n\n=== STEP 3: HP-FILTER LP — outcome: % deviation from HP trend ===\n")
cat(sprintf("    HP lambda = %d (standard monthly)\n\n", HP_LAMBDA))

results_hp <- orchestrator$run_hp_lp()

# ==============================================================================
# STEP 4 - COMPARISON: log vs HP overlay plots
# ==============================================================================

cat("\n\n=== STEP 4: COMPARISON PLOTS ===\n")

comp_df <- bind_rows(
  results_log |> mutate(spec = "log(consumption)"),
  results_hp  |> mutate(spec = "% dev HP trend")
) |>
  mutate(
    shock_col = factor(shock_col, levels = names(ALL_SHOCKS)),
    direction = factor(direction, levels = c("Full (Signed)", "Contractionary", "Expansionary")),
    htm_type  = factor(htm_type,  levels = c("PH2M", "WH2M")),
    spec      = factor(spec, levels = c("log(consumption)", "% dev HP trend"))
  )

for (sc in names(ALL_SHOCKS)) {
  sl <- ALL_SHOCKS[[sc]]
  p <- comp_df |>
    filter(shock_col == sc) |>
    ggplot(aes(x = horizon, y = estimate_1sd, color = spec, fill = spec)) +
    geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd), alpha = 0.12, color = NA) +
    geom_line(linewidth = 0.85) +
    facet_grid(htm_type ~ direction, scales = "free_y") +
    scale_color_manual(values = SPEC_COLOURS) +
    scale_fill_manual( values = SPEC_COLOURS) +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
    labs(
      title    = sprintf("Log vs HP-Filter IRFs - %s (TWFE)", sl),
      subtitle = "Blue = log(consumption) | Red = % dev HP trend | DK 90% CI | 1-SD shock",
      x = "Horizon (months)", y = "Cumulative response (1-SD shock)"
    ) + irf_theme()
  fname <- sprintf("comparison_%s_6panel.png", sc)
  ggsave(file.path(OUT_PLT_CMP, fname), p, width = 12, height = 7, dpi = 300)
  cat(sprintf("  saved %s\n", fname))
}

write_csv(comp_df, file.path(OUT_TBL, "irf_comparison_log_vs_hp.csv"))

# ==============================================================================
# STEP 5 - LEAD TEST (eps_rr only)
# ==============================================================================

cat("\n\n=== STEP 5: LEAD TEST (Placebo) - eps_rr only ===\n")
cat("    H0: lead shock has no effect (IRF approx 0)\n\n")

lead_panel <- d_raw |>
  arrange(uf_code, year, month_num) |>
  group_by(uf_code) |>
  mutate(
    log_consumption  = log(consumption_index),
    log_real_imports = log(coalesce(vl_imports / ipca_index, 0) + 1),
    log_real_exports = log(coalesce(vl_exports / ipca_index, 0) + 1),
    log_bf           = log(coalesce(total_value_BF_old, 0) + 1),
    infl_mom         = log(ipca_index) - log(lag(ipca_index, 1)),
    infl_yoy_raw     = log(ipca_index) - log(lag(ipca_index, 12)),
    infl_yoy         = coalesce(infl_yoy_raw, infl_mom * 12),
    lag1_lc          = lag(log_consumption),
    ym_id            = year * 100L + month_num,
    eps_rr_lead1     = dplyr::lead(eps_rr, 1),
    lead_x_ph2m      = eps_rr_lead1 * lag1_share_ph2m,
    lead_x_wh2m      = eps_rr_lead1 * lag1_share_wh2m
  ) |>
  ungroup()

lead_cols <- c("uf_code", "ym_id", "log_consumption",
               "lead_x_ph2m", "lead_x_wh2m", CTRL_LAGGED, CTRL_DUMMIES)

lead_input <- lead_panel |>
  filter(!if_any(all_of(lead_cols), is.na)) |>
  select(all_of(lead_cols))

cat(sprintf("  Lead test sample: %d rows\n\n", nrow(lead_input)))

lead_results_list <- list()

for (htm_name in names(HTM_TYPES)) {
  htm_label   <- HTM_TYPES[[htm_name]]$label
  shock_var   <- if (htm_name == "ph2m") "lead_x_ph2m" else "lead_x_wh2m"
  contemp_htm <- if (htm_name == "ph2m") "lead_x_wh2m" else "lead_x_ph2m"
  contemp_all <- c(contemp_htm, CTRL_DUMMIES)
  shock_sd    <- sd(lead_input[[shock_var]], na.rm = TRUE)

  cat(sprintf("  -> Lead LP: %s  (sd = %.5f)\n", shock_var, shock_sd))

  res_lead <- lpirfs::lp_lin_panel(
    data_set       = lead_input,
    endog_data     = "log_consumption",
    cumul_mult     = TRUE,
    shock          = shock_var,
    diff_shock     = FALSE,
    panel_model    = "within",
    panel_effect   = "twoways",
    robust_cov     = "vcovSCC",
    robust_type    = "HC1",
    robust_maxlag  = 6,
    c_exog_data    = contemp_all,
    l_exog_data    = CTRL_LAGGED,
    lags_exog_data = 2,
    confint        = CI_MULT,
    hor            = LP_HOR
  )

  lead_irf <- extract_series(res_lead, "eps_rr_lead1", "eps_rr Lead +1",
                             "Full (Signed)", htm_label, shock_sd, shock_var)
  lead_results_list[[htm_name]] <- lead_irf
}

lead_irf_all <- bind_rows(lead_results_list)
write_csv(lead_irf_all, file.path(OUT_TBL, "lead_test_eps_rr.csv"))

lead_h0 <- lead_irf_all |>
  filter(horizon == 0) |>
  select(htm_type, estimate_1sd, ci_low_1sd, ci_high_1sd)

cat("\n  Lead test IRF at h=0:\n")
print(lead_h0)

crosses_zero <- lead_h0 |>
  mutate(crosses = ci_low_1sd <= 0 & ci_high_1sd >= 0) |>
  pull(crosses)

if (all(crosses_zero)) {
  cat("\n  OK: Lead placebo passes at h=0\n")
} else {
  cat("\n  WARNING: Lead placebo fails at h=0 - check identification\n")
}

p_lead <- lead_irf_all |>
  mutate(htm_type = factor(htm_type, levels = c("PH2M", "WH2M"))) |>
  ggplot(aes(x = horizon, y = estimate_1sd)) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
              alpha = 0.18, fill = "#d62728", color = NA) +
  geom_line(linewidth = 0.9, color = "#d62728") +
  facet_wrap(~htm_type) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "Lead Test (Placebo) - eps_rr Lead +1",
    subtitle = "IRF should be approx 0 if eps_rr is exogenous | DK 90% CI",
    x = "Horizon (months)", y = "Cumulative log consumption response (1-SD)"
  ) + irf_theme()

ggsave(file.path(OUT_PLT, "lead_test_eps_rr.png"), p_lead, width = 10, height = 5, dpi = 300)
cat("  saved lead_test_eps_rr.png\n")

# ---- Final summary -----------------------------------------------------------
cat("\n=== DONE ===\n")
cat(sprintf("  Tables (log)    : %s/\n", OUT_TBL))
cat(sprintf("  Tables (HP)     : %s/\n", OUT_TBL_HP))
cat(sprintf("  Plots  (log)    : %s/\n", OUT_PLT))
cat(sprintf("  Plots  (HP)     : %s/\n", OUT_PLT_HP))
cat(sprintf("  Plots  (compare): %s/\n", OUT_PLT_CMP))
cat("\n  Outputs by step:\n")
cat("  [1] stationarity_adf_per_state.csv | ljung_box_mp_shock_di.csv\n")
cat("  [2] irf_log_*.csv | boot_log_*.csv | *_6panel.png (DK + boot overlaid)\n")
cat("  [3] irf_hp_*.csv  | *_6panel.png\n")
cat("  [4] comparison_*_6panel.png | irf_comparison_log_vs_hp.csv\n")
cat("  [5] lead_test_eps_rr.csv | lead_test_eps_rr.png\n")
