#!/usr/bin/env Rscript
# Smooth LP Diagnostics — Whittaker-Henderson second-difference smoother
#
# Applies the Barnichon-Brownlees (2019) style second-difference penalty to
# the horizon-by-horizon IRF estimates from the main TWFE LP runs.
# Lambda (smoothing strength) selected by generalized cross-validation (GCV).
#
# Interpretation: if smooth and raw IRFs agree in shape, the main results
# are not driven by sampling noise at individual horizons. Divergence flags
# noisy estimates that should be interpreted cautiously.
#
# SE propagation: Var(β_smooth) = S · diag(se²) · S'  where S = (I + λD'D)⁻¹
#
# Inputs (combined CSVs from main TWFE LP runs):
#   results/tables/lp_consumption_twfe/irf_consumption_twfe_all.csv
#   results/tables/lp_income_twfe_consumption_spec/irf_income_twfe_all.csv
#   results/tables/lp_wealth_twfe_consumption_spec/irf_wealth_twfe_all.csv
#
# Output:
#   results/diagnostics/lp_smooth/tables/
#   results/diagnostics/lp_smooth/plots/

suppressPackageStartupMessages(library(tidyverse))

set.seed(42)
cat("\n=== SMOOTH LP DIAGNOSTICS (Whittaker-Henderson, GCV lambda) ===\n\n")

CI_MULT  <- qnorm(0.95)   # 90% CI
MAX_HOR  <- 48L

OUT_TBL <- "results/diagnostics/lp_smooth/tables"
OUT_PLT <- "results/diagnostics/lp_smooth/plots"
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)

# ── Smoother functions ─────────────────────────────────────────────────────────

# Second-difference matrix D: (n-2) × n
make_D2 <- function(n) {
  D <- matrix(0, n - 2, n)
  for (k in seq_len(n - 2)) {
    D[k, k]     <-  1
    D[k, k + 1] <- -2
    D[k, k + 2] <-  1
  }
  D
}

# Whittaker-Henderson smoother with GCV lambda selection
smooth_wh <- function(y, se, lambda_grid = 10^seq(-2, 6, length.out = 120)) {
  n   <- length(y)
  D   <- make_D2(n)
  P   <- crossprod(D)     # t(D) %*% D — n × n penalty matrix
  I_n <- diag(n)

  gcv_vals <- vapply(lambda_grid, function(lam) {
    S     <- solve(I_n + lam * P)
    y_hat <- as.numeric(S %*% y)
    df    <- sum(diag(S))
    rss   <- sum((y - y_hat)^2)
    rss / max((n - df), 0.1)^2
  }, numeric(1))

  lam_opt   <- lambda_grid[which.min(gcv_vals)]
  S_opt     <- solve(I_n + lam_opt * P)
  y_smooth  <- as.numeric(S_opt %*% y)

  # SE propagation through smoother matrix
  V_ols    <- diag(se^2)
  V_smooth <- S_opt %*% V_ols %*% t(S_opt)
  se_sm    <- sqrt(pmax(0, diag(V_smooth)))

  list(estimate = y_smooth, se = se_sm, lambda = lam_opt,
       effective_df = sum(diag(S_opt)))
}

# ── Plot theme ─────────────────────────────────────────────────────────────────

irf_theme <- function() {
  theme_bw(base_size = 11) +
    theme(
      panel.grid.minor       = element_blank(),
      panel.grid.major       = element_line(color = "gray92", linewidth = 0.3),
      strip.background       = element_blank(),
      strip.text             = element_text(size = 10, face = "bold"),
      legend.position        = "inside",
      legend.position.inside = c(0.01, 0.99),
      legend.justification   = c(0, 1),
      legend.background      = element_rect(fill = alpha("white", 0.85), color = NA),
      legend.title           = element_blank(),
      legend.text            = element_text(size = 9),
      axis.title             = element_text(size = 10),
      plot.title             = element_text(size = 11, hjust = 0.5),
      plot.subtitle          = element_text(size = 8.5, hjust = 0.5, color = "gray40")
    )
}

# ── LP source definitions ──────────────────────────────────────────────────────

LP_SOURCES <- list(
  consumption = list(
    label  = "Consumption",
    colour = "#1f77b4",
    ytitle = "Cumulative log consumption response (1-SD shock)",
    path   = "results/tables/lp_consumption_twfe/irf_consumption_twfe_all.csv"
  ),
  income = list(
    label  = "Income",
    colour = "#d62728",
    ytitle = "Cumulative log income response (1-SD shock)",
    path   = "results/tables/lp_income_twfe_consumption_spec/irf_income_twfe_all.csv"
  ),
  wealth = list(
    label  = "Wealth (asinh)",
    colour = "#2ca02c",
    ytitle = "Cumulative asinh(wealth) response (1-SD shock)",
    path   = "results/tables/lp_wealth_twfe_consumption_spec/irf_wealth_twfe_all.csv"
  )
)

