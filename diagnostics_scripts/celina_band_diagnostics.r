#!/usr/bin/env Rscript
# CI Width, Power, and MDE Diagnostics for State-Month LP
#
# Examines how statistical precision evolves across horizons h = 0, …, 24.
# Produces per-horizon effective sample size, pointwise 90% CI widths,
# Bonferroni-corrected uniform bands, minimum detectable effects, and a
# truncation recommendation based on power relative to a plausible effect size.
#
# Focus term: neg_wh2m (Expansionary × WH2M) — the only PASS from the placebo test.
# All four interaction terms are included in output tables.
#
# Run from project root:
#   Rscript scripts/reporting/celina_band_diagnostics.r
#
# Output:
#   results/tables/band_diagnostics/
#   results/plots/band_diagnostics/

suppressPackageStartupMessages({
  library(tidyverse)
  library(sandwich)
})

cat("\n=== BAND DIAGNOSTICS: CI WIDTH, POWER, MDE ===\n\n")

# ── Constants ─────────────────────────────────────────────────────────────────

ALPHA      <- 0.10
MAX_HOR    <- 24L
H_TOTAL    <- MAX_HOR + 1L      # 25 horizons (h = 0, …, 24)
FOCUS_TERM <- "neg_wh2m"        # PASS in placebo test; primary term for plots

# Pointwise 90% CI multiplier
Z_PTWISE   <- qnorm(1 - ALPHA / 2)               # 1.645

# Bonferroni-corrected uniform band: qnorm(1 - α/(2H))
Z_BONF     <- qnorm(1 - ALPHA / (2 * H_TOTAL))   # ≈ 2.878

# MDE multiplier: one-sided test at α with 80% power
# MDE = (z_{1-α} + z_{0.80}) × SE_h
MDE_MULT   <- qnorm(1 - ALPHA) + qnorm(0.80)     # ≈ 2.124

cat(sprintf("z_ptwise (90%% CI):        %.4f\n", Z_PTWISE))
cat(sprintf("z_bonf   (uniform 90%%):   %.4f  [Bonferroni over %d horizons]\n",
            Z_BONF, H_TOTAL))
cat(sprintf("MDE_MULT (one-sided 80%%): %.4f\n\n", MDE_MULT))

OUT_PLT <- "results/plots/band_diagnostics"
OUT_TBL <- "results/tables/band_diagnostics"
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)

# ── Load and prepare data ─────────────────────────────────────────────────────

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

INTERACTION_TERMS <- c("pos_ph2m", "pos_wh2m", "neg_ph2m", "neg_wh2m")
INTERACTION_LBLS  <- c(
  pos_ph2m = "Contractionary × PH2M",
  pos_wh2m = "Contractionary × WH2M",
  neg_ph2m = "Expansionary × PH2M",
  neg_wh2m = "Expansionary × WH2M"
)
MAIN_EFFECTS <- c("eps_rr_pos", "eps_rr_neg_abs")
CTRL_VARS    <- c("lag1_share_PH2M", "lag1_share_WH2M",
                  "log_real_imports", "log_real_exports",
                  "infl_yoy", "log_bf", "lag1_lc")

fml <- as.formula(paste(
  "y_h ~",
  paste(c(MAIN_EFFECTS, INTERACTION_TERMS, CTRL_VARS), collapse = " + "),
  "+ factor(uf_code) + factor(ref_month_yyyymm)"
))

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

# ── Plausible effect reference ────────────────────────────────────────────────
# SD(eps_rr_neg_abs) × between-state SD(WH2M share)
# This is the magnitude of the neg_wh2m interaction term we would expect if
# a 1-SD expansionary shock produced a 1-between-SD differential response.

d0 <- make_h_sample(d_panel, 0L)

between_sd_wh2m <- d0 |>
  group_by(uf_code) |>
  summarise(mean_wh2m = mean(lag1_share_WH2M, na.rm = TRUE), .groups = "drop") |>
  pull(mean_wh2m) |>
  sd()

neg_shock_sd     <- sd(d0$eps_rr_neg_abs, na.rm = TRUE)
plausible_effect <- neg_shock_sd * between_sd_wh2m

cat(sprintf("Plausible effect (neg_wh2m):\n"))
cat(sprintf("  Between-state SD(WH2M share):  %.5f\n", between_sd_wh2m))
cat(sprintf("  National SD(eps_rr_neg_abs):   %.5f\n", neg_shock_sd))
cat(sprintf("  Plausible effect:              %.5f × %.5f = %.5f\n\n",
            neg_shock_sd, between_sd_wh2m, plausible_effect))

# ── Run LP at each horizon ─────────────────────────────────────────────────────

cat("Running LP at h = 0, …, 24...\n")

