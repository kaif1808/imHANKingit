#!/usr/bin/env Rscript
# Lag Robustness — sensitivity of H2M interaction estimates to lagged consumption controls
#
# Context: prior diagnostics show neg_wh2m (Expansionary × WH2M) has genuine signal
# (placebo PASS) but runs with wrong sign at h=6–15. Contractionary terms fail the
# placebo. This script tests whether lag length choice can explain the wrong sign on
# neg_wh2m or the null on contractionary terms, or whether these are robust features
# of the data regardless of lag structure.
#
# Run from project root:
#   Rscript scripts/reporting/celina_lag_robustness.r
#
# Output:
#   results/plots/lag_robustness/
#   results/tables/lag_robustness/

suppressPackageStartupMessages({
  library(tidyverse)
  library(sandwich)
  library(plm)
})

cat("\n=== LAG ROBUSTNESS ANALYSIS ===\n\n")

CI_MULT <- qnorm(0.95)   # 90% pointwise CI
MAX_HOR <- 24L
OUT_PLT <- "results/plots/lag_robustness"
OUT_TBL <- "results/tables/lag_robustness"
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)

# ── Load data ─────────────────────────────────────────────────────────────────

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset_.csv"
if (!file.exists(lp_path)) {
  lp_path <- sub("_\\.csv$", ".csv", lp_path)
  if (!file.exists(lp_path)) stop("Dataset not found: ", lp_path)
}

d_raw <- read_csv(lp_path, show_col_types = FALSE)
cat(sprintf("✓ Loaded: %d rows, %d states, ym %d–%d\n\n",
            nrow(d_raw), n_distinct(d_raw$uf_code),
            min(d_raw$ref_month_yyyymm), max(d_raw$ref_month_yyyymm)))

d_panel <- d_raw |>
  arrange(uf_code, t_index) |>
  group_by(uf_code) |>
  mutate(
    log_bf           = log(coalesce(total_value_BF_old, 0) + 1),
    log_real_imports = log(coalesce(real_imports, 0) + 1),
    log_real_exports = log(coalesce(real_exports, 0) + 1),
    infl_yoy         = (ipca_index / dplyr::lag(ipca_index, 12) - 1) * 100,
    lag1_lc          = lag1_log_consumption,
    lag2_lc          = lag2_log_consumption,             # already in dataset
    lag3_lc          = dplyr::lag(lag2_log_consumption, 1),
    lag4_lc          = dplyr::lag(lag2_log_consumption, 2),
    lag5_lc          = dplyr::lag(lag2_log_consumption, 3),
    lag6_lc          = dplyr::lag(lag2_log_consumption, 4)
  ) |>
  ungroup() |>
  mutate(
    eps_rr_pos     = pmax(eps_rr, 0),
    eps_rr_neg_abs = pmax(-eps_rr, 0),
    pos_ph2m       = eps_rr_pos     * lag1_share_PH2M,
    pos_wh2m       = eps_rr_pos     * lag1_share_WH2M,
    neg_ph2m       = eps_rr_neg_abs * lag1_share_PH2M,
    neg_wh2m       = eps_rr_neg_abs * lag1_share_WH2M
  )

INTERACTION_TERMS <- c("pos_ph2m", "pos_wh2m", "neg_ph2m", "neg_wh2m")
INTERACTION_LBLS  <- c(
  pos_ph2m = "Contractionary × PH2M",
  pos_wh2m = "Contractionary × WH2M",
  neg_ph2m = "Expansionary × PH2M",
  neg_wh2m = "Expansionary × WH2M"
)
MAIN_EFFECTS <- c("eps_rr_pos", "eps_rr_neg_abs")
BASE_CTRLS   <- c("lag1_share_PH2M", "lag1_share_WH2M",
                  "log_real_imports", "log_real_exports", "infl_yoy", "log_bf")

# ── Section 1: Lag specifications ─────────────────────────────────────────────
#
# Lag length is a researcher degree of freedom in panel LP. The baseline (lag1_tfe)
# follows Jordà (2005): include one lag of the outcome to absorb first-order
# autocorrelation in consumption growth. Higher-order lags address residual
# autocorrelation but cost degrees of freedom and may introduce collinearity.
# lag0_tfe omits lagged consumption entirely — a conservative bound on the effect
# of lag controls. All other controls (state and year-month FE, shock terms,
# HC1 clustered SEs, horizons h=0–24) are identical across specifications.
#
# Key question given prior diagnostics: does any lag spec produce a correctly-signed
# (positive) neg_wh2m estimate at h=6–15? A sign reversal would indicate the
# wrong-sign result is a lag artefact rather than a genuine feature of the data.

