#!/usr/bin/env Rscript
# Placebo Test — time-shuffled eps_rr shock
#
# Validates that the heterogeneous monetary transmission result is driven by
# the actual timing of the eps_rr shocks, not by persistent cross-sectional
# patterns in the data. Runs 500 time-shuffle placebos and compares the actual
# IRF path against the null distribution of shuffled estimates.
#
# Run from project root:
#   Rscript scripts/reporting/celina_placebo_test.r
#
# Output:
#   results/tables/placebo/placebo_distribution.csv
#   results/tables/placebo/rank_table.csv
#   results/plots/placebo/

suppressPackageStartupMessages({
  library(tidyverse)
  library(sandwich)
  library(pbapply)
})

set.seed(42)
cat("\n=== PLACEBO TEST: TIME-SHUFFLED eps_rr ===\n\n")

CI_MULT     <- qnorm(0.95)
MAX_HOR     <- 24L
N_SHUFFLE   <- 500L

OUT_PLT <- "results/plots/placebo"
OUT_TBL <- "results/tables/placebo"
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)

# ── Load and prepare data ──────────────────────────────────────────────────────

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset_.csv"
if (!file.exists(lp_path)) {
  lp_path <- sub("_\\.csv$", ".csv", lp_path)
  if (!file.exists(lp_path)) stop("Dataset not found: ", lp_path)
}

d_raw <- read_csv(lp_path, show_col_types = FALSE)
cat(sprintf("✓ Loaded: %d rows, %d states, ym %d–%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code),
            min(d_raw$ref_month_yyyymm), max(d_raw$ref_month_yyyymm)))

d_panel <- d_raw |>
  arrange(uf_code, t_index) |>
  group_by(uf_code) |>
  mutate(
    log_bf           = log(coalesce(total_value_BF_old, 0) + 1),
    log_real_imports = log(coalesce(real_imports, 0) + 1),
    log_real_exports = log(coalesce(real_exports, 0) + 1),
    infl_yoy         = (ipca_index / lag(ipca_index, 12) - 1) * 100,
    lag1_lc          = lag1_log_consumption
  ) |>
  ungroup() |>
  mutate(
    eps_rr_pos     = pmax(eps_rr, 0),
    eps_rr_neg_abs = pmax(-eps_rr, 0),
    pos_ph2m = eps_rr_pos     * lag1_share_PH2M,
    pos_wh2m = eps_rr_pos     * lag1_share_WH2M,
    neg_ph2m = eps_rr_neg_abs * lag1_share_PH2M,
    neg_wh2m = eps_rr_neg_abs * lag1_share_WH2M
  )

# ── Section 1: Placebo shock construction ─────────────────────────────────────
#
# Shuffling strategy: permute the eps_rr time series at the NATIONAL level.
# Each permutation keeps the same set of shock magnitudes and their full
# cross-sectional structure (all states receive the same shock in a given month),
# but breaks the temporal relationship between the shock and the outcome.
#
# Why shuffle dates, not state-month observations?
#   eps_rr is a national shock — it takes a single value per month shared across
#   all 27 states. Shuffling at the state-month level would assign different
#   eps_rr values to different states within the same month, creating an
#   artificial within-month cross-sectional variation in the shock that does not
#   exist in reality. This would invalidate the TWFE design where the time FE
#   absorbs the national average and only the shock × state-HtM-share variation
#   is identified. Time-shuffling preserves the national structure: after each
#   permutation, all states still receive the same shock in any given month.
#
# Null hypothesis: if the actual IRF estimates are driven purely by cross-sectional
# patterns in HtM shares or by chance alignment of the shock timing with the
# consumption index, they should be replicable with shuffled shocks. Rejection
# of the null (actual estimates in the tails of the placebo distribution) supports
# genuine monetary transmission heterogeneity.

# National shock series: one value per month
nat_shock <- d_panel |>
  distinct(ref_month_yyyymm, eps_rr) |>
  arrange(ref_month_yyyymm)

nat_ym  <- as.character(nat_shock$ref_month_yyyymm)
nat_eps <- nat_shock$eps_rr

cat(sprintf("  National shock months: %d | nonzero: %d\n",
            length(nat_eps), sum(nat_eps != 0)))