irf_raw <- map_dfr(0L:MAX_HOR, function(h) {
  dh <- make_h_sample(d_panel, h)
  if (nrow(dh) < 50) return(NULL)

  m  <- suppressWarnings(lm(fml, data = dh))
  vc <- vcovCL(m, cluster = dh$uf_code, type = "HC1")
  cf <- coef(m)
  se <- sqrt(diag(vc))

  map_dfr(INTERACTION_TERMS, function(trm) {
    if (!trm %in% names(cf) || is.na(cf[trm])) {
      return(tibble(horizon = h, term = trm, n_obs = nrow(dh),
                    n_states = n_distinct(dh$uf_code),
                    n_months = n_distinct(dh$ref_month_yyyymm),
                    est = NA_real_, se = NA_real_))
    }
    e <- cf[trm]; s <- se[trm]
    tibble(
      horizon  = h,
      term     = trm,
      n_obs    = nrow(dh),
      n_states = n_distinct(dh$uf_code),
      n_months = n_distinct(dh$ref_month_yyyymm),
      est      = e,
      se       = s
    )
  })
})

cat(sprintf("✓ LP complete: %d horizon × term rows\n\n", nrow(irf_raw)))

# ── Section 1: Effective sample size ──────────────────────────────────────────
#
# How many observations, states, and time periods enter the estimation at each
# horizon? Sample shrinks as h grows: leading the outcome by h months drops the
# last h rows per state. A balanced 27-state panel losing time periods monotonically
# is expected; non-monotone loss signals filtering issues.

cat("── Section 1: Effective sample size ──\n")

sample_tbl <- irf_raw |>
  distinct(horizon, n_obs, n_states, n_months) |>
  arrange(horizon) |>
  mutate(
    fraction_of_h0 = n_obs / n_obs[horizon == 0L],
    obs_lost       = n_obs[horizon == 0L] - n_obs
  )

write_csv(sample_tbl, file.path(OUT_TBL, "sample_size_by_horizon.csv"))

cat(sprintf("  h=0 baseline: %d obs | %d states | %d months\n",
            sample_tbl$n_obs[1], sample_tbl$n_states[1], sample_tbl$n_months[1]))
cat(sprintf("  h=24 final:   %d obs | %d states | %d months\n",
            tail(sample_tbl$n_obs, 1), tail(sample_tbl$n_states, 1),
            tail(sample_tbl$n_months, 1)))
cat(sprintf("  Sample retention at h=24: %.1f%%\n\n",
            tail(sample_tbl$fraction_of_h0, 1) * 100))

p_sample <- ggplot(sample_tbl, aes(x = horizon, y = n_obs)) +
  geom_col(fill = "#4c72b0", width = 0.7, alpha = 0.85) +
  geom_hline(yintercept = sample_tbl$n_obs[1], linetype = "dashed",
             colour = "gray30", linewidth = 0.5) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  scale_y_continuous(labels = scales::comma) +
  labs(
    title    = "Section 1: Estimation Sample Size by Horizon",
    subtitle = sprintf("Dashed = h=0 baseline (%s obs)", scales::comma(sample_tbl$n_obs[1])),
    x = "Horizon h (months)", y = "Observations"
  ) +
  theme_bw(base_size = 11) +
  theme(panel.grid.minor = element_blank(), panel.grid.major.x = element_blank(),
        plot.title = element_text(hjust = 0.5, size = 11),
        plot.subtitle = element_text(hjust = 0.5, size = 8.5, colour = "gray40"))

ggsave(file.path(OUT_PLT, "s1_sample_size.png"), p_sample,
       width = 9, height = 5, dpi = 300)
cat("  ✓ s1_sample_size.png\n\n")

# ── Section 2: CI width as a function of horizon ──────────────────────────────
#
# Pointwise 90% CI width = 2 × z_ptwise × SE_h.
# Bonferroni uniform band width = 2 × z_bonf × SE_h.
# Width grows as the sample shrinks and as the outcome accumulates noise.
# A non-monotone path signals time-varying collinearity or filtering effects.

cat("── Section 2: CI width by horizon ──\n")

ci_tbl <- irf_raw |>
  filter(!is.na(se)) |>
  mutate(
    ci_lo_ptwise    = est - Z_PTWISE * se,
    ci_hi_ptwise    = est + Z_PTWISE * se,
    ci_width_ptwise = 2 * Z_PTWISE * se,
    ci_lo_bonf      = est - Z_BONF * se,
    ci_hi_bonf      = est + Z_BONF * se,
    ci_width_bonf   = 2 * Z_BONF * se,
    # Coefficient-space MDE: minimum detectable β at one-sided α, 80% power
    mde             = MDE_MULT * se,
    # Log-response MDE: mde × typical interaction variation = mde × shock_SD × share_SD
    # Comparable to plausible_effect (both in log consumption units, assuming β=1 reference)
    mde_log         = MDE_MULT * se * neg_shock_sd * between_sd_wh2m,
    term_label      = factor(INTERACTION_LBLS[term], levels = unname(INTERACTION_LBLS))
  )