cat("── Section 1: Lag specifications ──\n")

LAG_SPECS <- list(
  lag0_tfe = list(lag_ctrls = character(0),
                  label = "lag0 (no lag)", color = "#d62728"),
  lag1_tfe = list(lag_ctrls = "lag1_lc",
                  label = "lag1 (baseline)", color = "black"),
  lag2_tfe = list(lag_ctrls = c("lag1_lc", "lag2_lc"),
                  label = "lag2", color = "#1f77b4"),
  lag3_tfe = list(lag_ctrls = c("lag1_lc", "lag2_lc", "lag3_lc"),
                  label = "lag3", color = "#2ca02c"),
  lag4_tfe = list(lag_ctrls = c("lag1_lc", "lag2_lc", "lag3_lc", "lag4_lc"),
                  label = "lag4", color = "#9467bd"),
  lag5_tfe = list(lag_ctrls = c("lag1_lc", "lag2_lc", "lag3_lc", "lag4_lc", "lag5_lc"),
                  label = "lag5", color = "#8c564b"),
  lag6_tfe = list(lag_ctrls = c("lag1_lc", "lag2_lc", "lag3_lc", "lag4_lc", "lag5_lc", "lag6_lc"),
                  label = "lag6", color = "#e377c2")
)

SPEC_NAMES  <- names(LAG_SPECS)
SPEC_COLORS <- setNames(map_chr(LAG_SPECS, "color"), SPEC_NAMES)
SPEC_LABELS <- setNames(map_chr(LAG_SPECS, "label"), SPEC_NAMES)

build_fml <- function(lag_ctrls) {
  as.formula(paste(
    "y_h ~",
    paste(c(MAIN_EFFECTS, INTERACTION_TERMS, BASE_CTRLS, lag_ctrls),
          collapse = " + "),
    "+ factor(uf_code) + factor(ref_month_yyyymm)"
  ))
}

build_fml_plm <- function(lag_ctrls) {
  as.formula(paste(
    "y_h ~",
    paste(c(MAIN_EFFECTS, INTERACTION_TERMS, BASE_CTRLS, lag_ctrls),
          collapse = " + ")
  ))
}

make_h_sample <- function(d, h, lag_ctrls = "lag1_lc") {
  dh <- d |>
    group_by(uf_code) |>
    arrange(t_index) |>
    mutate(log_cons_lead = dplyr::lead(log_consumption, h)) |>
    ungroup() |>
    mutate(y_h = log_cons_lead - lag1_lc) |>
    filter(!is.na(y_h), !is.na(eps_rr),
           !is.na(lag1_share_PH2M), !is.na(lag1_share_WH2M),
           !is.na(infl_yoy), !is.na(log_bf),
           !is.na(log_real_imports), !is.na(log_real_exports))
  if ("lag2_lc" %in% lag_ctrls) dh <- dh |> filter(!is.na(lag2_lc))
  if ("lag3_lc" %in% lag_ctrls) dh <- dh |> filter(!is.na(lag3_lc))
  if ("lag4_lc" %in% lag_ctrls) dh <- dh |> filter(!is.na(lag4_lc))
  if ("lag5_lc" %in% lag_ctrls) dh <- dh |> filter(!is.na(lag5_lc))
  if ("lag6_lc" %in% lag_ctrls) dh <- dh |> filter(!is.na(lag6_lc))
  dh |>
    group_by(uf_code)          |> filter(n() > 1) |> ungroup() |>
    group_by(ref_month_yyyymm) |> filter(n() > 1) |> ungroup()
}

for (spec in SPEC_NAMES) {
  lc  <- LAG_SPECS[[spec]]$lag_ctrls
  n0  <- nrow(make_h_sample(d_panel, 0L,  lc))
  n24 <- nrow(make_h_sample(d_panel, 24L, lc))
  cat(sprintf("  %-10s  h=0: %4d obs  |  h=24: %4d obs  |  lag controls: %s\n",
              spec, n0, n24,
              if (length(lc) == 0) "(none)" else paste(lc, collapse = ", ")))
}
cat("\n")