# ── Load CSVs ──────────────────────────────────────────────────────────────────

for (nm in names(LP_SOURCES)) {
  p <- LP_SOURCES[[nm]]$path
  if (!file.exists(p)) {
    warning(sprintf("Not found: %s — skipping %s", p, nm))
    LP_SOURCES[[nm]]$data <- NULL
  } else {
    LP_SOURCES[[nm]]$data <- read_csv(p, show_col_types = FALSE)
    cat(sprintf("✓ Loaded %s: %d rows\n", nm, nrow(LP_SOURCES[[nm]]$data)))
  }
}

# ── Apply smoother ─────────────────────────────────────────────────────────────

cat("\nSmoothing IRF paths via GCV Whittaker-Henderson...\n")

smooth_all <- list()

for (nm in names(LP_SOURCES)) {
  src <- LP_SOURCES[[nm]]
  if (is.null(src$data)) next

  d    <- src$data
  keys <- d |> distinct(shock_col, direction, htm_type)

  rows <- vector("list", nrow(keys))

  for (i in seq_len(nrow(keys))) {
    k <- keys[i, ]

    series <- d |>
      filter(shock_col == k$shock_col,
             direction == k$direction,
             htm_type  == k$htm_type) |>
      arrange(horizon)

    if (nrow(series) < 5 || all(is.na(series$estimate))) next

    sd_val   <- series$shock_sd[1]
    sm       <- smooth_wh(series$estimate, series$se)

    rows[[i]] <- tibble(
      horizon        = series$horizon,
      lp_type        = nm,
      lp_label       = src$label,
      shock_col      = series$shock_col,
      shock_label    = series$shock_label,
      direction      = series$direction,
      htm_type       = series$htm_type,
      shock_sd       = sd_val,
      nobs           = series$nobs,
      lambda_gcv     = sm$lambda,
      eff_df         = sm$effective_df,
      # Raw
      est_raw        = series$estimate,
      se_raw         = series$se,
      ci_lo_raw      = series$estimate - CI_MULT * series$se,
      ci_hi_raw      = series$estimate + CI_MULT * series$se,
      # Smooth
      est_sm         = sm$estimate,
      se_sm          = sm$se,
      ci_lo_sm       = sm$estimate - CI_MULT * sm$se,
      ci_hi_sm       = sm$estimate + CI_MULT * sm$se,
      # 1-SD scaled
      est_raw_1sd    = series$estimate * sd_val,
      ci_lo_raw_1sd  = (series$estimate - CI_MULT * series$se) * sd_val,
      ci_hi_raw_1sd  = (series$estimate + CI_MULT * series$se) * sd_val,
      est_sm_1sd     = sm$estimate * sd_val,
      ci_lo_sm_1sd   = (sm$estimate - CI_MULT * sm$se) * sd_val,
      ci_hi_sm_1sd   = (sm$estimate + CI_MULT * sm$se) * sd_val
    )
  }

  smooth_all[[nm]] <- bind_rows(rows)
  write_csv(smooth_all[[nm]], file.path(OUT_TBL, sprintf("smooth_lp_%s.csv", nm)))
  mean_lam <- mean(smooth_all[[nm]]$lambda_gcv, na.rm = TRUE)
  cat(sprintf("  ✓ %s: %d series smoothed (mean GCV λ = %.1f)\n",
              nm, nrow(keys), mean_lam))
}

combined <- bind_rows(smooth_all)
write_csv(combined, file.path(OUT_TBL, "smooth_lp_all.csv"))
cat(sprintf("\n✓ Combined: %d rows → %s/smooth_lp_all.csv\n",
            nrow(combined), OUT_TBL))

# ── Plots ──────────────────────────────────────────────────────────────────────

cat("\nGenerating plots...\n")

SHOCK_LABELS <- c(
  mp_shock_di = "DI Surprise",
  eps_rr      = "eps_rr (OLS)",
  eps_sb      = "eps_sb (Bai-Perron)",
  eps_tvp     = "eps_tvp (TVP-Bayes)"
)

direction_levels <- c("Full (Signed)", "Contractionary", "Expansionary")
htm_levels       <- c("PH2M", "WH2M")

plot_df <- combined |>
  mutate(
    direction = factor(direction, levels = direction_levels),
    htm_type  = factor(htm_type,  levels = htm_levels),
    lp_label  = factor(lp_label,  levels = c("Consumption", "Income", "Wealth (asinh)"))
  )

# ── 1. Per LP type × shock: raw (gray dashed) vs smooth (colored solid), 6-panel ──