# Pre-generate reproducible shuffle seeds
shuffle_seeds <- sample.int(1e6, N_SHUFFLE)

# ── Pre-build per-horizon datasets and fixed design matrices ───────────────────
#
# The fixed design matrix (controls + state FE + year-month FE) does not change
# across shuffles — only the four shock×share interaction columns change.
# Pre-building it once per horizon avoids repeating model.matrix() 500 times,
# reducing runtime by ~10x compared to re-running lm() from a formula each time.

INTERACTION_TERMS <- c("pos_ph2m", "pos_wh2m", "neg_ph2m", "neg_wh2m")
INTERACTION_LBLS  <- c(
  pos_ph2m = "Contractionary × PH2M",
  pos_wh2m = "Contractionary × WH2M",
  neg_ph2m = "Expansionary × PH2M",
  neg_wh2m = "Expansionary × WH2M"
)

make_h_sample <- function(d, h) {
  d |>
    group_by(uf_code) |>
    arrange(t_index) |>
    mutate(log_cons_lead = lead(log_consumption, h)) |>
    ungroup() |>
    mutate(y_h = log_cons_lead - lag1_lc) |>
    filter(!is.na(y_h), !is.na(eps_rr),
           !is.na(lag1_share_PH2M), !is.na(lag1_share_WH2M),
           !is.na(infl_yoy), !is.na(log_bf),
           !is.na(log_real_imports), !is.na(log_real_exports)) |>
    group_by(uf_code)           |> filter(n() > 1) |> ungroup() |>
    group_by(ref_month_yyyymm)  |> filter(n() > 1) |> ungroup()
}

cat("\nPre-building per-horizon datasets and design matrices...\n")

h_setups <- lapply(0L:MAX_HOR, function(h) {
  dh <- make_h_sample(d_panel, h)
  if (nrow(dh) < 50) return(NULL)

  # Fixed design matrix: controls + state FE + year-month FE
  # Intercept included by default in model.matrix(); no main shock effects
  # (they would be collinear with year-month FE — the time FE absorbs the
  # average national shock; only the shock×share cross-state variation is ID'd)
  X_fixed <- model.matrix(
    ~ lag1_share_PH2M + lag1_share_WH2M +
      log_real_imports + log_real_exports +
      infl_yoy + log_bf + lag1_lc +
      factor(uf_code) + factor(ref_month_yyyymm),
    data = dh
  )

  list(
    h       = h,
    nobs    = nrow(dh),
    y       = dh$y_h,
    X_fixed = X_fixed,
    ph2m    = dh$lag1_share_PH2M,
    wh2m    = dh$lag1_share_WH2M,
    ym      = as.character(dh$ref_month_yyyymm),
    data    = dh   # kept for actual LP (with SEs)
  )
})
h_setups <- Filter(Negate(is.null), h_setups)
cat(sprintf("  ✓ %d horizons pre-built\n", length(h_setups)))

# ── Actual baseline LP (with HC1 clustered SEs) ────────────────────────────────

cat("\nRunning actual baseline LP...\n")

CTRL_VARS <- c("lag1_share_PH2M", "lag1_share_WH2M",
               "log_real_imports", "log_real_exports",
               "infl_yoy", "log_bf", "lag1_lc")

fml_actual <- as.formula(paste(
  "y_h ~",
  paste(c(INTERACTION_TERMS, CTRL_VARS), collapse = " + "),
  "+ factor(uf_code) + factor(ref_month_yyyymm)"
))

actual_irf <- map_dfr(h_setups, function(hs) {
  dh <- hs$data                                # local copy avoids scoping issue
  m  <- lm(fml_actual, data = dh)
  vc <- vcovCL(m, cluster = dh$uf_code, type = "HC1")
  cf <- coef(m)
  se <- sqrt(diag(vc))
  tibble(
    horizon = hs$h,
    nobs    = hs$nobs,
    term    = INTERACTION_TERMS,
    est     = cf[INTERACTION_TERMS],
    se      = se[INTERACTION_TERMS],
    ci_lo   = cf[INTERACTION_TERMS] - CI_MULT * se[INTERACTION_TERMS],
    ci_hi   = cf[INTERACTION_TERMS] + CI_MULT * se[INTERACTION_TERMS]
  )
})

