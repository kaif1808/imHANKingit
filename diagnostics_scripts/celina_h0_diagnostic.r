#!/usr/bin/env Rscript
# h=0 Diagnostic — Impact regression, sign check, scaling, sensitivity, lag
#
# Six-section diagnostic specifically targeting the contemporaneous (h=0)
# heterogeneous monetary transmission result.
#
# What this tests:
#   1. Full coefficient table at h=0 — are the main shock effects absorbed by
#      the time FE? Are interaction terms on a reasonable scale?
#   2. Sign check — do interaction terms match economic priors?
#   3. Scaling — shares in fractions vs percentages? Shock SD plausible?
#   4. Sensitivity to controls and FE choice — does h=0 result survive removing
#      controls or FEs one at a time?
#   5. h=0 vs h=1 — is the response lagged by one month?
#   6. Plain-text verdict: PASS / WARN / FAIL per interaction term.
#
# Run from project root:
#   Rscript scripts/reporting/celina_h0_diagnostic.r

suppressPackageStartupMessages({
  library(tidyverse)
  library(sandwich)
})

cat("\n=== h=0 DIAGNOSTIC: eps_rr × HtM IMPACT REGRESSION ===\n\n")

CI_MULT <- qnorm(0.95)   # 90% CI

OUT_PLT <- "results/plots/h0_diagnostic"
OUT_TBL <- "results/tables/h0_diagnostic"
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
    # eps_rr > 0: contractionary (rate hike surprise)
    # eps_rr < 0: expansionary (rate cut surprise)
    eps_rr_pos     = pmax(eps_rr, 0),         # contractionary component
    eps_rr_neg_abs = pmax(-eps_rr, 0),        # expansionary component (positive)
    # Interaction terms: shock component × lagged state HtM share
    pos_ph2m = eps_rr_pos     * lag1_share_PH2M,
    pos_wh2m = eps_rr_pos     * lag1_share_WH2M,
    neg_ph2m = eps_rr_neg_abs * lag1_share_PH2M,
    neg_wh2m = eps_rr_neg_abs * lag1_share_WH2M
  )

# Build h=0 and h=1 estimation samples
# outcome: log_consumption_{t+h} - lag1_log_consumption_{t} (cumulative since t-1)
make_h_sample <- function(d, h) {
  d |>
    group_by(uf_code) |>
    arrange(t_index) |>
    mutate(log_cons_lead = lead(log_consumption, h)) |>
    ungroup() |>
    mutate(y_h = log_cons_lead - lag1_lc) |>
    filter(
      !is.na(y_h), !is.na(eps_rr),
      !is.na(lag1_share_PH2M), !is.na(lag1_share_WH2M),
      !is.na(infl_yoy), !is.na(log_bf),
      !is.na(log_real_imports), !is.na(log_real_exports)
    )
}

d0 <- make_h_sample(d_panel, 0L)
d1 <- make_h_sample(d_panel, 1L)
cat(sprintf("  h=0 estimation sample: %d obs\n", nrow(d0)))
cat(sprintf("  h=1 estimation sample: %d obs\n", nrow(d1)))

INTERACTION_TERMS <- c("pos_ph2m", "pos_wh2m", "neg_ph2m", "neg_wh2m")
INTERACTION_LBLS  <- c(
  pos_ph2m = "Contractionary × PH2M",
  pos_wh2m = "Contractionary × WH2M",
  neg_ph2m = "Expansionary × PH2M",
  neg_wh2m = "Expansionary × WH2M"
)

# Expected signs under standard HANK heterogeneity:
#   Contractionary shock (eps_rr_pos > 0) hits more-PH2M/WH2M states harder
#   → interaction coefficient should be NEGATIVE (worse consumption outcome)
#   Expansionary shock (eps_rr_neg_abs > 0) boosts more-PH2M/WH2M states more
#   → interaction coefficient should be POSITIVE
EXPECTED_SIGN <- c(pos_ph2m = -1, pos_wh2m = -1, neg_ph2m = 1, neg_wh2m = 1)