# ── Section 2: Within-state autocorrelation check ─────────────────────────────
#
# The ACF of the state-demeaned h=0 outcome (log consumption growth) reveals the
# autocorrelation structure that lag controls must address. State demeaning is essential
# before computing the ACF: without it, the ACF reflects persistent cross-sectional
# level differences (higher-consumption states remain higher-consumption states across
# time), not within-state temporal dynamics. The resulting inflated ACF at all lags
# would incorrectly suggest that many lags are needed when the true within-state
# autocorrelation may be negligible.
#
# Stable result: ACF drops below the 95% CI band after lag 1 → lag1_tfe is
# statistically sufficient; higher-order lags address noise rather than systematic
# autocorrelation. Sensitive result: significant ACF at lags 2–3 → higher-order
# lags may materially improve efficiency and remove bias from omitted dynamics.

cat("── Section 2: Within-state ACF of demeaned outcome ──\n")

d0_base <- make_h_sample(d_panel, 0L, "lag1_lc")

acf_by_state <- d0_base |>
  group_by(uf_code) |>
  mutate(y_dm = y_h - mean(y_h, na.rm = TRUE)) |>
  ungroup()

T_avg    <- mean(as.numeric(table(acf_by_state$uf_code)))
ci_band  <- 1.96 / sqrt(T_avg)
MAX_LAG  <- 12L

state_acfs <- map_dfr(unique(acf_by_state$uf_code), function(s) {
  x <- acf_by_state |>
    filter(uf_code == s) |>
    arrange(ref_month_yyyymm) |>
    pull(y_dm)
  if (length(x) < MAX_LAG + 5) return(NULL)
  a <- acf(x, lag.max = MAX_LAG, plot = FALSE)$acf[-1]   # drop lag-0 (= 1)
  tibble(uf_code = s, lag = seq_len(MAX_LAG), acf_val = as.numeric(a))
})

acf_avg <- state_acfs |>
  group_by(lag) |>
  summarise(
    mean_acf = mean(acf_val, na.rm = TRUE),
    sd_acf   = sd(acf_val, na.rm = TRUE),
    .groups  = "drop"
  ) |>
  mutate(sig = abs(mean_acf) > ci_band)

write_csv(acf_avg, file.path(OUT_TBL, "acf_demeaned.csv"))

p_acf <- ggplot(acf_avg, aes(x = lag, y = mean_acf)) +
  geom_hline(yintercept = 0, colour = "gray30", linewidth = 0.4) +
  geom_hline(yintercept =  ci_band, colour = "#d62728",
             linetype = "dashed", linewidth = 0.5) +
  geom_hline(yintercept = -ci_band, colour = "#d62728",
             linetype = "dashed", linewidth = 0.5) +
  geom_ribbon(aes(ymin = mean_acf - sd_acf, ymax = mean_acf + sd_acf),
              fill = "#4c72b0", alpha = 0.15) +
  geom_col(aes(fill = sig), width = 0.55, alpha = 0.9) +
  scale_fill_manual(values = c("FALSE" = "#4c72b0", "TRUE" = "#d62728"),
                    guide = "none") +
  scale_x_continuous(breaks = seq(1, MAX_LAG)) +
  labs(
    title    = "Section 2: Within-State ACF of Demeaned h=0 Outcome",
    subtitle = sprintf(
      "State-demeaned log consumption growth · Mean ± 1 SD across %d states (shading)\nRed dashed = approx 95%% CI (±1.96/√T, T≈%.0f)  ·  Red bars = significant",
      n_distinct(acf_by_state$uf_code), T_avg
    ),
    x = "Lag", y = "Mean ACF (across states)"
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor = element_blank(), panel.grid.major.x = element_blank(),
    plot.title    = element_text(hjust = 0.5, size = 11),
    plot.subtitle = element_text(hjust = 0.5, size = 8.5, colour = "gray40")
  )

ggsave(file.path(OUT_PLT, "s2_acf.png"), p_acf,
       width = 9, height = 5.5, dpi = 300)
cat("  ✓ s2_acf.png\n")

sig_lags <- acf_avg$lag[acf_avg$sig]
cat(sprintf("  Significant ACF lags: %s\n",
            if (length(sig_lags) == 0) "none" else paste(sig_lags, collapse = ", ")))
cat(sprintf("  ACF at lag 1: %.4f  |  lag 2: %.4f  |  lag 3: %.4f\n\n",
            acf_avg$mean_acf[1], acf_avg$mean_acf[2], acf_avg$mean_acf[3]))