write_csv(
  ci_tbl |> select(horizon, term, n_obs, est, se,
                   ci_lo_ptwise, ci_hi_ptwise, ci_width_ptwise,
                   ci_lo_bonf, ci_hi_bonf, ci_width_bonf,
                   mde, mde_log),
  file.path(OUT_TBL, "ci_width_by_horizon.csv")
)

focus_ci <- ci_tbl |>
  filter(term == FOCUS_TERM, horizon %in% c(0L, 6L, 12L, 18L, 24L)) |>
  select(horizon, n_obs, se, ci_width_ptwise, ci_width_bonf, mde) |>
  mutate(across(c(se, ci_width_ptwise, ci_width_bonf, mde), ~round(.x, 5)))

cat(sprintf("  %s — CI width at key horizons:\n", FOCUS_TERM))
print(focus_ci, n = Inf)
cat("\n")

p_ciw <- ggplot(ci_tbl, aes(x = horizon)) +
  geom_line(aes(y = ci_width_ptwise), colour = "#4c72b0", linewidth = 0.9) +
  geom_line(aes(y = ci_width_bonf), colour = "#d62728",
            linetype = "dashed", linewidth = 0.9) +
  # Reference: CI width where MDE just equals the plausible coefficient (β=1)
  # i.e., 2 × Z_PTWISE / MDE_MULT = 1.55 — above this line, test is underpowered for β=1
  geom_hline(yintercept = 2 * Z_PTWISE / MDE_MULT,
             linetype = "dotted", colour = "gray30", linewidth = 0.5) +
  facet_wrap(~term_label, scales = "free_y", ncol = 2) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  labs(
    title    = "Section 2: CI Width by Horizon",
    subtitle = sprintf(
      "Blue = pointwise 90%% CI (z=%.3f)  ·  Red dashed = Bonferroni uniform (z=%.3f, H=%d)  ·  Dotted = power threshold (CI width = %.2f)",
      Z_PTWISE, Z_BONF, H_TOTAL, 2 * Z_PTWISE / MDE_MULT
    ),
    x = "Horizon h (months)", y = "CI width"
  ) +
  theme_bw(base_size = 11) +
  theme(panel.grid.minor = element_blank(), strip.background = element_blank(),
        strip.text = element_text(size = 9.5, face = "bold"),
        plot.title = element_text(hjust = 0.5, size = 11),
        plot.subtitle = element_text(hjust = 0.5, size = 8.5, colour = "gray40"))

ggsave(file.path(OUT_PLT, "s2_ci_width.png"), p_ciw,
       width = 10, height = 7, dpi = 300)
cat("  ✓ s2_ci_width.png\n\n")

# ── Section 3: CI width ratio diagnostic ──────────────────────────────────────
#
# Three ratios:
#   rel_ci_width:  CI_width_h / CI_width_h0 — how much wider than baseline?
#   bonf_penalty:  z_bonf / z_ptwise — cost of uniform coverage (constant ≈ 1.75)
#   mde_vs_plaus:  MDE_h / plausible_effect — power ratio (>1 = underpowered)
#   ci_vs_plaus:   CI_width_ptwise / (2 × plausible_effect) — signal-to-noise

cat("── Section 3: CI width ratio diagnostic ──\n")

ci_h0 <- ci_tbl |>
  filter(horizon == 0L) |>
  select(term, ci_width_h0 = ci_width_ptwise)

ratio_tbl <- ci_tbl |>
  left_join(ci_h0, by = "term") |>
  mutate(
    rel_ci_width = ci_width_ptwise / ci_width_h0,
    bonf_penalty = Z_BONF / Z_PTWISE,
    # mde_vs_plaus: ratio of MDE (log-response space) to plausible_effect (log-response space)
    # = MDE_MULT × SE_h (dimensionless; <1 means powered to detect β_plausible=1)
    mde_vs_plaus = mde_log / plausible_effect,
    ci_vs_plaus  = (ci_width_ptwise * neg_shock_sd * between_sd_wh2m) / (2 * plausible_effect)
  )

write_csv(
  ratio_tbl |> select(horizon, term, n_obs, se, rel_ci_width,
                      bonf_penalty, mde, mde_vs_plaus, ci_vs_plaus),
  file.path(OUT_TBL, "ci_width_ratios.csv")
)

focus_ratio <- ratio_tbl |>
  filter(term == FOCUS_TERM) |>
  select(horizon, n_obs, se, rel_ci_width, mde_vs_plaus, ci_vs_plaus) |>
  mutate(across(c(se, rel_ci_width, mde_vs_plaus, ci_vs_plaus), ~round(.x, 3)))

cat(sprintf("  Bonferroni penalty (constant): %.4f/%.4f = %.3f\n",
            Z_BONF, Z_PTWISE, Z_BONF / Z_PTWISE))
cat(sprintf("  %s — MDE/plausible ratio by horizon:\n", FOCUS_TERM))
print(focus_ratio, n = Inf)
cat("\n")

