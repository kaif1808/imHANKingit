#!/usr/bin/env Rscript
# ============================================================
# Shock Diagnostic: mp_shock_di vs eps_rr
# ============================================================
# Compares the two monetary policy shock series used in the main LPs:
#   mp_shock_di : DI futures surprise (high-frequency financial identification)
#   eps_rr      : OLS narrative shock (Romer-Romer style, real-economy identification)
#
# Five diagnostic sections — see section headers for what each tests.
#
# Run from project root:
#   Rscript scripts/reporting/celina_shock_diagnostics.r
#
# Output:
#   results/plots/shock_diagnostics/
#   results/tables/shock_diagnostics/

suppressPackageStartupMessages({
  library(tidyverse)
  library(sandwich)
  library(zoo)
})

set.seed(42)
cat("\n=== SHOCK DIAGNOSTICS: mp_shock_di vs eps_rr ===\n\n")

CI_MULT     <- qnorm(0.95)   # 90% CI
MAX_HORIZON <- 24L

OUT_PLT <- "results/plots/shock_diagnostics"
OUT_TBL <- "results/tables/shock_diagnostics"
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)

SHOCK_COLS   <- c("mp_shock_di", "eps_rr")
SHOCK_LABELS <- c(mp_shock_di = "DI Surprise", eps_rr = "eps_rr (OLS)")
SHOCK_COLS_  <- c(mp_shock_di = "#333333", eps_rr = "#1f77b4")

# ── Load and prepare panel ─────────────────────────────────────────────────────

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset_.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(month_num       = month,
         lag1_share_ph2m = lag1_share_PH2M,
         lag1_share_wh2m = lag1_share_WH2M)

cat(sprintf("✓ Loaded: %d rows, %d states, years %d–%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code),
            min(d_raw$year), max(d_raw$year)))

panel <- d_raw |>
  arrange(uf_code, year, month_num) |>
  group_by(uf_code) |>
  mutate(
    log_consumption = log(consumption_index),
    log_imports     = log(real_imports + 1),
    log_exports     = log(real_exports + 1),
    log_bf          = log(coalesce(total_value_BF_old, 0) + 1),
    infl_mom        = log(ipca_index) - log(lag(ipca_index, 1)),
    infl_yoy_raw    = log(ipca_index) - log(lag(ipca_index, 12)),
    infl_yoy        = coalesce(infl_yoy_raw, infl_mom * 12),
    lag1_lc         = lag(log_consumption),
    ym_id           = year * 100L + month_num
  ) |>
  ungroup()

# Collapse to national monthly series — shocks are national (same across states)
nat <- panel |>
  filter(!is.na(population)) |>
  group_by(year, month_num) |>
  summarise(
    date            = as.Date(sprintf("%04d-%02d-01", first(year), first(month_num))),
    ym_id           = first(ym_id),
    mp_shock_di     = first(mp_shock_di),
    eps_rr          = first(eps_rr),
    log_consumption = weighted.mean(log_consumption, population, na.rm = TRUE),
    lag1_lc         = weighted.mean(lag1_lc,         population, na.rm = TRUE),
    log_imports     = weighted.mean(log_imports,      population, na.rm = TRUE),
    log_exports     = weighted.mean(log_exports,      population, na.rm = TRUE),
    log_bf          = weighted.mean(log_bf,           population, na.rm = TRUE),
    infl_yoy        = weighted.mean(infl_yoy,         population, na.rm = TRUE),
    lag1_share_ph2m = weighted.mean(lag1_share_ph2m,  population, na.rm = TRUE),
    lag1_share_wh2m = weighted.mean(lag1_share_wh2m,  population, na.rm = TRUE),
    .groups = "drop"
  ) |>
  arrange(date) |>
  mutate(
    lag1_di = lag(mp_shock_di),
    lag1_rr = lag(eps_rr)
  )

cat(sprintf("  National series: %d months (%s to %s)\n",
            nrow(nat), min(nat$date), max(nat$date)))

# ── Shared plot theme ──────────────────────────────────────────────────────────

diag_theme <- function() {
  theme_bw(base_size = 11) +
    theme(
      panel.grid.minor       = element_blank(),
      panel.grid.major       = element_line(color = "gray92", linewidth = 0.3),
      strip.background       = element_blank(),
      strip.text             = element_text(size = 10, face = "bold"),
      legend.position        = "bottom",
      legend.title           = element_blank(),
      legend.text            = element_text(size = 9),
      axis.title             = element_text(size = 10),
      plot.title             = element_text(size = 11, hjust = 0.5),
      plot.subtitle          = element_text(size = 8.5, hjust = 0.5, color = "gray40")
    )
}