cat(sprintf("  ✓ Actual LP: %d rows\n", nrow(actual_irf)))

# ── Section 2: Placebo LP ──────────────────────────────────────────────────────
#
# For each of 500 time-shuffled shocks, run the identical LP specification at
# all horizons h = 0, …, 24. Uses lm.fit() with pre-built fixed design matrices
# for speed — only the four shock×share interaction columns change per shuffle.
# Stores only the point estimate (SEs not needed for the placebo distribution).
#
# A stable result should produce:
#   Placebo distribution centred near zero at all horizons.
#   Actual estimates in the tails (top or bottom 5%) at horizons where the true
#   monetary transmission effect is non-zero.

run_one_placebo <- function(seed_val) {
  set.seed(seed_val)
  perm_eps  <- sample(nat_eps)           # permute the 100 national shock values
  shock_map <- setNames(perm_eps, nat_ym) # map each month to a permuted shock

  result <- matrix(NA_real_, nrow = length(h_setups), ncol = 4,
                   dimnames = list(NULL, INTERACTION_TERMS))

  for (j in seq_along(h_setups)) {
    hs <- h_setups[[j]]

    # Look up permuted shock for each row's month
    eps_shuf    <- shock_map[hs$ym]
    pos_shuf    <- pmax(eps_shuf, 0)
    neg_shuf    <- pmax(-eps_shuf, 0)

    # Shock × share interaction columns (only these 4 change per shuffle)
    X_int <- cbind(
      pos_ph2m = pos_shuf * hs$ph2m,
      pos_wh2m = pos_shuf * hs$wh2m,
      neg_ph2m = neg_shuf * hs$ph2m,
      neg_wh2m = neg_shuf * hs$wh2m
    )
    # Interaction terms first so their coefficients are positions 1:4
    X_full <- cbind(X_int, hs$X_fixed)

    fit <- tryCatch(lm.fit(X_full, hs$y), error = function(e) NULL)
    if (!is.null(fit)) {
      cf <- fit$coefficients
      result[j, ] <- cf[INTERACTION_TERMS]
    }
  }
  result
}

cat(sprintf("\nRunning %d placebo shuffles (lm.fit, pre-built design matrices)...\n",
            N_SHUFFLE))
pboptions(type = "timer", char = "=")

placebo_raw <- pblapply(shuffle_seeds, run_one_placebo)

# Shape: list of N_SHUFFLE matrices [n_horizons × 4]
# Convert to long tibble
placebo_long <- map2_dfr(placebo_raw, seq_len(N_SHUFFLE), function(mat, idx) {
  as_tibble(mat) |>
    mutate(horizon    = map_int(h_setups, "h"),
           shuffle_id = idx)
}) |>
  pivot_longer(cols = all_of(INTERACTION_TERMS), names_to = "term", values_to = "est_placebo")

cat(sprintf("\n✓ Placebo estimates: %d rows\n", nrow(placebo_long)))

# ── Section 3: Placebo distribution summary ────────────────────────────────────
#
# The placebo distribution should be centred near zero at all horizons under the
# null of no genuine transmission heterogeneity. A median deviating from zero by
# more than 0.1 suggests a systematic cross-sectional pattern that survives time
# randomisation (e.g., structural correlation between HtM shares and baseline
# consumption trends), independent of the shock timing.

cat("\n── Section 3: Placebo distribution summary ──\n")

placebo_dist <- placebo_long |>
  filter(!is.na(est_placebo)) |>
  group_by(term, horizon) |>
  summarise(
    p05       = quantile(est_placebo, 0.05),
    p25       = quantile(est_placebo, 0.25),
    p50       = quantile(est_placebo, 0.50),
    p75       = quantile(est_placebo, 0.75),
    p95       = quantile(est_placebo, 0.95),
    placebo_sd = sd(est_placebo),
    n_valid   = sum(!is.na(est_placebo)),
    .groups   = "drop"
  ) |>
  mutate(median_flag = abs(p50) > 0.1)

write_csv(placebo_dist, file.path(OUT_TBL, "placebo_distribution.csv"))
cat(sprintf("✓ Saved placebo_distribution.csv (%d rows)\n", nrow(placebo_dist)))

