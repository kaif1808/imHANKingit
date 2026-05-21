#!/usr/bin/env Rscript
# Multi-shock version of celina_lp_income.r
# Loops over 4 MP shock series; saves per-shock CSVs/PNGs + combined comparison outputs.
# Spec: lag1_tfe, pairs cluster bootstrap (B=499), directional (con/exp), MAX_HORIZON=24.
# Note: most compute-intensive script — shocks run sequentially.

library(tidyverse)
library(sandwich)
library(parallel)

set.seed(42)
N_CORES_RAW <- suppressWarnings(detectCores())
N_CORES     <- if (is.na(N_CORES_RAW)) 1L else max(1L, N_CORES_RAW - 1L)
B_BOOT      <- 499L
MAX_HORIZON <- 24L
CI_LEVEL    <- 90
CI_MULT     <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)

OUT_TBL <- "results/tables/lp_income/multishock"
OUT_PLT <- "results/plots/lp_income/multishock"
dir.create(OUT_TBL, showWarnings = FALSE, recursive = TRUE)
dir.create(OUT_PLT, showWarnings = FALSE, recursive = TRUE)

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

cat(sprintf("\n=== LP INCOME MULTI-SHOCK (lag1_tfe · B=%d · %d cores) ===\n\n",
            B_BOOT, N_CORES))

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

# ── Bootstrap helpers (identical to single-shock version) ─────────────────────

one_boot_rep <- function(seed, d, fml, params) {
  set.seed(seed)
  clusters <- unique(d$uf_code)
  sampled  <- sample(clusters, length(clusters), replace = TRUE)
  boot_d   <- do.call(rbind, lapply(seq_along(sampled), function(i) {
    sub <- d[d$uf_code == sampled[i], ]
    sub$uf_code <- i
    sub
  }))
  tryCatch({
    mb  <- lm(fml, data = boot_d)
    cf  <- coef(mb)
    sapply(params, function(p) {
      idx <- grep(paste0("^", p, "$"), names(cf), perl = TRUE)[1]
      if (is.na(idx)) NA_real_ else as.numeric(cf[idx])
    })
  }, error = function(e) rep(NA_real_, length(params)))
}

boot_ci <- function(d, fml, params, B = B_BOOT, alpha = 1 - CI_LEVEL / 100) {
  seeds <- sample.int(.Machine$integer.max, B)
  reps  <- mclapply(seeds, one_boot_rep, d = d, fml = fml, params = params,
                    mc.cores = N_CORES)
  mat   <- do.call(rbind, reps)
  lo    <- apply(mat, 2, quantile, alpha / 2,       na.rm = TRUE)
  hi    <- apply(mat, 2, quantile, 1 - alpha / 2,   na.rm = TRUE)
  list(lo = lo, hi = hi)
}

get_coef_vc <- function(m, vc, term) {
  cn  <- rownames(vc); cf <- coef(m)
  idx <- grep(paste0("^", term, "$"), cn, perl = TRUE)[1]
  if (is.na(idx)) return(c(b = NA_real_, se = NA_real_))
  c(b = as.numeric(cf[cn[idx]]), se = sqrt(as.numeric(vc[idx, idx])))
}

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
      plot.title             = element_text(size = 12, hjust = 0.5),
      plot.subtitle          = element_text(size = 9, hjust = 0.5, color = "gray40")
    )
}

DIRECTIONS <- c("con", "exp")
RTYPES     <- c("cumulative")

all_shock_results <- list()
t_start <- proc.time()