# Major Brazilian macro events to annotate on all time-axis plots
events <- tribble(
  ~date,                   ~label,            ~vjust,
  as.Date("2015-01-01"),   "Recession\nstart", 1.2,
  as.Date("2016-12-01"),   "Recession\nend",   1.2,
  as.Date("2018-10-01"),   "2018\nelection",   1.2,
  as.Date("2020-03-01"),   "COVID-19",         1.2
)

recession_band <- data.frame(
  xmin = as.Date("2015-01-01"),
  xmax = as.Date("2016-12-01"),
  ymin = -Inf, ymax = Inf
)

add_events <- function(p) {
  p +
    geom_rect(data = recession_band,
              aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax),
              inherit.aes = FALSE,
              fill = "gray85", alpha = 0.5) +
    geom_vline(data = events,
               aes(xintercept = date),
               linetype = "dotted", colour = "gray40", linewidth = 0.5) +
    geom_text(data = events,
              aes(x = date, y = Inf, label = label, vjust = vjust),
              inherit.aes = FALSE, size = 2.5, colour = "gray35",
              hjust = -0.1, lineheight = 0.85)
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Time series comparison + rolling correlation
# ══════════════════════════════════════════════════════════════════════════════
# What this tests: whether the two shock series have similar timing and sign.
# What to look for:
#   - Periods where both shocks fire together vs. diverge (identification gap)
#   - Whether the rolling correlation is stable or collapses in specific episodes
#   - High rolling correlation → shocks agree on the direction of policy change
#   - Rolling correlation near zero → shocks disagree or one is inactive
cat("\n── Section 1: Time series comparison ──\n")

ts_long <- nat |>
  select(date, mp_shock_di, eps_rr) |>
  pivot_longer(cols = c(mp_shock_di, eps_rr),
               names_to = "shock", values_to = "value") |>
  mutate(shock = factor(shock, levels = SHOCK_COLS,
                        labels = unname(SHOCK_LABELS)))

p_ts <- ggplot(ts_long, aes(x = date, y = value, colour = shock)) +
  geom_hline(yintercept = 0, colour = "black", linewidth = 0.4) +
  geom_line(linewidth = 0.65, alpha = 0.85) +
  scale_colour_manual(values = unname(SHOCK_COLS_)) +
  scale_x_date(date_breaks = "1 year", date_labels = "%Y") +
  labs(title    = "Monetary Policy Shock Series: DI Surprise vs eps_rr",
       subtitle = "Gray band = 2015–16 recession · Dotted lines = major events",
       x = NULL, y = "Shock value") +
  diag_theme()

p_ts <- add_events(p_ts)
ggsave(file.path(OUT_PLT, "ts_shock_comparison.png"),
       p_ts, width = 12, height = 4, dpi = 300)
cat("  ✓ ts_shock_comparison.png\n")

# 12-month rolling correlation
roll_cor <- zoo::rollapply(
  zoo(cbind(nat$mp_shock_di, nat$eps_rr), nat$date),
  width = 12,
  FUN   = function(x) cor(x[, 1], x[, 2], use = "complete.obs"),
  by.column = FALSE, fill = NA, align = "right"
)

roll_df <- tibble(date = nat$date, rolling_cor = as.numeric(roll_cor))

p_rcor <- ggplot(roll_df, aes(x = date, y = rolling_cor)) +
  geom_hline(yintercept = 0,    colour = "black",  linewidth = 0.4) +
  geom_hline(yintercept = c(-0.5, 0.5),
             colour = "gray55", linetype = "dashed", linewidth = 0.35) +
  geom_line(colour = "#9467bd", linewidth = 0.8) +
  geom_ribbon(aes(ymin = pmin(rolling_cor, 0), ymax = 0),
              fill = "#d62728", alpha = 0.15) +
  geom_ribbon(aes(ymin = 0, ymax = pmax(rolling_cor, 0)),
              fill = "#2ca02c", alpha = 0.15) +
  scale_x_date(date_breaks = "1 year", date_labels = "%Y") +
  scale_y_continuous(limits = c(-1, 1), breaks = seq(-1, 1, 0.25)) +
  labs(title    = "12-Month Rolling Correlation: DI Surprise vs eps_rr",
       subtitle = "Green = positive agreement · Red = disagreement · Dashed = ±0.5 reference",
       x = NULL, y = "Pearson correlation (12m window)") +
  diag_theme()