# Flag horizons where median ≠ 0
flagged_med <- placebo_dist |> filter(median_flag)
if (nrow(flagged_med) == 0) {
  cat("  Placebo medians all within ±0.1 of zero — no systematic baseline pattern.\n")
} else {
  cat(sprintf("  WARNING: %d horizon×term combinations have |median| > 0.1:\n",
              nrow(flagged_med)))
  print(flagged_med |> select(term, horizon, p50), n = Inf)
}

# ── Section 4: Actual vs placebo comparison plots ──────────────────────────────
#
# How to read:
#   Actual IRF inside the red dashed envelope: estimate indistinguishable from
#     random noise — no evidence of genuine transmission at this horizon.
#   Actual IRF outside the red dashed envelope: estimate in the 5% tail of the
#     null distribution — significant relative to the placebo benchmark.
#   Dots on the line: specific horizons where the actual falls outside the 90th
#     percentile envelope.
#
# The placebo envelope is NOT a confidence interval for the actual estimate —
# it is the distribution of estimates you would get if the shock timing were
# random. It answers "is the actual estimate more extreme than chance?"

cat("\n── Section 4: Generating actual vs placebo plots ──\n")

plot_df <- actual_irf |>
  left_join(placebo_dist |> select(term, horizon, p05, p50, p95, median_flag),
            by = c("term", "horizon")) |>
  mutate(
    outside_envelope = (est > p95) | (est < p05),
    term_label       = factor(INTERACTION_LBLS[term],
                              levels = unname(INTERACTION_LBLS))
  )

placebo_theme <- function() {
  theme_bw(base_size = 11) +
    theme(
      panel.grid.minor       = element_blank(),
      panel.grid.major       = element_line(color = "gray93", linewidth = 0.3),
      strip.background       = element_blank(),
      strip.text             = element_text(size = 10, face = "bold"),
      legend.position        = "inside",
      legend.position.inside = c(0.01, 0.99),
      legend.justification   = c(0, 1),
      legend.background      = element_rect(fill = alpha("white", 0.9), color = NA),
      legend.title           = element_blank(),
      legend.text            = element_text(size = 8.5),
      axis.title             = element_text(size = 10),
      plot.title             = element_text(size = 11, hjust = 0.5),
      plot.subtitle          = element_text(size = 8.5, hjust = 0.5, color = "gray40")
    )
}

for (trm in INTERACTION_TERMS) {
  df_t <- plot_df |> filter(term == trm)
  lbl  <- INTERACTION_LBLS[trm]
  pct_outside <- mean(df_t$outside_envelope, na.rm = TRUE) * 100

  p <- ggplot(df_t, aes(x = horizon)) +
    # Placebo 90th percentile envelope (dashed red)
    geom_ribbon(aes(ymin = p05, ymax = p95, fill = "Placebo 90% envelope"),
                alpha = 0.08, colour = NA) +
    geom_line(aes(y = p05, colour = "Placebo 90% envelope"),
              linetype = "dashed", linewidth = 0.7) +
    geom_line(aes(y = p95, colour = "Placebo 90% envelope"),
              linetype = "dashed", linewidth = 0.7) +
    # Placebo median (thin grey)
    geom_line(aes(y = p50, colour = "Placebo median"),
              linewidth = 0.5) +
    # Zero line
    geom_hline(yintercept = 0, linetype = "dashed",
               colour = "gray30", linewidth = 0.4) +
    # Actual IRF: 90% CI shading
    geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi, fill = "Actual IRF 90% CI"),
                alpha = 0.18, colour = NA) +
    # Actual IRF: solid black line
    geom_line(aes(y = est, colour = "Actual IRF"),
              linewidth = 1.0) +
    # Dots: horizons where actual falls outside placebo envelope
    geom_point(data = df_t |> filter(outside_envelope),
               aes(y = est, colour = "Actual outside envelope"),
               size = 2.5, shape = 16) +
    scale_colour_manual(
      values = c(
        "Actual IRF"              = "black",
        "Actual outside envelope" = "#d62728",
        "Placebo 90% envelope"    = "#d62728",
        "Placebo median"          = "gray60"
      ),
      breaks = c("Actual IRF", "Placebo 90% envelope",
                 "Placebo median", "Actual outside envelope")
    ) +
    scale_fill_manual(
      values = c(
        "Actual IRF 90% CI"    = "black",
        "Placebo 90% envelope" = "#d62728"
      ),
      guide = "none"
    ) +
    scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
    labs(
      title    = sprintf("Placebo Test: %s", lbl),
      subtitle = sprintf(
        "Black = actual IRF ± 90%% CI  ·  Red dashed = 90%% placebo envelope (N=%d shuffles)  ·  %.0f%% of horizons outside envelope",
        N_SHUFFLE, pct_outside
      ),
      x = "Horizon (months)",
      y = "Cumulative log consumption response"
    ) +
    placebo_theme()

  fname <- sprintf("placebo_%s.png", trm)
  ggsave(file.path(OUT_PLT, fname), p, width = 9, height = 5.5, dpi = 300)
  cat(sprintf("  ✓ %s  (%.0f%% of horizons outside placebo envelope)\n",
              fname, pct_outside))
}