p_mde_ratio <- ggplot(ratio_tbl, aes(x = horizon, y = mde_vs_plaus)) +
  geom_hline(yintercept = 1, colour = "#d62728", linetype = "dashed", linewidth = 0.7) +
  geom_hline(yintercept = 2, colour = "gray40", linetype = "dotted", linewidth = 0.5) +
  geom_line(colour = "#4c72b0", linewidth = 0.9) +
  geom_point(data = ratio_tbl |> filter(mde_vs_plaus > 1),
             colour = "#d62728", size = 2, shape = 16) +
  facet_wrap(~term_label, ncol = 2) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  labs(
    title    = "Section 3: MDE / Plausible Effect by Horizon",
    subtitle = sprintf(
      "Red dashed = power threshold (ratio=1: MDE equals plausible log-response for β=1)\nMDE = %.3f × SE_h × SD(shock) × between-SD(share)  ·  Dotted = 2×",
      MDE_MULT
    ),
    x = "Horizon h (months)", y = "MDE / plausible effect  [= MDE_MULT × SE_h]"
  ) +
  theme_bw(base_size = 11) +
  theme(panel.grid.minor = element_blank(), strip.background = element_blank(),
        strip.text = element_text(size = 9.5, face = "bold"),
        plot.title = element_text(hjust = 0.5, size = 11),
        plot.subtitle = element_text(hjust = 0.5, size = 8, colour = "gray40"))

ggsave(file.path(OUT_PLT, "s3_mde_ratio.png"), p_mde_ratio,
       width = 10, height = 7, dpi = 300)
cat("  ✓ s3_mde_ratio.png\n\n")

# ── Section 4: Bonferroni uniform bands ───────────────────────────────────────
#
# Joint 90% confidence band under Bonferroni correction over all H=25 horizons.
# z_bonf = qnorm(1 - 0.10 / (2 × 25)) ≈ 2.878 vs z_ptwise ≈ 1.645.
#
# If the IRF is distinguishable from zero under the uniform band at any horizon,
# the result survives simultaneous inference across the full path.

cat("── Section 4: Bonferroni uniform bands ──\n")

focus_df <- ci_tbl |> filter(term == FOCUS_TERM)

p_bonf <- ggplot(focus_df, aes(x = horizon)) +
  geom_ribbon(aes(ymin = ci_lo_bonf, ymax = ci_hi_bonf,
                  fill = "Bonferroni uniform 90%"), alpha = 0.09, colour = NA) +
  geom_line(aes(y = ci_lo_bonf, colour = "Bonferroni uniform 90%"),
            linetype = "dashed", linewidth = 0.8) +
  geom_line(aes(y = ci_hi_bonf, colour = "Bonferroni uniform 90%"),
            linetype = "dashed", linewidth = 0.8) +
  geom_ribbon(aes(ymin = ci_lo_ptwise, ymax = ci_hi_ptwise,
                  fill = "Pointwise 90% CI"), alpha = 0.15, colour = NA) +
  # ±1 reference: plausible coefficient magnitude (β=1 implies log-response = plausible_effect)
  geom_hline(yintercept =  1, colour = "gray50", linetype = "dotted", linewidth = 0.5) +
  geom_hline(yintercept = -1, colour = "gray50", linetype = "dotted", linewidth = 0.5) +
  geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.4) +
  geom_line(aes(y = est, colour = "IRF estimate"), linewidth = 1.0) +
  scale_colour_manual(
    values = c(
      "IRF estimate"           = "black",
      "Bonferroni uniform 90%" = "#d62728"
    )
  ) +
  scale_fill_manual(
    values = c(
      "Pointwise 90% CI"       = "#4c72b0",
      "Bonferroni uniform 90%" = "#d62728"
    ),
    guide = "none"
  ) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
  labs(
    title    = sprintf("Section 4: Bonferroni Uniform Bands — %s", INTERACTION_LBLS[FOCUS_TERM]),
    subtitle = sprintf(
      "Blue shading = pointwise 90%% CI (z=%.3f)  ·  Red dashed = Bonferroni uniform (z=%.3f, H=%d)\nDotted = ±1 (plausible coefficient reference, β=1)",
      Z_PTWISE, Z_BONF, H_TOTAL
    ),
    x = "Horizon h (months)", y = "Estimated coefficient (log consumption / unit interaction)",
    colour = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor       = element_blank(),
    panel.grid.major       = element_line(colour = "gray93", linewidth = 0.3),
    legend.position        = "inside",
    legend.position.inside = c(0.01, 0.99),
    legend.justification   = c(0, 1),
    legend.background      = element_rect(fill = alpha("white", 0.9), colour = NA),
    legend.title           = element_blank(),
    plot.title             = element_text(hjust = 0.5, size = 11),
    plot.subtitle          = element_text(hjust = 0.5, size = 8.5, colour = "gray40")
  )

ggsave(file.path(OUT_PLT, "s4_bonferroni_bands.png"), p_bonf,
       width = 10, height = 6, dpi = 300)