# Helper: extract coef + sandwich SE for named terms
extract_coefs <- function(model, vcov_mat, terms) {
  cf  <- coef(model)
  ses <- sqrt(diag(vcov_mat))
  map_dfr(terms, function(trm) {
    if (!trm %in% names(cf) || is.na(cf[trm])) {
      return(tibble(term = trm, est = NA_real_, se = NA_real_,
                    ci_lo = NA_real_, ci_hi = NA_real_, tstat = NA_real_,
                    note = "Dropped (collinear or absent)"))
    }
    e <- cf[trm]; s <- ses[trm]
    tibble(term = trm, est = e, se = s,
           ci_lo = e - CI_MULT * s, ci_hi = e + CI_MULT * s,
           tstat = e / s, note = "")
  })
}

# ── Section 1: Impact regression (full spec at h=0) ───────────────────────────
#
# What it tests: Can the full specification estimate all four interaction terms at h=0?
# Are the main shock effects (eps_rr_pos, eps_rr_neg_abs) dropped due to perfect
# collinearity with the year-month time FE?
#
# What to look for:
#   - Main effects (eps_rr_pos, eps_rr_neg_abs) should show "NA" — they vary only
#     by time (national), so they're absorbed by year-month dummies. This is expected.
#   - Interaction terms vary by state × time (shock × state share) and ARE identified.
#   - If any interaction term is also NA, there's a collinearity problem to investigate.

cat("\n── Section 1: Full h=0 coefficient table ──\n")

# Include main effects even though they'll be absorbed by time FE — this is
# intentional: we want the full specification table to confirm the FE absorption.
MAIN_EFFECTS <- c("eps_rr_pos", "eps_rr_neg_abs")
CTRL_VARS    <- c("lag1_share_PH2M", "lag1_share_WH2M",
                  "log_real_imports", "log_real_exports",
                  "infl_yoy", "log_bf", "lag1_lc")

all_rhs_terms <- c(MAIN_EFFECTS, INTERACTION_TERMS, CTRL_VARS)

fml_full <- as.formula(paste(
  "y_h ~",
  paste(all_rhs_terms, collapse = " + "),
  "+ factor(uf_code) + factor(ref_month_yyyymm)"
))

m1   <- suppressWarnings(lm(fml_full, data = d0))
vc1  <- vcovCL(m1, cluster = ~uf_code, data = d0, type = "HC1")

# Detect which terms were dropped by lm() due to singularity
cf_all <- coef(m1)
dropped <- names(cf_all)[is.na(cf_all)]
shock_dropped <- intersect(c(MAIN_EFFECTS, INTERACTION_TERMS), dropped)
time_dropped  <- grep("^factor\\(ref_month", dropped, value = TRUE)
if (length(dropped) > 0) {
  cat(sprintf("  Note: %d variable(s) set to NA by lm() due to collinearity:\n", length(dropped)))
  if (length(time_dropped) > 0) {
    cat(sprintf("        Time dummies dropped (%d): %s\n",
                length(time_dropped), paste(time_dropped, collapse = ", ")))
    cat("        Explanation: lm() processes formula left-to-right (QR pivoting).\n")
    cat("        Because eps_rr_pos/eps_rr_neg_abs appear before factor(ref_month_yyyymm),\n")
    cat("        lm() KEEPS the main shock effects and drops the collinear time dummies.\n")
    cat("        → eps_rr_pos and eps_rr_neg_abs absorb some time FE information.\n")
    cat("          Do NOT interpret their coefficients as pure causal shock effects.\n")
    cat("          The interaction terms are still identified from cross-state variation.\n\n")
  }
  if (length(shock_dropped) > 0) {
    cat(sprintf("        Shock/interaction terms dropped: %s\n",
                paste(shock_dropped, collapse = ", ")))
    cat("        → These interaction terms are not identified. Investigate collinearity.\n\n")
  }
}

# Full coefficient table (all non-FE terms)
display_terms <- c(MAIN_EFFECTS, INTERACTION_TERMS, CTRL_VARS)