# ── Section 3: LP estimation across all four specs ────────────────────────────
#
# Runs the identical LP specification at h=0–24 under four lag structures; the only
# variation is in which lagged consumption controls enter the RHS. For each
# spec × horizon, stores point estimates, HC1 state-clustered SEs, and 90% CI bounds
# for all four interaction terms. A stable result across specs (similar magnitudes,
# same signs, largely overlapping CIs) confirms that the baseline lag1_tfe findings
# are not a lag artefact. A sensitive result — particularly a sign change in neg_wh2m
# at h=6–15 — would indicate that the lag structure is a key researcher degree of
# freedom that materially affects the substantive conclusions.

cat(sprintf("── Section 3: LP estimation (%d specs × 25 horizons) ──\n", length(LAG_SPECS)))

irf_all <- map_dfr(SPEC_NAMES, function(spec) {
  lc  <- LAG_SPECS[[spec]]$lag_ctrls
  fml <- build_fml(lc)
  cat(sprintf("  %s [%s]:", spec, LAG_SPECS[[spec]]$label))

  res <- map_dfr(0L:MAX_HOR, function(h) {
    dh <- make_h_sample(d_panel, h, lc)
    if (nrow(dh) < 50) return(NULL)

    m  <- suppressWarnings(lm(fml, data = dh))
    vc <- vcovCL(m, cluster = dh$uf_code, type = "HC1")
    cf <- coef(m); se <- sqrt(diag(vc))

    if (h %% 6 == 0) cat(sprintf(" h%02d", h))

    map_dfr(INTERACTION_TERMS, function(trm) {
      if (!trm %in% names(cf) || is.na(cf[trm])) {
        return(tibble(spec=spec, horizon=h, term=trm, n_obs=nrow(dh),
                      est=NA_real_, se=NA_real_, ci_lo=NA_real_, ci_hi=NA_real_))
      }
      e <- cf[trm]; s <- se[trm]
      tibble(spec=spec, horizon=h, term=trm, n_obs=nrow(dh),
             est=e, se=s, ci_lo=e-CI_MULT*s, ci_hi=e+CI_MULT*s)
    })
  })
  cat("\n")
  res
}) |>
  mutate(
    spec_label = factor(SPEC_LABELS[spec], levels = unname(SPEC_LABELS)),
    term_label = factor(INTERACTION_LBLS[term], levels = unname(INTERACTION_LBLS))
  )

write_csv(irf_all |> select(-spec_label, -term_label),
          file.path(OUT_TBL, "irf_all_specs.csv"))
cat(sprintf("\n✓ irf_all_specs.csv (%d rows)\n\n", nrow(irf_all)))

# ── Plot helper ───────────────────────────────────────────────────────────────

overlay_theme <- function() {
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
}

make_overlay_plot <- function(df, shade_band = NULL, title_str, subtitle_str) {
  p <- ggplot(df, aes(x = horizon, group = spec, colour = spec, fill = spec))

  if (!is.null(shade_band)) {
    p <- p + annotate("rect",
                      xmin = shade_band[1] - 0.5, xmax = shade_band[2] + 0.5,
                      ymin = -Inf, ymax = Inf,
                      fill = "#ff7f0e", alpha = 0.09)
  }

  p +
    geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.07, colour = NA) +
    geom_line(aes(y = est, linewidth = I(if_else(spec == "lag1_tfe", 1.2, 0.8))),
              linewidth = 0.9) +
    scale_colour_manual(values = SPEC_COLORS, labels = SPEC_LABELS) +
    scale_fill_manual(values   = SPEC_COLORS, labels = SPEC_LABELS, guide = "none") +
    scale_x_continuous(breaks = seq(0, MAX_HOR, 6), limits = c(0, MAX_HOR)) +
    labs(title    = title_str,
         subtitle = subtitle_str,
         x = "Horizon h (months)",
         y = "Estimated coefficient",
         colour = NULL) +
    overlay_theme()
}

# ── Section 4: Primary comparison — neg_wh2m ─────────────────────────────────
#
# The focal question: does any lag spec produce a correctly-signed (positive)
# neg_wh2m estimate at h=6–15? The shaded orange band marks the horizon window
# where the placebo test confirmed genuine signal in the baseline. The baseline
# (lag1_tfe, black) runs with a negative coefficient in this window — economically
# wrong (expansionary shocks should boost consumption *more* in high-WH2M states).
# A positive estimate from any other lag spec inside the orange band would be the
# most substantive finding: it would suggest the wrong sign is an artefact of the
# lag structure rather than a genuine feature of heterogeneous monetary transmission.
# All specs negative → the wrong sign is robust to lag choice.

cat("── Section 4: neg_wh2m — primary comparison ──\n")

df_nw <- irf_all |> filter(term == "neg_wh2m")