cat("  ✓ s4_bonferroni_bands.png\n")

p_bonf4 <- ci_tbl |>
  ggplot(aes(x = horizon)) +
  geom_ribbon(aes(ymin = ci_lo_bonf, ymax = ci_hi_bonf),
              fill = "#d62728", alpha = 0.08, colour = NA) +
  geom_line(aes(y = ci_lo_bonf), colour = "#d62728",
            linetype = "dashed", linewidth = 0.7) +
  geom_line(aes(y = ci_hi_bonf), colour = "#d62728",
            linetype = "dashed", linewidth = 0.7) +
  geom_ribbon(aes(ymin = ci_lo_ptwise, ymax = ci_hi_ptwise),
              fill = "#4c72b0", alpha = 0.15, colour = NA) +
  geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.35) +
  geom_line(aes(y = est), colour = "black", linewidth = 0.9) +
  facet_wrap(~term_label, scales = "free_y", ncol = 2) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  labs(
    title    = "Section 4: Bonferroni Uniform Bands — All Terms",
    subtitle = sprintf(
      "Black = IRF  ·  Blue = pointwise 90%% CI  ·  Red dashed = Bonferroni uniform (H=%d)",
      H_TOTAL
    ),
    x = "Horizon h (months)", y = "Cumulative log consumption response"
  ) +
  theme_bw(base_size = 11) +
  theme(panel.grid.minor = element_blank(), strip.background = element_blank(),
        strip.text = element_text(size = 9.5, face = "bold"),
        plot.title = element_text(hjust = 0.5, size = 11),
        plot.subtitle = element_text(hjust = 0.5, size = 8.5, colour = "gray40"))

ggsave(file.path(OUT_PLT, "s4_bonferroni_4panel.png"), p_bonf4,
       width = 11, height = 7.5, dpi = 300)
cat("  ✓ s4_bonferroni_4panel.png\n\n")

# ── Section 5: Minimum detectable effect ──────────────────────────────────────
#
# MDE = (z_{1-α} + z_{0.80}) × SE_h ≈ 2.124 × SE_h
# One-sided test at α=10%, 80% power. Answers: what is the smallest true effect
# we would detect 80% of the time given the actual SE at this horizon?
#
# Horizon where MDE > plausible_effect: the LP cannot reliably detect an effect
# of the expected economic magnitude — inference is underpowered.

cat("── Section 5: MDE by horizon ──\n")

mde_tbl <- ci_tbl |>
  select(horizon, term, term_label, n_obs, n_states, n_months, est, se,
         ci_width_ptwise, ci_width_bonf, mde, mde_log) |>
  mutate(
    # mde_vs_plaus = mde_log / plausible_effect = MDE_MULT × SE_h
    # Interpretation: ratio of MDE (log-response) to plausible log-response (at β=1)
    # <1 → powered to detect β=1; >1 → underpowered
    mde_vs_plaus     = round(mde_log / plausible_effect, 3),
    power_flag       = mde_log > plausible_effect,
    plausible_effect = plausible_effect
  )

write_csv(mde_tbl |> select(-term_label),
          file.path(OUT_TBL, "mde_by_horizon.csv"))

focus_mde <- mde_tbl |>
  filter(term == FOCUS_TERM) |>
  select(horizon, n_obs, se, mde, mde_log, mde_vs_plaus, power_flag) |>
  mutate(across(c(se, mde, mde_log, mde_vs_plaus), ~round(.x, 5)))

cat(sprintf("  %s — MDE by horizon:\n", FOCUS_TERM))
cat(sprintf("  mde = %.4f × SE_h (coefficient space)\n", MDE_MULT))
cat(sprintf("  mde_log = mde × SD(shock) × between_SD(share) (log-response space)\n"))
cat(sprintf("  mde_vs_plaus = mde_log / plausible_effect = MDE_MULT × SE_h\n"))
cat(sprintf("  Underpowered when mde_vs_plaus > 1 (i.e., SE_h > %.4f)\n\n",
            1 / MDE_MULT))
print(focus_mde, n = Inf)

n_underpowered <- sum(focus_mde$power_flag)
cat(sprintf(
  "\n  %d / %d horizons underpowered for β=1 (MDE_log > plausible_effect = %.5f)\n\n",
  n_underpowered, nrow(focus_mde), plausible_effect
))