# Combined 4-panel plot
p4 <- plot_df |>
  ggplot(aes(x = horizon)) +
  geom_ribbon(aes(ymin = p05, ymax = p95), fill = "#d62728",
              alpha = 0.07, colour = NA) +
  geom_line(aes(y = p05), colour = "#d62728", linetype = "dashed", linewidth = 0.6) +
  geom_line(aes(y = p95), colour = "#d62728", linetype = "dashed", linewidth = 0.6) +
  geom_line(aes(y = p50), colour = "gray65", linewidth = 0.45) +
  geom_hline(yintercept = 0, linetype = "dashed", colour = "gray30", linewidth = 0.35) +
  geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), fill = "black", alpha = 0.12, colour = NA) +
  geom_line(aes(y = est), colour = "black", linewidth = 0.95) +
  geom_point(data = plot_df |> filter(outside_envelope),
             aes(y = est), colour = "#d62728", size = 2.2, shape = 16) +
  facet_wrap(~term_label, scales = "free_y", ncol = 2) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
  labs(
    title    = "Placebo Test — All Interaction Terms",
    subtitle = sprintf(
      "Black = actual IRF · Red dashed = 90%% placebo envelope (%d shuffles) · Dots = outside envelope",
      N_SHUFFLE
    ),
    x = "Horizon (months)", y = "Cumulative log consumption response"
  ) +
  placebo_theme() +
  theme(legend.position = "none")

ggsave(file.path(OUT_PLT, "placebo_4panel.png"),
       p4, width = 11, height = 8, dpi = 300)
cat("  ✓ placebo_4panel.png\n")

# ── Section 5: Rank test ───────────────────────────────────────────────────────
#
# For each term × horizon, what percentile rank does the actual estimate occupy
# within the 500 placebo estimates?
#
# Rank > 95% or < 5%: actual estimate is in the tail of the null distribution.
# This is a one-sample rank test equivalent to a permutation p-value.
# A rank of 97.5% corresponds to a two-sided permutation p ≈ 0.05.
#
# Interpretation:
#   Rank > 95%: actual estimate is more POSITIVE than 95% of placebo estimates.
#   Rank < 5%:  actual estimate is more NEGATIVE than 95% of placebo estimates.
#   Both indicate that the actual estimate is unlikely under the null.

cat("\n── Section 5: Rank test ──\n")

rank_df <- placebo_long |>
  filter(!is.na(est_placebo)) |>
  left_join(actual_irf |> select(horizon, term, est_actual = est),
            by = c("horizon", "term")) |>
  group_by(term, horizon) |>
  summarise(
    n_valid      = sum(!is.na(est_placebo)),
    actual_est   = first(est_actual),
    rank_pct     = 100 * mean(est_placebo < actual_est, na.rm = TRUE),
    tail_flag    = rank_pct > 95 | rank_pct < 5,
    .groups      = "drop"
  )

write_csv(rank_df, file.path(OUT_TBL, "rank_table.csv"))
cat(sprintf("✓ Saved rank_table.csv (%d rows)\n", nrow(rank_df)))

# Print table at selected horizons
CHECK_HORIZONS <- c(0L, 6L, 12L, 18L, 24L)