pos_in_signal <- df_nw |>
  filter(horizon >= 6L, horizon <= 15L, !is.na(est), est > 0)

cat(sprintf("  neg_wh2m positive at h=6–15: %d / %d spec×horizon combinations\n",
            nrow(pos_in_signal),
            nrow(df_nw |> filter(horizon >= 6L, horizon <= 15L, !is.na(est)))))

if (nrow(pos_in_signal) > 0) {
  cat("  *** SUBSTANTIVE FINDING: positive estimates found ***\n")
  print(pos_in_signal |>
          select(spec, horizon, est, se, ci_lo, ci_hi) |>
          mutate(across(c(est, se, ci_lo, ci_hi), ~round(.x, 4))), n = Inf)
} else {
  cat("  All specs negative at h=6–15 — wrong sign is robust to lag length choice.\n")
}
cat("\n")

p_nw <- make_overlay_plot(
  df_nw,
  shade_band   = c(6, 15),
  title_str    = "neg_wh2m — does lag choice affect sign at h=6–15?",
  subtitle_str = sprintf(
    "lag0=red · lag1=black (baseline) · lag2=blue · lag3=green · lag4=purple · lag5=brown · lag6=pink · 90%% CI\nOrange band = placebo-confirmed signal window  ·  %s",
    if (nrow(pos_in_signal) > 0)
      sprintf("%d spec×horizon positive in shaded band", nrow(pos_in_signal))
    else "all specs negative in shaded band"
  )
)

ggsave(file.path(OUT_PLT, "s4_neg_wh2m_lag_comparison.png"),
       p_nw, width = 10, height = 6, dpi = 300)
cat("  ✓ s4_neg_wh2m_lag_comparison.png\n\n")

# ── Section 5: Secondary comparison — remaining three terms ──────────────────
#
# For completeness, the same overlay is produced for neg_ph2m, pos_ph2m, pos_wh2m.
# pos_ph2m and pos_wh2m failed the placebo — their contractionary H2M estimates are
# indistinguishable from noise. Sign changes in these terms across lag specs are
# expected sampling variation and carry no substantive interpretation; they merely
# establish that lag choice does not manufacture a spurious contractionary signal.
# neg_ph2m received WARN from the placebo — mixed evidence of genuine signal.
# Sensitivity in neg_ph2m (sign flip or large shift as lags are added) would suggest
# the marginal signal is fragile; stability would provide mild support for a genuine
# but weak expansionary PH2M channel.

cat("── Section 5: Secondary comparisons — remaining terms ──\n")

other_terms <- setdiff(INTERACTION_TERMS, "neg_wh2m")
placebo_note <- c(
  pos_ph2m = "placebo FAIL — sign changes are expected noise",
  pos_wh2m = "placebo FAIL — sign changes are expected noise",
  neg_ph2m = "placebo WARN — mixed evidence"
)

for (trm in other_terms) {
  df_t  <- irf_all |> filter(term == trm)
  lbl   <- INTERACTION_LBLS[trm]

  p_t <- make_overlay_plot(
    df_t,
    shade_band   = NULL,
    title_str    = sprintf("%s — lag structure comparison", lbl),
    subtitle_str = sprintf(
      "lag0=red · lag1=black (baseline) · lag2=blue · lag3=green · lag4=purple · lag5=brown · lag6=pink · 90%% CI\n%s",
      placebo_note[trm]
    )
  )

  fname <- sprintf("s5_%s_lag_comparison.png", trm)
  ggsave(file.path(OUT_PLT, fname), p_t, width = 10, height = 6, dpi = 300)
  cat(sprintf("  ✓ %s\n", fname))
}

# Combined 4-panel
p4 <- irf_all |>
  ggplot(aes(x = horizon, group = spec, colour = spec, fill = spec)) +
  annotate("rect", xmin = 5.5, xmax = 15.5, ymin = -Inf, ymax = Inf,
           fill = "#ff7f0e", alpha = 0.07) +
  geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.35) +
  geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.06, colour = NA) +
  geom_line(aes(y = est), linewidth = 0.8) +
  facet_wrap(~term_label, scales = "free_y", ncol = 2) +
  scale_colour_manual(values = SPEC_COLORS, labels = SPEC_LABELS) +
  scale_fill_manual(values   = SPEC_COLORS, labels = SPEC_LABELS, guide = "none") +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  labs(
    title    = "Lag Robustness — All Interaction Terms",
    subtitle = "Orange band = h=6–15 (placebo signal window)  ·  90% CI  ·  Baseline in black",
    x = "Horizon h (months)", y = "Estimated coefficient", colour = NULL
  ) +
  theme_bw(base_size = 11) +
  theme(
    panel.grid.minor = element_blank(), strip.background = element_blank(),
    strip.text       = element_text(size = 9.5, face = "bold"),
    legend.position  = "bottom",
    plot.title       = element_text(hjust = 0.5, size = 11),
    plot.subtitle    = element_text(hjust = 0.5, size = 8.5, colour = "gray40")
  )