full_coef_tbl <- map_dfr(display_terms, function(trm) {
  if (!trm %in% names(cf_all)) {
    return(tibble(term = trm, est = NA_real_, se = NA_real_,
                  tstat = NA_real_, ci_lo = NA_real_, ci_hi = NA_real_,
                  note = "Not in model"))
  }
  e <- cf_all[trm]
  if (is.na(e)) {
    return(tibble(term = trm, est = NA_real_, se = NA_real_,
                  tstat = NA_real_, ci_lo = NA_real_, ci_hi = NA_real_,
                  note = "Dropped (absorbed by time FE)"))
  }
  s  <- sqrt(vc1[trm, trm])
  tibble(term = trm, est = e, se = s,
         tstat = e / s, ci_lo = e - CI_MULT * s, ci_hi = e + CI_MULT * s,
         note = "")
}) |>
  mutate(across(c(est, se, tstat, ci_lo, ci_hi), ~round(.x, 5)))

write_csv(full_coef_tbl, file.path(OUT_TBL, "h0_coefficient_table.csv"))
cat("Full h=0 coefficient table:\n")
print(full_coef_tbl, n = Inf)
cat(sprintf("  R² = %.4f | Adj R² = %.4f | N = %d\n",
            summary(m1)$r.squared, summary(m1)$adj.r.squared, nrow(d0)))

# ── Section 2: Sign and magnitude check ───────────────────────────────────────
#
# What it tests: Do the four interaction terms have the expected signs?
#   Contractionary (eps_rr_pos) × PH2M/WH2M: should be NEGATIVE
#   Expansionary (eps_rr_neg_abs) × PH2M/WH2M: should be POSITIVE
#
# Economic logic: monetary tightening should reduce consumption more in states
# with more HtM households (binding liquidity constraints). Easing should lift
# consumption more in those states.
#
# Flags:
#   WRONG SIGN: sign(estimate) ≠ expected sign — qualitative misidentification
#   LARGE MAGNITUDE (|est| > 5): suggests a units problem (shares in 0–100?)

cat("\n── Section 2: Sign and magnitude check ──\n")

int_coefs <- extract_coefs(m1, vc1, INTERACTION_TERMS)

sign_check <- int_coefs |>
  mutate(
    label         = INTERACTION_LBLS[term],
    expected_sign = EXPECTED_SIGN[term],
    sign_ok       = !is.na(est) & (sign(est) == expected_sign),
    large_mag     = !is.na(est) & abs(est) > 5,
    flag          = case_when(
      is.na(est)  ~ "NA — not identified",
      !sign_ok    ~ "WRONG SIGN",
      large_mag   ~ "LARGE MAGNITUDE",
      TRUE        ~ "OK"
    )
  ) |>
  select(term, label, expected_sign, est, se, ci_lo, ci_hi, tstat, flag)

write_csv(sign_check, file.path(OUT_TBL, "h0_sign_check.csv"))
cat("\n")
print(sign_check |> mutate(across(where(is.numeric), ~round(.x, 5))), n = Inf)

# ── Section 3: Units and scaling diagnostic ────────────────────────────────────
#
# What it tests: Are the regressors on sensible scales?
#   Shares in fractions (0–1): mean ~0.20–0.30, max ~0.35 → correct
#   Shares in percentages (0–100): mean ~20–30, max ~35 → coefficients 100x too small
#
# The implied effect column translates coefficients into economically interpretable
# terms: how much does a 1-SD contractionary/expansionary shock shift log consumption
# in a state at the mean HtM share?

cat("\n── Section 3: Units and scaling diagnostic ──\n")

scale_vars <- c("lag1_share_PH2M", "lag1_share_WH2M", "eps_rr_pos", "eps_rr_neg_abs")
scale_tbl <- map_dfr(scale_vars, function(v) {
  x <- d0[[v]]
  tibble(variable = v, mean = mean(x, na.rm=T), sd = sd(x, na.rm=T),
         min = min(x, na.rm=T), max = max(x, na.rm=T),
         n_nonzero = sum(x != 0, na.rm=T))
}) |> mutate(across(where(is.numeric), ~round(.x, 5)))

cat("\nDescriptives in h=0 estimation sample:\n")
print(scale_tbl, n = Inf)