for (nm in names(LP_SOURCES)) {
  src <- LP_SOURCES[[nm]]
  if (is.null(src$data)) next

  df_lp <- plot_df |> filter(lp_type == nm)
  shocks <- unique(df_lp$shock_col)

  for (sc in shocks) {
    sl  <- SHOCK_LABELS[sc]
    df_sc <- df_lp |> filter(shock_col == sc)

    p <- ggplot(df_sc, aes(x = horizon)) +
      # Raw: light gray dashed
      geom_hline(yintercept = 0, linetype = "dashed", colour = "black", linewidth = 0.4) +
      geom_ribbon(aes(ymin = ci_lo_raw_1sd, ymax = ci_hi_raw_1sd),
                  fill = "gray70", alpha = 0.25, colour = NA) +
      geom_line(aes(y = est_raw_1sd), colour = "gray55", linetype = "dashed",
                linewidth = 0.6) +
      # Smooth: colored solid
      geom_ribbon(aes(ymin = ci_lo_sm_1sd, ymax = ci_hi_sm_1sd),
                  fill = src$colour, alpha = 0.18, colour = NA) +
      geom_line(aes(y = est_sm_1sd), colour = src$colour, linewidth = 0.9) +
      facet_grid(htm_type ~ direction, scales = "free_y") +
      scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
      labs(
        title    = sprintf("%s LP — %s | Smooth LP Diagnostic", src$label, sl),
        subtitle = "Gray dashed = raw LP-OLS · Colored solid = smooth LP (WH, GCV λ) · 90% CI · 1-SD shock",
        x = "Horizon (months)", y = src$ytitle
      ) + irf_theme()

    fname <- sprintf("smooth_%s_%s_6panel.png", nm, sc)
    ggsave(file.path(OUT_PLT, fname), p, width = 12, height = 7, dpi = 300)
    cat(sprintf("  ✓ %s\n", fname))
  }
}

# ── 2. All three outcomes overlaid (smooth only) per shock × direction × HtM ──

OUT_COLOURS <- c(
  Consumption      = "#1f77b4",
  Income           = "#d62728",
  `Wealth (asinh)` = "#2ca02c"
)

shocks_all <- unique(plot_df$shock_col)

for (sc in shocks_all) {
  sl    <- SHOCK_LABELS[sc]
  df_sc <- plot_df |> filter(shock_col == sc)

  p_ov <- ggplot(df_sc, aes(x = horizon, colour = lp_label, fill = lp_label)) +
    geom_hline(yintercept = 0, linetype = "dashed", colour = "black", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_lo_sm_1sd, ymax = ci_hi_sm_1sd),
                alpha = 0.10, colour = NA) +
    geom_line(aes(y = est_sm_1sd), linewidth = 0.9) +
    facet_grid(htm_type ~ direction, scales = "free_y") +
    scale_colour_manual(values = OUT_COLOURS) +
    scale_fill_manual(values = OUT_COLOURS) +
    scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
    labs(
      title    = sprintf("Smooth LP IRFs — All Outcomes — %s", sl),
      subtitle = "Whittaker-Henderson smooth LP · GCV λ · 90% CI · 1-SD shock · TWFE",
      x = "Horizon (months)", y = "Cumulative response (1-SD shock)"
    ) + irf_theme()

  fname <- sprintf("smooth_all_outcomes_%s_6panel.png", sc)
  ggsave(file.path(OUT_PLT, fname), p_ov, width = 12, height = 7, dpi = 300)
  cat(sprintf("  ✓ %s\n", fname))
}

# ── 3. Lambda summary — how much smoothing was applied per series ──────────────

lambda_summary <- combined |>
  group_by(lp_type, shock_col, direction, htm_type) |>
  summarise(lambda_gcv = first(lambda_gcv),
            eff_df     = first(eff_df),
            .groups    = "drop") |>
  arrange(lp_type, shock_col, direction, htm_type)

write_csv(lambda_summary, file.path(OUT_TBL, "smooth_lambda_summary.csv"))
cat("\n── Lambda summary (GCV selected smoothing strength) ──\n")
print(lambda_summary, n = Inf)

cat(sprintf("\n✓ All plots → %s/\n", OUT_PLT))
cat("\n=== SMOOTH LP DIAGNOSTICS DONE ===\n")
cat(sprintf("  Tables: %s/\n", OUT_TBL))
cat(sprintf("  Plots:  %s/\n", OUT_PLT))
cat("\nINTERPRETATION:\n")
cat("  High λ (> 1000) → strong smoothing was needed; raw LP was noisy\n")
cat("  Low  λ (< 10)   → raw LP already smooth; results are robust\n")
cat("  If smooth ≈ raw → main results not driven by horizon-specific noise\n")