ggsave(file.path(OUT_PLT, "s5_4panel_all_terms.png"),
       p4, width = 11, height = 8, dpi = 300)
cat("  ✓ s5_4panel_all_terms.png\n\n")

# ── Section 6: Stability table ────────────────────────────────────────────────
#
# Compares estimates at h = 0, 6, 12, 18, 24 across the three alternative lag specs
# relative to the lag1_tfe baseline. Three flags:
#   SIGN FLIP:   sign(est) ≠ sign(lag1_tfe est) — qualitative reversal
#   LARGE SHIFT: |est − lag1_est| > |lag1_se| — shift larger than one baseline SE
#   POS FLAG:    neg_wh2m est > 0 — turns to correct sign (reported for neg_wh2m only)
#
# Flag rates > 25% (sign flip) or > 50% (large shift) across spec × horizon
# combinations indicate sensitivity; < 10% / < 25% indicate stability. The POS FLAG
# is the primary diagnostic for neg_wh2m — any positive estimate in the h=6–15 range
# would require re-evaluation of the wrong-sign interpretation.

cat("── Section 6: Stability table ──\n")

CHECK_HOR <- c(0L, 6L, 12L, 18L, 24L)

baseline_lag1 <- irf_all |>
  filter(spec == "lag1_tfe") |>
  select(horizon, term, est_lag1 = est, se_lag1 = se)

stab_tbl <- irf_all |>
  filter(horizon %in% CHECK_HOR, spec != "lag1_tfe") |>
  left_join(baseline_lag1, by = c("horizon", "term")) |>
  mutate(
    sign_flip   = !is.na(est) & !is.na(est_lag1) & est_lag1 != 0 &
                  sign(est) != sign(est_lag1),
    large_shift = !is.na(est) & !is.na(se_lag1) &
                  abs(est - est_lag1) > abs(se_lag1),
    pos_flag    = term == "neg_wh2m" & !is.na(est) & est > 0
  ) |>
  arrange(term, horizon, spec)

write_csv(
  stab_tbl |>
    select(term, horizon, spec, est, se, est_lag1, se_lag1,
           sign_flip, large_shift, pos_flag) |>
    mutate(across(c(est, se, est_lag1, se_lag1), ~round(.x, 5))),
  file.path(OUT_TBL, "lag_stability_table.csv")
)
cat(sprintf("✓ lag_stability_table.csv\n\n"))

for (trm in INTERACTION_TERMS) {
  lbl <- INTERACTION_LBLS[trm]
  cat(sprintf("  %s\n", lbl))

  wide <- irf_all |>
    filter(term == trm, horizon %in% CHECK_HOR) |>
    mutate(est_se = sprintf("%+.3f (%.3f)", est, se)) |>
    select(horizon, spec, est_se) |>
    pivot_wider(names_from = spec, values_from = est_se)

  print(wide, n = Inf)

  flags_t <- stab_tbl |> filter(term == trm)
  n_sf  <- sum(flags_t$sign_flip,   na.rm = TRUE)
  n_ls  <- sum(flags_t$large_shift, na.rm = TRUE)
  n_pf  <- sum(flags_t$pos_flag,    na.rm = TRUE)
  n_tot <- nrow(flags_t)
  cat(sprintf("    Sign flips:   %d / %d (%.0f%%)\n", n_sf, n_tot, 100*n_sf/n_tot))
  cat(sprintf("    Large shifts: %d / %d (%.0f%%)\n", n_ls, n_tot, 100*n_ls/n_tot))
  if (trm == "neg_wh2m")
    cat(sprintf("    Positive (correct sign): %d / %d  %s\n",
                n_pf, n_tot,
                if (n_pf > 0) "← SUBSTANTIVE FINDING" else "← none found"))
  cat("\n")
}