cat("\nScale assessment:\n")
ph2m_mean <- mean(d0$lag1_share_PH2M, na.rm = TRUE)
wh2m_mean <- mean(d0$lag1_share_WH2M, na.rm = TRUE)
if (ph2m_mean < 1) {
  cat(sprintf("  lag1_share_PH2M mean = %.3f → shares appear to be in FRACTIONS (0–1). ✓\n", ph2m_mean))
} else {
  cat(sprintf("  lag1_share_PH2M mean = %.1f → shares appear to be in PERCENTAGES (0–100). ✗\n", ph2m_mean))
  cat("  → Coefficients on interaction terms will be ~100x smaller than expected.\n")
}

pos_sd  <- sd(d0$eps_rr_pos[d0$eps_rr_pos > 0], na.rm = TRUE)
neg_sd  <- sd(d0$eps_rr_neg_abs[d0$eps_rr_neg_abs > 0], na.rm = TRUE)
cat(sprintf("  eps_rr_pos SD (nonzero): %.4f — %s\n", pos_sd,
            if (pos_sd < 0.5) "plausible scale for quarterly interest rate surprise." else "large — check units."))
cat(sprintf("  eps_rr_neg_abs SD (nonzero): %.4f — %s\n", neg_sd,
            if (neg_sd < 0.5) "plausible scale." else "large — check units."))

# Implied effects: 1-SD shock × mean HtM share × coefficient
cat("\nImplied effect of 1-SD shock × mean HtM share (in log consumption):\n")
implied <- sign_check |>
  filter(!is.na(est)) |>
  rowwise() |>
  mutate(
    shock_sd     = if_else(startsWith(term, "pos"), pos_sd, neg_sd),
    share_mean   = if_else(grepl("ph2m", term), ph2m_mean, wh2m_mean),
    implied_eff  = round(est * shock_sd * share_mean, 5),
    implied_pct  = round(implied_eff * 100, 3)
  ) |>
  ungroup() |>
  select(term, label, est, shock_sd, share_mean, implied_eff, implied_pct)

print(implied, n = Inf)
write_csv(implied, file.path(OUT_TBL, "h0_implied_effects.csv"))

# ── Section 4: Sensitivity to controls and FE choice ──────────────────────────
#
# What it tests: How much does the h=0 result depend on what is controlled for?
#   (a) No controls, no FEs: raw bivariate interaction (maximum confounding)
#   (b) Controls, no FEs: partial out observables but not unobservables
#   (c) Controls + state FE: absorb time-invariant state heterogeneity
#   (d) Controls + state + year-month FE: full TWFE (baseline)
#
# Stable result: interaction term estimates similar across specs (b), (c), (d).
# Instability between (a) and (b) is expected (uncontrolled confounders).
# Instability between (c) and (d) suggests the time FE is important.
#
# Note: main effects (eps_rr_pos, eps_rr_neg_abs) are dropped in spec (d)
# because they vary only by time and are collinear with year-month dummies.

cat("\n── Section 4: Sensitivity to controls and FE choice ──\n")

MAIN_SHOCK <- paste(MAIN_EFFECTS, collapse = " + ")
INT_TERMS  <- paste(INTERACTION_TERMS, collapse = " + ")
CTRL       <- paste(CTRL_VARS, collapse = " + ")

spec_formulae <- list(
  a_no_ctrl_no_fe  = paste(MAIN_SHOCK, INT_TERMS, sep = " + "),
  b_ctrl_no_fe     = paste(MAIN_SHOCK, INT_TERMS, CTRL, sep = " + "),
  c_ctrl_state_fe  = paste(MAIN_SHOCK, INT_TERMS, CTRL, "factor(uf_code)", sep = " + "),
  d_ctrl_full_fe   = paste(MAIN_SHOCK, INT_TERMS, CTRL,
                            "factor(uf_code)", "factor(ref_month_yyyymm)", sep = " + ")
)

SPEC_LABELS4 <- c(
  a_no_ctrl_no_fe = "(a) No controls, no FE",
  b_ctrl_no_fe    = "(b) Controls, no FE",
  c_ctrl_state_fe = "(c) Controls + state FE",
  d_ctrl_full_fe  = "(d) Controls + state + time FE [baseline]"
)