for (shock_var in names(SHOCKS)) {
  shock_label <- SHOCKS[[shock_var]]
  cat(sprintf("\n── Shock: %s (%s) ──\n", shock_var, shock_label))

  panel <- d_raw |>
    arrange(uf_code, year, month_num) |>
    group_by(uf_code) |>
    mutate(
      log_income_sa    = log(mean_income_sa),
      log_imports      = log(coalesce(vl_imports, 0)         + 1),
      log_exports      = log(coalesce(vl_exports, 0)         + 1),
      log_bf           = log(coalesce(total_value_BF_old, 0) + 1),
      infl_mom         = log(ipca_index) - log(lag(ipca_index, 1)),
      infl_yoy_raw     = log(ipca_index) - log(lag(ipca_index, 12)),
      infl_yoy         = coalesce(infl_yoy_raw, infl_mom * 12),
      lag1_li          = lag(log_income_sa),
      mp_shock_pos     = pmax(.data[[shock_var]], 0),
      mp_shock_neg_abs = abs(pmin(.data[[shock_var]], 0)),
      mp_pos_x_ph2m    = mp_shock_pos     * lag1_share_ph2m,
      mp_pos_x_wh2m    = mp_shock_pos     * lag1_share_wh2m,
      mp_neg_x_ph2m    = mp_shock_neg_abs * lag1_share_ph2m,
      mp_neg_x_wh2m    = mp_shock_neg_abs * lag1_share_wh2m,
      ym               = year * 100L + month_num
    ) |>
    ungroup()

  CTRL_BASE <- c("lag1_share_ph2m", "lag1_share_wh2m",
                 "log_imports", "log_exports", "infl_yoy", "log_bf")
  if (sum(!is.na(panel$log_credit_pf)) > 10)
    CTRL_BASE <- c(CTRL_BASE, "log_credit_pf")
  ctrl_str <- paste(CTRL_BASE, collapse = " + ")

  cat(sprintf("  mp_shock non-zero: %d / %d obs\n",
              sum(panel[[shock_var]] != 0, na.rm = TRUE),
              sum(!is.na(panel[[shock_var]]))))

  shock_results <- list()

  for (direction in DIRECTIONS) {
    for (rtype in RTYPES) {

      x_ph2m  <- if (direction == "con") "mp_pos_x_ph2m" else "mp_neg_x_ph2m"
      x_wh2m  <- if (direction == "con") "mp_pos_x_wh2m" else "mp_neg_x_wh2m"
      fml_str <- paste("y_resp ~", x_ph2m, "+", x_wh2m, "+",
                       ctrl_str, "+ lag1_li + factor(uf_code) + factor(ym)")

      cat(sprintf("  %s | %s | lag1_tfe  [B=%d]\n", direction, rtype, B_BOOT))

      rows_h <- vector("list", MAX_HORIZON + 1)

      for (h in 0:MAX_HORIZON) {
        d <- panel |>
          filter(!is.na(lag1_li), !is.na(.data[[shock_var]]), !is.na(log_income_sa)) |>
          arrange(uf_code, year, month_num) |>
          group_by(uf_code) |>
          mutate(y_resp = lead(log_income_sa, h) - lag1_li) |>
          ungroup() |>
          filter(!is.na(y_resp))

        fml         <- as.formula(fml_str)
        m           <- lm(fml, data = d)
        vc          <- sandwich::vcovCL(m, cluster = d$uf_code, type = "HC1")
        b_ph2m      <- get_coef_vc(m, vc, x_ph2m)
        b_wh2m      <- get_coef_vc(m, vc, x_wh2m)
        ci          <- boot_ci(d, fml, params = c(x_ph2m, x_wh2m))

        rows_h[[h + 1]] <- tibble(
          horizon       = h,
          b_mp_x_ph2m   = b_ph2m[["b"]],
          se_mp_x_ph2m  = b_ph2m[["se"]],
          ci_lo_ph2m    = ci$lo[[x_ph2m]],
          ci_hi_ph2m    = ci$hi[[x_ph2m]],
          b_mp_x_wh2m   = b_wh2m[["b"]],
          se_mp_x_wh2m  = b_wh2m[["se"]],
          ci_lo_wh2m    = ci$lo[[x_wh2m]],
          ci_hi_wh2m    = ci$hi[[x_wh2m]],
          nobs          = nrow(d),
          response_type = rtype,
          spec          = "lag1_tfe",
          shock_type    = if (direction == "con") "contractionary" else "expansionary",
          shock_series  = shock_label,
          shock_var     = shock_var
        )

        if (h %% 8 == 0)
          cat(sprintf("    h=%02d  n=%d  PH2M=%+.4f [%+.4f, %+.4f]  WH2M=%+.4f [%+.4f, %+.4f]\n",
                      h, nrow(d),
                      b_ph2m[["b"]], ci$lo[[x_ph2m]], ci$hi[[x_ph2m]],
                      b_wh2m[["b"]], ci$lo[[x_wh2m]], ci$hi[[x_wh2m]]))
      }

      key    <- paste(shock_var, direction, rtype, "lag1_tfe", sep = "_")
      result <- bind_rows(rows_h)
      shock_results[[key]] <- result

      fname <- sprintf("irf_income_%s_%s_%s_lag1_tfe.csv", shock_var, direction, rtype)
      write_csv(result, file.path(OUT_TBL, fname))
      cat(sprintf("    ✓ saved %s\n", fname))
    }
  }

  # Per-shock plots (PH2M | WH2M, one per direction×rtype)
  TYPE_COLS <- c(PH2M = "#2166ac", WH2M = "#d6604d")

  for (direction in DIRECTIONS) {
    slabel <- if (direction == "con") "Contractionary (Rate Hikes)" else "Expansionary (Rate Cuts)"
    for (rtype in RTYPES) {
      ytitle <- "Cumulative log income response"
      key    <- paste(shock_var, direction, rtype, "lag1_tfe", sep = "_")

      plot_df <- shock_results[[key]] |>
        pivot_longer(
          cols      = c(b_mp_x_ph2m, b_mp_x_wh2m),
          names_to  = "type_raw", values_to = "estimate"
        ) |>
        mutate(
          type  = if_else(type_raw == "b_mp_x_ph2m", "PH2M", "WH2M"),
          ci_lo = if_else(type_raw == "b_mp_x_ph2m", ci_lo_ph2m, ci_lo_wh2m),
          ci_hi = if_else(type_raw == "b_mp_x_ph2m", ci_hi_ph2m, ci_hi_wh2m),
          type  = factor(type, levels = c("PH2M", "WH2M"))
        )

      p <- ggplot(plot_df, aes(x = horizon, y = estimate, colour = type, fill = type)) +
        geom_hline(yintercept = 0, linewidth = 0.5) +
        geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.15, colour = NA) +
        geom_line(linewidth = 0.9) +
        facet_wrap(~type, nrow = 1, scales = "free_y",
                   labeller = labeller(type = c(
                     PH2M = "PH2M exposure x MP shock",
                     WH2M = "WH2M exposure x MP shock"
                   ))) +
        scale_colour_manual(values = TYPE_COLS, guide = "none") +
        scale_fill_manual(  values = TYPE_COLS, guide = "none") +
        scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
        labs(
          title    = sprintf("Income LP IRFs — %s — %s (%s)", slabel, shock_label, shock_var),
          subtitle = sprintf("Response: log(mean_income_sa) · lag1_tfe · %d%% bootstrap CI (B=%d)",
                             CI_LEVEL, B_BOOT),
          x = "Horizon (months)", y = ytitle
        ) + irf_theme()

      fname_png <- sprintf("irf_income_%s_%s_%s_preferred.png",
                           shock_var, direction, rtype)
      ggsave(file.path(OUT_PLT, fname_png), p, width = 10, height = 4.5, dpi = 300)
      cat(sprintf("  ✓ Plot: %s\n", fname_png))
    }
  }

  all_shock_results[[shock_var]] <- bind_rows(shock_results)
}