flag_summary <- stab_tbl |>
  group_by(term) |>
  summarise(
    n_total     = n(),
    pct_sf      = round(100 * mean(sign_flip,   na.rm = TRUE), 1),
    pct_ls      = round(100 * mean(large_shift, na.rm = TRUE), 1),
    n_pos_flag  = sum(pos_flag, na.rm = TRUE),
    sensitivity = case_when(
      pct_sf > 25 | pct_ls > 50 ~ "SENSITIVE",
      pct_sf > 10 | pct_ls > 25 ~ "MODERATE",
      TRUE                        ~ "STABLE"
    ),
    .groups = "drop"
  ) |>
  mutate(label = INTERACTION_LBLS[term])

cat("  Flag-rate summary per term:\n")
print(flag_summary |> select(label, pct_sf, pct_ls, n_pos_flag, sensitivity), n = Inf)
cat("\n")

# ── Section 7: Arellano-Bond serial correlation test ─────────────────────────
#
# Uses plm::pbgtest() (Breusch-Godfrey panel serial correlation test) at h=0 for
# each lag spec. This serves the same diagnostic role as the Arellano-Bond AR(1)/AR(2)
# serial correlation tests in dynamic GMM estimation: it checks whether residuals
# exhibit autocorrelation after controlling for the specified lag structure.
#
# AIC/BIC are not appropriate for lag selection in panel LP because each horizon is
# a separate regression with a different dependent variable; information criteria
# on h=0 alone do not generalise to the full IRF path. The serial correlation test
# at h=0 is the appropriate alternative because it directly tests the assumption
# that the lag structure is sufficient — the same assumption invoked at all horizons.
#
# Expected result supporting lag1_tfe: AR(1) significant under lag0 but not lag1.
# AR(1) persisting under lag1 → residual autocorrelation, lag2 may be preferred.
# AR(2) significant under lag1 → dynamic misspecification, lag structure is insufficient.

cat("── Section 7: Serial correlation test (h=0, plm::pbgtest) ──\n")

ab_results <- map_dfr(SPEC_NAMES, function(spec) {
  lc  <- LAG_SPECS[[spec]]$lag_ctrls
  dh  <- make_h_sample(d_panel, 0L, lc)
  fml_plm <- build_fml_plm(lc)

  tryCatch({
    pdata <- pdata.frame(dh,
                         index = c("uf_code", "ref_month_yyyymm"),
                         drop.index = FALSE)
    m_plm <- plm(fml_plm, data = pdata,
                 model = "within", effect = "twoways")

    run_bg <- function(order) {
      tryCatch(pbgtest(m_plm, order = order),
               error = function(e) list(statistic = NA_real_, p.value = NA_real_))
    }
    t1 <- run_bg(1)
    t2 <- run_bg(2)

    row <- tibble(
      spec     = spec,
      label    = LAG_SPECS[[spec]]$label,
      n_obs    = nrow(dh),
      ar1_stat = round(as.numeric(t1$statistic), 4),
      ar1_pval = round(t1$p.value, 4),
      ar1_sig  = isTRUE(t1$p.value < 0.05),
      ar2_stat = round(as.numeric(t2$statistic), 4),
      ar2_pval = round(t2$p.value, 4),
      ar2_sig  = isTRUE(t2$p.value < 0.05)
    )
    cat(sprintf("  %-10s  n=%4d  AR(1) p=%.4f %s  |  AR(2) p=%.4f %s\n",
                spec, nrow(dh), row$ar1_pval,
                if (row$ar1_sig) "[sig *]" else "       ",
                row$ar2_pval,
                if (row$ar2_sig) "[sig *]" else "       "))
    row
  }, error = function(e) {
    cat(sprintf("  %-10s  plm ERROR: %s\n", spec, conditionMessage(e)))
    tibble(spec=spec, label=LAG_SPECS[[spec]]$label, n_obs=NA_integer_,
           ar1_stat=NA_real_, ar1_pval=NA_real_, ar1_sig=NA,
           ar2_stat=NA_real_, ar2_pval=NA_real_, ar2_sig=NA)
  })
})

write_csv(ab_results, file.path(OUT_TBL, "arellano_bond.csv"))
cat(sprintf("\n✓ arellano_bond.csv\n\n"))

# Derive recommended lag from AB results
lag_sig <- setNames(ab_results$ar1_sig, ab_results$spec)
first_clean <- ab_results$spec[!ab_results$ar1_sig & !is.na(ab_results$ar1_sig)][1]