rank_check <- rank_df |>
  filter(horizon %in% CHECK_HORIZONS) |>
  mutate(
    label = INTERACTION_LBLS[term],
    flag  = if_else(tail_flag, "*** TAIL ***", "")
  ) |>
  select(label, horizon, actual_est, rank_pct, flag) |>
  mutate(across(c(actual_est, rank_pct), ~round(.x, 2)))

cat("\nRank percentiles at h = 0, 6, 12, 18, 24 (>95% or <5% = tail):\n")
print(rank_check, n = Inf)

# ── Section 6: Summary verdict ─────────────────────────────────────────────────
#
# PASS: actual estimates consistently in the tails of the placebo distribution
#   at theoretically relevant horizons (h = 3–18), indicating the result is
#   driven by the actual shock timing, not chance cross-sectional patterns.
#
# WARN: mixed evidence — some horizons in tails, some not. Interpretation
#   depends on whether the theoretically key horizons (h = 6–12) are significant.
#
# FAIL: actual estimates indistinguishable from placebo at all horizons.
#   The result cannot be distinguished from noise under the null of random timing.

cat("\n══════════════════════════════════════════════════════\n")
cat("  SECTION 6: SUMMARY VERDICT\n")
cat("══════════════════════════════════════════════════════\n\n")

verdict_df <- rank_df |>
  mutate(
    in_tail     = rank_pct > 95 | rank_pct < 5,
    theory_hor  = horizon >= 3 & horizon <= 18
  ) |>
  group_by(term) |>
  summarise(
    pct_outside_all    = mean(in_tail, na.rm = TRUE) * 100,
    pct_outside_theory = mean(in_tail[theory_hor], na.rm = TRUE) * 100,
    n_theory_horizons  = sum(theory_hor),
    .groups = "drop"
  ) |>
  mutate(
    verdict = case_when(
      pct_outside_theory >= 50 ~ "PASS",
      pct_outside_theory >= 20 ~ "WARN",
      TRUE                     ~ "FAIL"
    ),
    label = INTERACTION_LBLS[term]
  )

for (i in seq_len(nrow(verdict_df))) {
  row <- verdict_df[i, ]
  cat(sprintf("%-32s  [%s]\n", row$label, row$verdict))
  cat(sprintf(
    "  %.0f%% of all horizons (0–24) outside placebo 90%% envelope\n",
    row$pct_outside_all
  ))
  cat(sprintf(
    "  %.0f%% of theory-relevant horizons (3–18) outside placebo 90%% envelope\n",
    row$pct_outside_theory
  ))
  if (row$verdict == "PASS") {
    cat("  → Actual estimates consistently in placebo tails at key horizons.\n")
    cat("    Result is unlikely under random-timing null — supports genuine transmission.\n\n")
  } else if (row$verdict == "WARN") {
    cat("  → Mixed evidence. Effect may be present but not uniformly significant.\n")
    cat("    Check which horizons are in-tail; economic channels often peak at h=6–12.\n\n")
  } else {
    cat("  → Actual estimates indistinguishable from placebo at key horizons.\n")
    cat("    Cannot rule out that result is driven by cross-sectional confounders\n")
    cat("    rather than shock timing. Consider alternative identification strategy.\n\n")
  }
}

write_csv(verdict_df, file.path(OUT_TBL, "placebo_verdict.csv"))

cat(sprintf("\n✓ All plots  → %s/\n", OUT_PLT))
cat(sprintf("✓ All tables → %s/\n", OUT_TBL))
cat("\n=== PLACEBO TEST DONE ===\n")
cat("\nFiles produced:\n")
cat(sprintf("  tables/placebo_distribution.csv (%d rows — percentiles per term×horizon)\n",
            nrow(placebo_dist)))
cat(sprintf("  tables/rank_table.csv (%d rows — permutation rank per term×horizon)\n",
            nrow(rank_df)))
cat(sprintf("  tables/placebo_verdict.csv (%d rows — PASS/WARN/FAIL per term)\n",
            nrow(verdict_df)))
cat(sprintf("  plots/ — 5 PNG files (%d individual + 1 combined 4-panel)\n",
            length(INTERACTION_TERMS)))