# Section 5 MDE plot: log-response space — MDE_log vs plausible_effect
p_mde <- ggplot(mde_tbl |> filter(term == FOCUS_TERM), aes(x = horizon)) +
  geom_hline(yintercept = plausible_effect, colour = "#2ca02c",
             linetype = "dashed", linewidth = 0.8) +
  geom_hline(yintercept = 0, colour = "gray30",
             linetype = "dashed", linewidth = 0.3) +
  geom_line(aes(y = mde_log), colour = "#4c72b0", linewidth = 1.0) +
  geom_line(aes(y = ci_width_ptwise * neg_shock_sd * between_sd_wh2m / 2),
            colour = "#4c72b0", linetype = "dotted", linewidth = 0.6) +
  geom_point(data = mde_tbl |> filter(term == FOCUS_TERM, power_flag),
             aes(y = mde_log), colour = "#d62728", size = 2.5) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
  labs(
    title    = sprintf("Section 5: MDE by Horizon — %s", INTERACTION_LBLS[FOCUS_TERM]),
    subtitle = sprintf(
      "Blue = MDE (log-response space = %.4f × SE_h × %.5f)  ·  Green dashed = plausible log-response (%.5f, β=1)\nBlue dotted = SE_h × SD(shock) × SD(share)  ·  Red dots = underpowered (MDE > plausible)",
      MDE_MULT, neg_shock_sd * between_sd_wh2m, plausible_effect
    ),
    x = "Horizon h (months)", y = "Log consumption response magnitude"
  ) +
  theme_bw(base_size = 11) +
  theme(panel.grid.minor = element_blank(),
        plot.title = element_text(hjust = 0.5, size = 11),
        plot.subtitle = element_text(hjust = 0.5, size = 8.5, colour = "gray40"))

ggsave(file.path(OUT_PLT, "s5_mde.png"), p_mde,
       width = 10, height = 5.5, dpi = 300)
cat("  ✓ s5_mde.png\n\n")

# ── Section 6: Summary comparison plot ────────────────────────────────────────
#
# Focus term only. Overlays:
#   1. Actual IRF (black line)
#   2. Pointwise 90% CI (blue shading)
#   3. Bonferroni uniform 90% band (red dashed)
#   4. ±MDE path (green dotted) — how wide the detection window is
#   5. ±plausible effect reference (green dashed horizontal)
#
# Where the IRF falls outside the Bonferroni band AND the band is narrower than
# the plausible effect, we have the strongest case for genuine heterogeneity.

cat("── Section 6: Summary comparison plot ──\n")

p_summary <- ggplot(focus_df, aes(x = horizon)) +
  geom_ribbon(aes(ymin = ci_lo_bonf, ymax = ci_hi_bonf),
              fill = "#d62728", alpha = 0.07, colour = NA) +
  geom_line(aes(y = ci_lo_bonf, colour = "Bonferroni 90%"),
            linetype = "dashed", linewidth = 0.75) +
  geom_line(aes(y = ci_hi_bonf, colour = "Bonferroni 90%"),
            linetype = "dashed", linewidth = 0.75) +
  geom_ribbon(aes(ymin = ci_lo_ptwise, ymax = ci_hi_ptwise),
              fill = "#4c72b0", alpha = 0.14, colour = NA) +
  # Coefficient-space MDE band: estimates must exceed ±mde to be individually significant
  geom_line(aes(y =  mde, colour = "±MDE"), linetype = "dotted", linewidth = 0.8) +
  geom_line(aes(y = -mde, colour = "±MDE"), linetype = "dotted", linewidth = 0.8) +
  # ±1 reference: plausible coefficient (β=1 → implied log-response = plausible_effect)
  geom_hline(yintercept =  1, colour = "#2ca02c", linetype = "dashed", linewidth = 0.6) +
  geom_hline(yintercept = -1, colour = "#2ca02c", linetype = "dashed", linewidth = 0.6) +
  geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.4) +
  geom_line(aes(y = est, colour = "IRF"), linewidth = 1.0) +
  annotate("text", x = MAX_HOR, y = 1.08,
           label = "β = 1 reference", size = 2.8, hjust = 1, colour = "#2ca02c") +
  scale_colour_manual(
    values = c(
      "IRF"            = "black",
      "Bonferroni 90%" = "#d62728",
      "±MDE"           = "#2ca02c"
    ),
    labels = c(
      "IRF"            = "IRF estimate",
      "Bonferroni 90%" = sprintf("Bonferroni uniform (z=%.3f)", Z_BONF),
      "±MDE"           = sprintf("±MDE (%.3f × SE_h)", MDE_MULT)
    )
  ) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
  labs(
    title    = sprintf("Section 6: CI Comparison — %s", INTERACTION_LBLS[FOCUS_TERM]),
    subtitle = sprintf(
      "All in coefficient space  ·  Blue shading = pointwise 90%% CI  ·  Red dashed = Bonferroni uniform\nGreen dotted = ±MDE (%.3f × SE_h)  ·  Green dashed = ±1 (plausible β reference)",
      MDE_MULT
    ),
    x = "Horizon h (months)", y = "Estimated coefficient (log consumption / unit interaction)",
    colour = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor       = element_blank(),
    panel.grid.major       = element_line(colour = "gray93", linewidth = 0.3),
    legend.position        = "inside",
    legend.position.inside = c(0.01, 0.99),
    legend.justification   = c(0, 1),
    legend.background      = element_rect(fill = alpha("white", 0.9), colour = NA),
    legend.title           = element_blank(),
    plot.title             = element_text(hjust = 0.5, size = 11),
    plot.subtitle          = element_text(hjust = 0.5, size = 8, colour = "gray40")
  )