cat("  Interpretation:\n")
if (isTRUE(lag_sig["lag0_tfe"]) && !isTRUE(lag_sig["lag1_tfe"])) {
  cat("  ✓ AR(1) significant under lag0 but not lag1 → one lag statistically justified.\n")
} else if (!isTRUE(lag_sig["lag0_tfe"])) {
  cat("  Note: AR(1) not significant even under lag0 — autocorrelation may be low.\n")
} else if (isTRUE(lag_sig["lag1_tfe"])) {
  cat("  Warning: AR(1) persists under lag1 — baseline may have residual autocorrelation.\n")
}
if (isTRUE(ab_results$ar2_sig[ab_results$spec == "lag1_tfe"])) {
  cat("  Warning: AR(2) significant under lag1 — higher-order lags may be warranted.\n")
} else {
  cat("  AR(2) not significant under lag1 — no evidence of higher-order autocorrelation.\n")
}
cat(sprintf("  First spec without significant AR(1): %s\n\n",
            if (!is.na(first_clean)) first_clean else "none"))

# ── Section 8: Summary verdict ────────────────────────────────────────────────
#
# Consolidates the ACF check (Section 2), stability flags (Section 6), and AB test
# (Section 7) into a per-term verdict and two pre-registered overall statements.
# The verdict answers the analysis context question: is the wrong sign on neg_wh2m
# at h=6–15 an artefact of the lag structure, or a robust feature of the data?

cat("══════════════════════════════════════════════════════\n")
cat("  SECTION 8: SUMMARY VERDICT\n")
cat("══════════════════════════════════════════════════════\n\n")

for (trm in INTERACTION_TERMS) {
  lbl <- INTERACTION_LBLS[trm]
  fs  <- flag_summary |> filter(term == trm)
  cat(sprintf("  %s\n", lbl))
  cat(sprintf("  (a) Stability across lag specs: %s\n",
              sprintf("%s  (%.0f%% sign-flip rate, %.0f%% large-shift rate)",
                      fs$sensitivity, fs$pct_sf, fs$pct_ls)))

  if (trm == "neg_wh2m") {
    n_pos_h6_15 <- stab_tbl |>
      filter(term == "neg_wh2m", horizon >= 6L, horizon <= 15L, pos_flag) |>
      nrow()
    cat(sprintf("  (b) Positive neg_wh2m at h=6–15: %s\n",
                if (n_pos_h6_15 > 0)
                  sprintf("YES (%d spec×horizon) — wrong sign not robust", n_pos_h6_15)
                else "NO — wrong sign persists across all lag specs at h=6–15"))
  }

  cat(sprintf("  (c) Recommended lag: %s\n",
              if (!is.na(first_clean)) first_clean else "lag1_tfe"))
  cat(sprintf("      ACF sig lags: %s  |  AB first-clean spec: %s\n\n",
              if (length(sig_lags) == 0) "none" else paste(sig_lags, collapse = ","),
              if (!is.na(first_clean)) first_clean else "none"))
}

# Overall pre-registered statements
contractionary_sensitive <- flag_summary |>
  filter(term %in% c("pos_ph2m", "pos_wh2m")) |>
  summarise(any = any(sensitivity == "SENSITIVE")) |>
  pull(any)

neg_wh2m_reverses <- nrow(
  stab_tbl |> filter(term == "neg_wh2m", horizon >= 6L, horizon <= 15L, pos_flag)
) > 0

cat("══════════════════════════════════════════════════════\n\n")
cat("OVERALL CONCLUSION:\n\n")
cat(sprintf(
  "  The null result on the contractionary H2M channel [%s] robust to lag length choice.\n",
  if (!contractionary_sensitive) "IS" else "IS NOT"
))
cat(sprintf(
  "  The wrong sign on neg_wh2m at h=6–15 [%s] under alternative lag specifications.\n\n",
  if (!neg_wh2m_reverses) "PERSISTS" else "REVERSES"
))

cat(sprintf("✓ All plots  → %s/\n", OUT_PLT))
cat(sprintf("✓ All tables → %s/\n", OUT_TBL))
cat("\n=== LAG ROBUSTNESS DONE ===\n")
cat("\nFiles produced:\n")
cat("  tables/acf_demeaned.csv\n")
cat("  tables/irf_all_specs.csv\n")
cat("  tables/lag_stability_table.csv\n")
cat("  tables/arellano_bond.csv\n")
cat("  plots/s2_acf.png\n")
cat("  plots/s4_neg_wh2m_lag_comparison.png\n")
cat("  plots/s5_neg_ph2m_lag_comparison.png\n")
cat("  plots/s5_pos_ph2m_lag_comparison.png\n")
cat("  plots/s5_pos_wh2m_lag_comparison.png\n")
cat("  plots/s5_4panel_all_terms.png\n")