sens_results <- imap(spec_formulae, function(rhs, spec_key) {
  fml  <- as.formula(paste("y_h ~", rhs))
  m    <- suppressWarnings(lm(fml, data = d0))
  vc   <- vcovCL(m, cluster = ~uf_code, data = d0, type = "HC1")
  coefs <- extract_coefs(m, vc, INTERACTION_TERMS) |>
    mutate(spec = SPEC_LABELS4[[spec_key]])
  coefs
}) |> bind_rows()

# Wide comparison table
sens_wide <- sens_results |>
  select(term, spec, est, se) |>
  mutate(est_se = sprintf("%.4f (%.4f)", est, se)) |>
  select(term, spec, est_se) |>
  pivot_wider(names_from = spec, values_from = est_se)

cat("\nInteraction term estimates across specifications [est (SE)]:\n")
print(sens_wide, n = Inf)
write_csv(sens_results, file.path(OUT_TBL, "h0_sensitivity_specs.csv"))

# Coefficient plot across specs
sens_plot_df <- sens_results |>
  mutate(
    ci_lo     = est - CI_MULT * se,
    ci_hi     = est + CI_MULT * se,
    term_lbl  = factor(INTERACTION_LBLS[term], levels = unname(INTERACTION_LBLS)),
    spec      = factor(spec, levels = rev(unname(SPEC_LABELS4)))
  ) |>
  filter(!is.na(est))

p_sens <- ggplot(sens_plot_df, aes(y = spec, x = est, colour = spec)) +
  geom_vline(xintercept = 0, linetype = "dashed", colour = "gray40", linewidth = 0.4) +
  geom_errorbarh(aes(xmin = ci_lo, xmax = ci_hi),
                 height = 0.25, linewidth = 0.75) +
  geom_point(size = 2.5) +
  facet_wrap(~term_lbl, scales = "free_x", ncol = 2) +
  scale_colour_manual(values = c(
    "(a) No controls, no FE"              = "#aaaaaa",
    "(b) Controls, no FE"                 = "#ff7f0e",
    "(c) Controls + state FE"             = "#1f77b4",
    "(d) Controls + state + time FE [baseline]" = "black"
  )) +
  labs(
    title    = "h=0 Interaction Terms — Sensitivity to Controls and FE",
    subtitle = "eps_rr shock · HC1 state-clustered SE · 90% CI",
    x = "Point estimate", y = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    legend.position  = "none",
    strip.background = element_blank(),
    strip.text       = element_text(size = 9.5, face = "bold"),
    axis.text.y      = element_text(size = 8.5),
    plot.title       = element_text(hjust = 0.5, size = 11),
    plot.subtitle    = element_text(hjust = 0.5, size = 8.5, colour = "gray40"),
    panel.grid.minor = element_blank()
  )

ggsave(file.path(OUT_PLT, "h0_sensitivity_specs.png"),
       p_sens, width = 10, height = 6.5, dpi = 300)
cat("  ✓ h0_sensitivity_specs.png\n")

# ── Section 5: h=0 vs h=1 comparison ──────────────────────────────────────────
#
# What it tests: Is the contemporaneous (h=0) effect small because the shock
# transmits with a one-month lag?
#
# How to read:
#   If h=0 estimates are near zero AND h=1 estimates have the expected sign with
#   larger magnitudes, the transmission lag hypothesis is supported: households
#   adjust consumption in the month *after* the shock is observed/felt.
#   This is economically plausible for income-constrained households.
#
#   If h=0 and h=1 are both near zero, the effect may only emerge at longer horizons
#   (or the shock is genuinely weak at short horizons).
#
#   If h=0 has the wrong sign but h=1 is correct, it may reflect measurement
#   error or within-month timing of the shock relative to consumption data.

cat("\n── Section 5: h=0 vs h=1 comparison ──\n")

m1_reg <- suppressWarnings(lm(fml_full, data = d1))
vc1_reg <- vcovCL(m1_reg, cluster = ~uf_code, data = d1, type = "HC1")

coefs_h0 <- extract_coefs(m1,     vc1,     INTERACTION_TERMS) |> mutate(horizon = 0L)
coefs_h1 <- extract_coefs(m1_reg, vc1_reg, INTERACTION_TERMS) |> mutate(horizon = 1L)

h01_compare <- bind_rows(coefs_h0, coefs_h1) |>
  select(horizon, term, est, se, ci_lo, ci_hi, tstat) |>
  mutate(across(where(is.numeric), ~round(.x, 5))) |>
  arrange(term, horizon)