ggsave(file.path(OUT_PLT, "s6_summary.png"), p_summary,
       width = 10, height = 6, dpi = 300)
cat("  ✓ s6_summary.png\n\n")

# ── Section 7: Truncation recommendation ──────────────────────────────────────
#
# At what horizon should inference be truncated?
#
# Criterion A (Bonferroni band width): ci_width_bonf < 4 × plausible_effect
#   The uniform band must be narrower than 4× the expected signal so that a
#   true effect of that magnitude would be detectable at a reasonable significance
#   level. Equivalent to: SE_h < 2 × plausible_effect / z_bonf.
#
# Criterion B (MDE ≤ plausible effect): MDE_h ≤ plausible_effect
#   The test must be powered to detect an effect of the expected magnitude.
#
# Recommendation: last horizon where both criteria hold.
# Applied to focus term (neg_wh2m) — the most econometrically credible channel.

cat("── Section 7: Truncation recommendation ──\n")

trunc_tbl <- ci_tbl |>
  filter(term == FOCUS_TERM) |>
  mutate(
    # Criterion A (log-response space): Bonferroni band width (log-response) < 4 × plausible_effect
    # ci_width_bonf_log = ci_width_bonf × shock_SD × share_SD < 4 × plausible_effect
    # Simplifies to: ci_width_bonf < 4 (since plausible_effect = shock_SD × share_SD)
    # Equivalently: SE_h < 2 / Z_BONF ≈ 0.695
    bonf_width_ok = ci_width_bonf * neg_shock_sd * between_sd_wh2m < 4 * plausible_effect,
    # Criterion B: MDE (log-response) ≤ plausible_effect → MDE_MULT × SE_h ≤ 1
    # Equivalently: SE_h ≤ 1 / MDE_MULT ≈ 0.471
    mde_powered   = mde_log <= plausible_effect,
    both_ok       = bonf_width_ok & mde_powered,
    mde_log_val   = mde_log,
    ci_bonf_log   = ci_width_bonf * neg_shock_sd * between_sd_wh2m
  ) |>
  select(horizon, n_obs, n_months, se, ci_width_bonf, ci_bonf_log, mde, mde_log_val,
         bonf_width_ok, mde_powered, both_ok)

write_csv(trunc_tbl, file.path(OUT_TBL, "truncation_recommendation.csv"))

last_both <- trunc_tbl$horizon[trunc_tbl$both_ok]
last_bonf <- trunc_tbl$horizon[trunc_tbl$bonf_width_ok]
last_mde  <- trunc_tbl$horizon[trunc_tbl$mde_powered]

rec_horizon <- if (length(last_both) > 0) max(last_both) else
  if (length(last_mde) > 0)  max(last_mde)  else
  if (length(last_bonf) > 0) max(last_bonf) else 0L

cat("\n══════════════════════════════════════════════════════\n")
cat("  SECTION 7: TRUNCATION RECOMMENDATION\n")
cat("══════════════════════════════════════════════════════\n\n")

cat(sprintf("  Focus term:                  %s\n", INTERACTION_LBLS[FOCUS_TERM]))
cat(sprintf("  Plausible effect:            %.5f\n", plausible_effect))
cat(sprintf("    = SD(eps_rr_neg_abs) × between-SD(WH2M share)\n"))
cat(sprintf("    = %.5f × %.5f\n", neg_shock_sd, between_sd_wh2m))
cat(sprintf("  Bonferroni z (H=%d):         %.4f\n", H_TOTAL, Z_BONF))
cat(sprintf("  MDE multiplier:              %.4f\n", MDE_MULT))
cat(sprintf("  Crit A SE threshold:         SE < 2/Z_BONF = %.4f\n", 2/Z_BONF))
cat(sprintf("  Crit B SE threshold:         SE < 1/MDE_MULT = %.4f\n\n", 1/MDE_MULT))

cat(sprintf("  Criterion A — Bonf band_log < 4×plausible (SE < %.4f):  last h = %s\n",
            2/Z_BONF, if (length(last_bonf) > 0) max(last_bonf) else "NONE"))
cat(sprintf("  Criterion B — MDE_log ≤ plausible (SE < %.4f):          last h = %s\n",
            1/MDE_MULT, if (length(last_mde) > 0) max(last_mde) else "NONE"))
cat(sprintf("  Both A + B satisfied:                                    last h = %s\n\n",
            if (length(last_both) > 0) max(last_both) else "NONE"))

cat(sprintf("  ► RECOMMENDATION: truncate LP at h = %d\n\n", rec_horizon))

n_both      <- sum(trunc_tbl$both_ok)
n_bonf_only <- sum(trunc_tbl$bonf_width_ok & !trunc_tbl$mde_powered)
n_neither   <- sum(!trunc_tbl$bonf_width_ok)