p_rcor <- add_events(p_rcor)
ggsave(file.path(OUT_PLT, "rolling_correlation_12m.png"),
       p_rcor, width = 12, height = 4, dpi = 300)
cat("  ✓ rolling_correlation_12m.png\n")

# Combined: time series on top, rolling correlation below
p_combined <- cowplot_or_patchwork <- tryCatch({
  library(patchwork)
  (p_ts / p_rcor) + plot_layout(heights = c(1.5, 1))
}, error = function(e) NULL)

if (!is.null(p_combined)) {
  ggsave(file.path(OUT_PLT, "ts_and_rolling_combined.png"),
         p_combined, width = 12, height = 7, dpi = 300)
  cat("  ✓ ts_and_rolling_combined.png\n")
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Summary statistics
# ══════════════════════════════════════════════════════════════════════════════
# What this tests: basic distributional properties of each shock and how often
# they fire in the same direction.
# What to look for:
#   - Large SD differences → shocks are on very different scales; 1-SD
#     normalisation in the main LPs becomes important for comparisons
#   - Low n_nonzero for one shock → fewer observations driving the LP estimates
#   - Direction agreement < 50% → shocks actively disagree on policy stance
cat("\n── Section 2: Summary statistics ──\n")

# National series (one obs per month)
summary_stats <- map_dfr(SHOCK_COLS, function(sc) {
  x <- nat[[sc]]
  x_nz <- x[x != 0 & !is.na(x)]
  tibble(
    shock         = sc,
    shock_label   = SHOCK_LABELS[sc],
    n_total       = sum(!is.na(x)),
    n_nonzero     = length(x_nz),
    pct_nonzero   = round(100 * length(x_nz) / sum(!is.na(x)), 1),
    mean          = round(mean(x, na.rm = TRUE), 6),
    sd            = round(sd(x, na.rm = TRUE), 6),
    min           = round(min(x, na.rm = TRUE), 6),
    max           = round(max(x, na.rm = TRUE), 6),
    n_positive    = sum(x > 0, na.rm = TRUE),
    n_negative    = sum(x < 0, na.rm = TRUE),
    pct_positive  = round(100 * mean(x > 0, na.rm = TRUE), 1),
    pct_negative  = round(100 * mean(x < 0, na.rm = TRUE), 1)
  )
})

# Direction agreement: fraction of months where both shocks have same sign
both_nonzero <- nat |>
  filter(mp_shock_di != 0, eps_rr != 0, !is.na(mp_shock_di), !is.na(eps_rr))

dir_agree <- if (nrow(both_nonzero) > 0) {
  mean(sign(both_nonzero$mp_shock_di) == sign(both_nonzero$eps_rr))
} else NA_real_

summary_stats <- summary_stats |>
  mutate(dir_agreement_pct = round(100 * dir_agree, 1))

print(summary_stats, width = Inf)
write_csv(summary_stats, file.path(OUT_TBL, "summary_stats.csv"))
cat(sprintf("  Direction agreement (both non-zero months): %.1f%%\n",
            dir_agree * 100))
cat("  ✓ summary_stats.csv\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Correlation and overlap diagnostics
# ══════════════════════════════════════════════════════════════════════════════
# What this tests: how similar the two shock series are in level and rank.
# What to look for:
#   - Pearson correlation: sensitive to outliers; tells you if large eps_rr
#     episodes coincide with large DI surprises
#   - Spearman correlation: rank-based; more robust — tells you if the
#     ordering of episodes agrees even if magnitudes differ
#   - Scatter plot: identify outlier months where the two shocks strongly disagree
#   - Low coincidence rate → most eps_rr non-zero months have no DI counterpart
#     (or vice versa), implying the shocks capture different episodes
cat("\n── Section 3: Correlation and overlap diagnostics ──\n")

cor_df <- nat |> filter(!is.na(mp_shock_di), !is.na(eps_rr))

pearson  <- cor(cor_df$mp_shock_di, cor_df$eps_rr, method = "pearson")
spearman <- cor(cor_df$mp_shock_di, cor_df$eps_rr, method = "spearman")

cat(sprintf("  Pearson  correlation: %.4f\n", pearson))
cat(sprintf("  Spearman correlation: %.4f\n", spearman))

# Scatter plot
lm_fit <- lm(eps_rr ~ mp_shock_di, data = cor_df)
cat(sprintf("  Regression eps_rr ~ mp_shock_di: slope = %.4f, R² = %.4f\n",
            coef(lm_fit)[2], summary(lm_fit)$r.squared))

p_scatter <- ggplot(cor_df, aes(x = mp_shock_di, y = eps_rr)) +
  geom_hline(yintercept = 0, colour = "gray70", linewidth = 0.4) +
  geom_vline(xintercept = 0, colour = "gray70", linewidth = 0.4) +
  geom_point(colour = "#555555", alpha = 0.55, size = 1.8) +
  geom_smooth(method = "lm", colour = "#d62728", fill = "#d62728",
              alpha = 0.15, linewidth = 0.9, se = TRUE) +
  annotate("text", x = Inf, y = Inf, hjust = 1.1, vjust = 1.5, size = 3.2,
           label = sprintf("Pearson r = %.3f\nSpearman ρ = %.3f\nR² = %.3f",
                           pearson, spearman, summary(lm_fit)$r.squared)) +
  labs(title    = "Scatter: DI Surprise vs eps_rr",
       subtitle = "Each point = one month · Red line = OLS fit with 95% CI",
       x = "mp_shock_di (DI Surprise)",
       y = "eps_rr (OLS narrative)") +
  diag_theme()

ggsave(file.path(OUT_PLT, "scatter_shocks.png"),
       p_scatter, width = 6, height = 5, dpi = 300)
cat("  ✓ scatter_shocks.png\n")

# Coincidence: eps_rr non-zero months that also have non-zero mp_shock_di
eps_nz    <- nat |> filter(eps_rr != 0, !is.na(eps_rr))
di_nz     <- nat |> filter(mp_shock_di != 0, !is.na(mp_shock_di))
coincide  <- sum(eps_nz$mp_shock_di != 0, na.rm = TRUE)
pct_coin  <- coincide / nrow(eps_nz)

cat(sprintf("  eps_rr non-zero months: %d\n", nrow(eps_nz)))
cat(sprintf("  Of those, mp_shock_di also non-zero: %d (%.1f%%)\n",
            coincide, 100 * pct_coin))

overlap_tbl <- tibble(
  metric        = c("Pearson correlation", "Spearman correlation",
                    "Regression R²", "Regression slope",
                    "eps_rr nonzero months",
                    "mp_shock_di also nonzero (of eps_rr nonzero)",
                    "Coincidence rate (%)"),
  value         = c(round(pearson, 4), round(spearman, 4),
                    round(summary(lm_fit)$r.squared, 4),
                    round(coef(lm_fit)[2], 4),
                    nrow(eps_nz), coincide,
                    round(100 * pct_coin, 1))
)
write_csv(overlap_tbl, file.path(OUT_TBL, "correlation_overlap.csv"))
cat("  ✓ correlation_overlap.csv\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — First-stage relevance check (predictability / persistence test)
# ══════════════════════════════════════════════════════════════════════════════
# What this tests: how predictable each shock is from past values and controls.
# Interpretation:
#   - High F / high R² → shock is forecastable from lagged information
#     → raises concerns about anticipation effects and weak exogeneity
#   - Low F / low R² → shock is close to white noise → good for identification
#   - AR(1) coefficient on lag(shock): if large and significant, the shock
#     persists over time — relevant for LP horizon interpretation
#
# Note on FE choice: shocks are national (identical across states in each
# month). Including year-month FE would make the shock perfectly collinear
# with the FE and drop it. We therefore use state FE only here.
# The within-state variation in controls is absorbed by the state FE;
# temporal variation in the shock is identified from the time dimension.
cat("\n── Section 4: First-stage relevance (predictability) ──\n")

ctrl_vars <- c("lag1_share_ph2m", "lag1_share_wh2m",
               "log_imports", "log_exports", "infl_yoy", "log_bf")

fs_results <- map_dfr(SHOCK_COLS, function(sc) {
  lag_sc <- paste0("lag1_", sc)

  # ── National time-series regression ──────────────────────────────────────
  # Tests: can lagged shock + controls predict the current shock value?
  # Outcome = shock; predictors = lag(shock) + national controls
  nat_c <- nat |>
    mutate(shock_now = .data[[sc]],
           shock_lag = lag(.data[[sc]])) |>
    filter(!is.na(shock_now), !is.na(shock_lag),
           if_all(all_of(ctrl_vars), ~ !is.na(.x)))

  fml_nat <- as.formula(
    paste("shock_now ~ shock_lag +",
          paste(ctrl_vars, collapse = " + "))
  )
  m_nat   <- lm(fml_nat, data = nat_c)
  sm_nat  <- summary(m_nat)
  f_nat   <- sm_nat$fstatistic
  pval_nat <- pf(f_nat[1], f_nat[2], f_nat[3], lower.tail = FALSE)
  ar1_coef <- coef(m_nat)["shock_lag"]
  ar1_se   <- sqrt(diag(vcov(m_nat)))["shock_lag"]
  ar1_t    <- ar1_coef / ar1_se

  # ── Panel regression (state FE) ────────────────────────────────────────
  # Tests same predictability in a panel context; controls for state-specific
  # levels of HtM shares and macro variables via state FE.
  panel_c <- panel |>
    group_by(uf_code) |>
    mutate(shock_now = .data[[sc]],
           shock_lag = lag(.data[[sc]])) |>
    ungroup() |>
    filter(!is.na(shock_now), !is.na(shock_lag),
           if_all(all_of(ctrl_vars), ~ !is.na(.x)))

  fml_pan <- as.formula(
    paste("shock_now ~ shock_lag +",
          paste(ctrl_vars, collapse = " + "),
          "+ factor(uf_code)")
  )
  m_pan  <- lm(fml_pan, data = panel_c)
  sm_pan <- summary(m_pan)
  # F-test on shock_lag and controls only (excluding state FEs)
  coef_interest <- c("shock_lag", ctrl_vars)
  coef_idx      <- which(names(coef(m_pan)) %in% coef_interest)
  rss_r  <- sum(residuals(lm(update(fml_pan, . ~ . - shock_lag -
                                      lag1_share_ph2m - lag1_share_wh2m -
                                      log_imports - log_exports -
                                      infl_yoy - log_bf),
                              data = panel_c))^2)
  rss_u  <- sum(residuals(m_pan)^2)
  q_pan  <- length(coef_interest)
  df_pan <- m_pan$df.residual
  f_pan  <- ((rss_r - rss_u) / q_pan) / (rss_u / df_pan)

  tibble(
    shock             = sc,
    shock_label       = SHOCK_LABELS[sc],
    # National time-series
    nat_n             = nrow(nat_c),
    nat_R2            = round(sm_nat$r.squared, 4),
    nat_F_overall     = round(f_nat[1], 3),
    nat_F_pval        = round(pval_nat, 4),
    nat_ar1_coef      = round(ar1_coef, 4),
    nat_ar1_tstat     = round(ar1_t, 3),
    # Panel with state FE
    pan_n             = nrow(panel_c),
    pan_R2_adj        = round(sm_pan$adj.r.squared, 4),
    pan_F_excl_FE     = round(f_pan, 3)
  )
})

print(fs_results, width = Inf)
write_csv(fs_results, file.path(OUT_TBL, "firststage_relevance.csv"))
cat("  ✓ firststage_relevance.csv\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Simple LP IRF comparison (no HtM interactions)
# ══════════════════════════════════════════════════════════════════════════════
# What this tests: whether both shocks produce qualitatively similar aggregate
# consumption impulse responses — before introducing any HtM heterogeneity.
# A "sanity check" for the main LP results.
# What to look for:
#   - Same sign and rough shape → shocks capture similar monetary transmission
#   - One shock flat / insignificant → that shock may lack power in this sample
#   - Large magnitude difference → scaling by 1-SD normalises this
#
# Specification: log(consumption) ~ shock + lag1_lc + state FE
# Note: year-month FE is omitted here. Because shocks are national (same value
# across all states in a given month), including year-month FE would create
# perfect collinearity with the shock and make it unidentifiable. The time-series
# variation in the national shock is what identifies β_h; state FE controls for
# state-specific intercepts.
# SE: HC1 state-clustered (vcovCL).
cat("\n── Section 5: Simple LP IRF comparison (no HtM interaction) ──\n")

vcov_cl_state <- function(m, data) {
  sandwich::vcovCL(m, cluster = ~ uf_code, data = data, type = "HC1")
}

all_irf <- map_dfr(SHOCK_COLS, function(sc) {
  shock_sd_val <- sd(panel[[sc]], na.rm = TRUE)
  cat(sprintf("  Running LP: %s (SD = %.5f)\n", sc, shock_sd_val))

  rows <- vector("list", MAX_HORIZON + 1)

  for (h in 0:MAX_HORIZON) {
    d_h <- panel |>
      arrange(uf_code, year, month_num) |>
      group_by(uf_code) |>
      mutate(y_resp = lead(log_consumption, h) - lag1_lc) |>
      ungroup() |>
      rename(shock = !!sym(sc)) |>
      filter(!is.na(y_resp), !is.na(shock), !is.na(lag1_lc))

    m   <- lm(y_resp ~ shock + lag1_lc + factor(uf_code), data = d_h)
    vc  <- vcov_cl_state(m, d_h)

    b  <- as.numeric(coef(m)["shock"])
    se <- sqrt(as.numeric(vc["shock", "shock"]))

    rows[[h + 1]] <- tibble(
      horizon      = h,
      shock_col    = sc,
      shock_label  = SHOCK_LABELS[sc],
      shock_sd     = shock_sd_val,
      estimate     = b,
      se           = se,
      ci_low       = b - CI_MULT * se,
      ci_high      = b + CI_MULT * se,
      estimate_1sd = b * shock_sd_val,
      ci_low_1sd   = (b - CI_MULT * se) * shock_sd_val,
      ci_high_1sd  = (b + CI_MULT * se) * shock_sd_val,
      nobs         = nrow(d_h)
    )

    if (h %% 6 == 0)
      cat(sprintf("    h=%02d  n=%d  β=%.4f  se=%.4f\n", h, nrow(d_h), b, se))
  }

  bind_rows(rows)
})

write_csv(all_irf, file.path(OUT_TBL, "simple_lp_irf.csv"))
cat("  ✓ simple_lp_irf.csv\n")

# IRF overlay plot — 1-SD normalised for comparability
plot_irf <- all_irf |>
  mutate(shock_label = factor(shock_label,
                               levels = unname(SHOCK_LABELS)))

p_irf <- ggplot(plot_irf, aes(x = horizon, colour = shock_label,
                               fill = shock_label)) +
  geom_hline(yintercept = 0, linetype = "dashed",
             colour = "black", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_low_1sd, ymax = ci_high_1sd),
              alpha = 0.12, colour = NA) +
  geom_line(aes(y = estimate_1sd), linewidth = 0.95) +
  scale_colour_manual(values = setNames(unname(SHOCK_COLS_), unname(SHOCK_LABELS))) +
  scale_fill_manual(values = setNames(unname(SHOCK_COLS_), unname(SHOCK_LABELS))) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6),
                     limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "Simple LP IRF: Consumption Response to MP Shock (No HtM Interaction)",
    subtitle = paste0("State FE · HC1 state-clustered SE · 90% CI · 1-SD shock · h = 0–",
                      MAX_HORIZON, " months"),
    x = "Horizon (months)",
    y = "Cumulative log consumption response (1-SD shock)"
  ) +
  diag_theme() +
  theme(legend.position = "inside",
        legend.position.inside = c(0.01, 0.01),
        legend.justification   = c(0, 0))

ggsave(file.path(OUT_PLT, "simple_lp_irf_overlay.png"),
       p_irf, width = 9, height = 5, dpi = 300)
cat("  ✓ simple_lp_irf_overlay.png\n")

# Also print peak responses
peak_tbl <- all_irf |>
  group_by(shock_col, shock_label) |>
  summarise(
    peak_horizon    = horizon[which.min(estimate_1sd)],
    peak_response   = round(min(estimate_1sd), 6),
    h0_response     = round(estimate_1sd[horizon == 0], 6),
    h12_response    = round(estimate_1sd[horizon == 12], 6),
    h24_response    = round(estimate_1sd[horizon == 24], 6),
    .groups = "drop"
  )
cat("\n  Peak responses (1-SD scaled):\n")
print(peak_tbl, width = Inf)
write_csv(peak_tbl, file.path(OUT_TBL, "simple_lp_peak_responses.csv"))
cat("  ✓ simple_lp_peak_responses.csv\n")

# ── Final summary ──────────────────────────────────────────────────────────────

cat(sprintf("\n=== SHOCK DIAGNOSTICS DONE ===\n"))
cat(sprintf("  Plots:  %s/\n", OUT_PLT))
cat(sprintf("  Tables: %s/\n", OUT_TBL))
cat("\nFiles produced:\n")
walk(list.files(OUT_PLT, full.names = FALSE),
     ~ cat(sprintf("  plots/%s\n", .x)))
walk(list.files(OUT_TBL, full.names = FALSE),
     ~ cat(sprintf("  tables/%s\n", .x)))