write_csv(h01_compare, file.path(OUT_TBL, "h0_h1_compare.csv"))

# Side-by-side table
h01_wide <- h01_compare |>
  mutate(est_se = sprintf("%.4f (%.4f)", est, se),
         lbl    = INTERACTION_LBLS[term]) |>
  select(lbl, horizon, est_se) |>
  pivot_wider(names_from = horizon, values_from = est_se,
              names_prefix = "h=")

cat("\nInteraction term estimates: h=0 vs h=1 [est (SE)]:\n")
print(h01_wide, n = Inf)

# Lag pattern flag
lag_signals <- h01_compare |>
  pivot_wider(id_cols = term, names_from = horizon,
              values_from = c(est, tstat)) |>
  mutate(
    h0_small = abs(est_0) < 0.5,
    h1_larger = abs(est_1) > abs(est_0),
    h1_right_sign = sign(est_1) == EXPECTED_SIGN[term],
    lag_suggested = h0_small & h1_larger & h1_right_sign
  )

cat("\nLag pattern signals:\n")
print(lag_signals |>
  select(term, est_0, tstat_0, est_1, tstat_1, lag_suggested), n = Inf)

# h=0 vs h=1 plot
h01_plot_df <- bind_rows(coefs_h0, coefs_h1) |>
  mutate(
    ci_lo    = est - CI_MULT * se,
    ci_hi    = est + CI_MULT * se,
    term_lbl = factor(INTERACTION_LBLS[term], levels = unname(INTERACTION_LBLS)),
    horizon  = factor(paste0("h = ", horizon))
  ) |>
  filter(!is.na(est))

p_h01 <- ggplot(h01_plot_df, aes(y = horizon, x = est, colour = horizon)) +
  geom_vline(xintercept = 0, linetype = "dashed", colour = "gray40", linewidth = 0.4) +
  geom_errorbarh(aes(xmin = ci_lo, xmax = ci_hi),
                 height = 0.25, linewidth = 0.75) +
  geom_point(size = 3) +
  facet_wrap(~term_lbl, scales = "free_x", ncol = 2) +
  scale_colour_manual(values = c("h = 0" = "#1f77b4", "h = 1" = "#d62728")) +
  labs(
    title    = "h=0 vs h=1: Is There a One-Month Transmission Lag?",
    subtitle = "Full TWFE spec · eps_rr · HC1 state-clustered SE · 90% CI",
    x = "Point estimate", y = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    legend.position  = "none",
    strip.background = element_blank(),
    strip.text       = element_text(size = 9.5, face = "bold"),
    axis.text.y      = element_text(size = 9),
    plot.title       = element_text(hjust = 0.5, size = 11),
    plot.subtitle    = element_text(hjust = 0.5, size = 8.5, colour = "gray40"),
    panel.grid.minor = element_blank()
  )

ggsave(file.path(OUT_PLT, "h0_vs_h1.png"),
       p_h01, width = 9, height = 5.5, dpi = 300)
cat("  ✓ h0_vs_h1.png\n")

# ── Section 6: Summary diagnosis ──────────────────────────────────────────────
#
# Consolidates all checks into a per-term verdict.
#
# PASS: correct sign, magnitude plausible, not sensitive to FE removal
# WARN: correct sign but either imprecise, marginally sensitive, or lag suggested
# FAIL: wrong sign, collinear/NA, or large magnitude suggesting units issue

cat("\n══════════════════════════════════════════════════════\n")
cat("  SECTION 6: SUMMARY DIAGNOSIS\n")
cat("══════════════════════════════════════════════════════\n\n")

# Gather all signals
baseline_ests <- sign_check |>
  select(term, label, est, se, ci_lo, ci_hi, tstat, flag, expected_sign) |>
  left_join(lag_signals |> select(term, lag_suggested), by = "term") |>
  left_join(
    sens_results |>
      filter(spec == SPEC_LABELS4["d_ctrl_full_fe"]) |>
      select(term, est_full = est),
    by = "term"
  ) |>
  left_join(
    sens_results |>
      filter(spec == SPEC_LABELS4["c_ctrl_state_fe"]) |>
      select(term, est_state_fe = est),
    by = "term"
  )