cat(sprintf("  Horizon breakdown (%d total):\n", nrow(trunc_tbl)))
cat(sprintf("    Both criteria OK:     %d\n", n_both))
cat(sprintf("    Bonferroni OK only:   %d\n", n_bonf_only))
cat(sprintf("    Neither criterion:    %d\n\n", n_neither))

cat("  Full truncation table (log-response space — all comparable to plausible_effect):\n")
print(
  trunc_tbl |>
    mutate(
      across(c(se, ci_bonf_log, mde_log_val), ~round(.x, 6)),
      status = case_when(
        both_ok       ~ "OK",
        bonf_width_ok ~ "marginal",
        TRUE          ~ "underpowered"
      )
    ) |>
    select(horizon, n_obs, se, ci_bonf_log, mde_log_val, status),
  n = Inf
)
cat(sprintf("  (plausible_effect = %.6f, 4× = %.6f)\n\n",
            plausible_effect, 4 * plausible_effect))

# Truncation plot in log-response space
p_trunc <- ggplot(trunc_tbl, aes(x = horizon)) +
  geom_vline(xintercept = rec_horizon, colour = "#d62728",
             linetype = "dashed", linewidth = 0.8) +
  geom_hline(yintercept = plausible_effect, colour = "#2ca02c",
             linetype = "dashed", linewidth = 0.6) +
  geom_hline(yintercept = 4 * plausible_effect, colour = "#2ca02c",
             linetype = "dotted", linewidth = 0.5) +
  geom_line(aes(y = ci_bonf_log, colour = "Bonferroni band (log-response)"), linewidth = 1.0) +
  geom_line(aes(y = mde_log_val, colour = "MDE (log-response)"), linewidth = 1.0) +
  geom_point(data = trunc_tbl |> filter(!both_ok),
             aes(y = mde_log_val), colour = "#d62728", size = 2, shape = 16) +
  annotate("text", x = rec_horizon + 0.5,
           y = max(c(trunc_tbl$ci_bonf_log, trunc_tbl$mde_log_val), na.rm = TRUE) * 0.95,
           label = sprintf("h = %d", rec_horizon),
           hjust = 0, size = 3, colour = "#d62728") +
  annotate("text", x = MAX_HOR, y = plausible_effect * 1.15,
           label = "Plausible effect\n(β=1)", hjust = 1, size = 2.8, colour = "#2ca02c") +
  annotate("text", x = MAX_HOR, y = 4 * plausible_effect * 1.05,
           label = "4×plausible", hjust = 1, size = 2.8, colour = "#2ca02c") +
  scale_colour_manual(
    values = c("Bonferroni band (log-response)" = "#d62728",
               "MDE (log-response)" = "#4c72b0")
  ) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
  labs(
    title    = sprintf("Section 7: Truncation Recommendation — %s", INTERACTION_LBLS[FOCUS_TERM]),
    subtitle = sprintf(
      "Log-response space (coefficient × SD(shock) × between-SD(share))  ·  Red line = recommended truncation h=%d\nGreen dashed = plausible log-response (%.5f)  ·  Red dots = underpowered",
      rec_horizon, plausible_effect
    ),
    x = "Horizon h (months)", y = "Log consumption response magnitude", colour = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor       = element_blank(),
    legend.position        = "inside",
    legend.position.inside = c(0.99, 0.99),
    legend.justification   = c(1, 1),
    legend.background      = element_rect(fill = alpha("white", 0.9), colour = NA),
    plot.title             = element_text(hjust = 0.5, size = 11),
    plot.subtitle          = element_text(hjust = 0.5, size = 8.5, colour = "gray40")
  )

ggsave(file.path(OUT_PLT, "s7_truncation.png"), p_trunc,
       width = 10, height = 5.5, dpi = 300)
cat(sprintf("\n  ✓ s7_truncation.png\n\n"))

# ── Done ──────────────────────────────────────────────────────────────────────

cat(sprintf("✓ All plots  → %s/\n", OUT_PLT))
cat(sprintf("✓ All tables → %s/\n", OUT_TBL))
cat("\n=== BAND DIAGNOSTICS DONE ===\n")
cat("\nFiles produced:\n")
cat("  tables/sample_size_by_horizon.csv\n")
cat("  tables/ci_width_by_horizon.csv\n")
cat("  tables/ci_width_ratios.csv\n")
cat("  tables/mde_by_horizon.csv\n")
cat("  tables/truncation_recommendation.csv\n")
cat("  plots/s1_sample_size.png\n")
cat("  plots/s2_ci_width.png\n")
cat("  plots/s3_mde_ratio.png\n")
cat("  plots/s4_bonferroni_bands.png\n")
cat("  plots/s4_bonferroni_4panel.png\n")
cat("  plots/s5_mde.png\n")
cat("  plots/s6_summary.png\n")
cat("  plots/s7_truncation.png\n")