elapsed <- round((proc.time() - t_start)[3] / 60, 1)
cat(sprintf("\n✓ All shocks complete (%s min)\n\n", elapsed))

# ── Combined comparison ────────────────────────────────────────────────────────

combined_df <- bind_rows(all_shock_results)
write_csv(combined_df, file.path(OUT_TBL, "irf_income_all_shocks_comparison.csv"))
cat(sprintf("✓ Saved combined table: irf_income_all_shocks_comparison.csv\n"))

# 4-panel comparison: con_cumulative | exp_cumulative, PH2M and WH2M sub-series
comp_long <- combined_df |>
  pivot_longer(
    cols      = c(b_mp_x_ph2m, b_mp_x_wh2m),
    names_to  = "type_raw", values_to = "estimate"
  ) |>
  mutate(
    type  = if_else(type_raw == "b_mp_x_ph2m", "PH2M", "WH2M"),
    ci_lo = if_else(type_raw == "b_mp_x_ph2m", ci_lo_ph2m, ci_lo_wh2m),
    ci_hi = if_else(type_raw == "b_mp_x_ph2m", ci_hi_ph2m, ci_hi_wh2m),
    panel_label = paste0(shock_type, " | ", response_type, " | ", type)
  )

p_comp <- ggplot(comp_long,
                 aes(x = horizon, y = estimate,
                     color = shock_series, fill = shock_series)) +
  geom_hline(yintercept = 0, linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.08, color = NA) +
  geom_line(linewidth = 0.7) +
  facet_wrap(~panel_label, scales = "free_y", ncol = 4) +
  scale_color_manual(values = SHOCK_COLORS) +
  scale_fill_manual(values  = SHOCK_COLORS) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "Income LP IRFs — All Shock Series Comparison (lag1_tfe, bootstrap CI)",
    subtitle = sprintf("%d%% bootstrap CI (B=%d); PH2M and WH2M sub-series", CI_LEVEL, B_BOOT),
    x        = "Horizon (months)", y = "Log income response",
    color    = "Shock series", fill = "Shock series"
  ) +
  theme_bw(base_size = 10) +
  theme(
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = "gray92", linewidth = 0.3),
    legend.position  = "bottom",
    strip.background = element_blank(),
    strip.text       = element_text(size = 8)
  )

ggsave(file.path(OUT_PLT, "irf_income_all_shocks_comparison.png"),
       p_comp, width = 16, height = 8, dpi = 300)
cat("✓ Saved comparison plot: irf_income_all_shocks_comparison.png\n")

cat(sprintf("\n=== LP INCOME MULTI-SHOCK COMPLETE ===\n  Tables: %s/\n  Plots:  %s/\n",
            OUT_TBL, OUT_PLT))