# Scaling diagnostic
scale_ok <- ph2m_mean < 1  # shares in fractions

# Per-term verdict
for (i in seq_len(nrow(baseline_ests))) {
  row    <- baseline_ests[i, ]
  lbl    <- row$label
  e      <- row$est
  s      <- row$se
  tstat  <- row$tstat
  fl     <- row$flag
  lag_s  <- row$lag_suggested
  e_full <- row$est_full
  e_sfe  <- row$est_state_fe

  # FE sensitivity: does adding time FE move estimate by >1 SE?
  fe_sensitive <- !is.na(e_sfe) & !is.na(e) & abs(e - e_sfe) > abs(s)

  if (is.na(e)) {
    verdict  <- "FAIL"
    reason   <- "Coefficient not identified (NA). Check for collinearity."
  } else if (fl == "WRONG SIGN") {
    verdict  <- "FAIL"
    reason   <- sprintf(
      "Sign is %s; expected %s. May indicate the h=0 result is spurious%s.",
      if (e > 0) "positive" else "negative",
      if (row$expected_sign > 0) "positive" else "negative",
      if (isTRUE(lag_s)) " — but h=1 shows the expected sign (lag)" else ""
    )
  } else if (!scale_ok) {
    verdict  <- "FAIL"
    reason   <- "Shares appear to be in percentages; coefficients scaled by 100."
  } else if (fl == "LARGE MAGNITUDE") {
    verdict  <- "WARN"
    reason   <- sprintf("|est| = %.3f > 5 — check units.", abs(e))
  } else if (abs(tstat) < 1.28) {
    verdict  <- "WARN"
    reason   <- sprintf("Correct sign but |t| = %.2f < 1.28 (below 90%% threshold).", abs(tstat))
    if (isTRUE(lag_s)) reason <- paste(reason, "h=1 comparison suggests one-month lag.")
  } else if (fe_sensitive) {
    verdict  <- "WARN"
    reason   <- sprintf(
      "Correct sign and significant, but estimate moves by >1 SE when time FE added (%.4f → %.4f).",
      e_sfe, e
    )
  } else {
    verdict  <- "PASS"
    reason   <- sprintf("|t| = %.2f, correct sign, stable across FE specs.", abs(tstat))
  }

  cat(sprintf("%-32s  [%s]\n", lbl, verdict))
  cat(sprintf("  Estimate: %.5f  SE: %.5f  t: %.2f  90%% CI: [%.4f, %.4f]\n",
              coalesce(e, NA_real_), coalesce(s, NA_real_), coalesce(tstat, NA_real_),
              row$ci_lo, row$ci_hi))
  cat(sprintf("  → %s\n\n", reason))
}

# Global scaling note
cat("── Scaling ──\n")
if (scale_ok) {
  cat(sprintf("  HtM shares in fractions (mean PH2M=%.3f, WH2M=%.3f). Scale OK.\n",
              ph2m_mean, wh2m_mean))
} else {
  cat(sprintf("  WARNING: HtM shares may be in percentages (mean PH2M=%.1f). Rescale.\n",
              ph2m_mean))
}
cat(sprintf("  eps_rr_pos SD (nonzero): %.4f | eps_rr_neg_abs SD (nonzero): %.4f\n",
            pos_sd, neg_sd))

# Lag note
lag_terms <- lag_signals$term[isTRUE(lag_signals$lag_suggested)]
cat("\n── Transmission lag ──\n")
if (length(lag_terms) > 0) {
  cat(sprintf("  One-month lag suggested for: %s\n",
              paste(INTERACTION_LBLS[lag_terms], collapse = ", ")))
  cat("  Interpretation: households adjust consumption in the month after the shock,\n")
  cat("  not contemporaneously. Check h=1 and h=2 for the leading edge of the effect.\n")
} else {
  cat("  No clear one-month lag pattern detected.\n")
}

cat(sprintf("\n✓ Tables → %s/\n", OUT_TBL))
cat(sprintf("✓ Plots  → %s/\n", OUT_PLT))
cat("\n=== h=0 DIAGNOSTIC DONE ===\n")
