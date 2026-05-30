#!/usr/bin/env Rscript
# State FE vs TWFE Comparison — OLS Baseline with Directional Shock Splitting
#
# Gap filled: the lpirfs benchmark scripts (celina_lp_lpirfs_benchmark.r etc.)
# already compare state FE vs TWFE for the lpirfs-based specs. This script
# adds the same comparison for the OLS baseline with eps_rr directional
# splitting — the spec that all placebo, lag robustness, and band diagnostics
# have been run on.
#
# Key econometric point: eps_rr_pos and eps_rr_neg_abs are national-level
# time-series variables (same value for all states in each month). Under TWFE
# they are in the column space of factor(ref_month_yyyymm) and must be EXCLUDED
# from Version B's formula — if left in, R's QR decomposition keeps them first
# and drops two time-FE dummies instead, leaving the time FEs incomplete.
# In Version A (state FE only) they are identified from national time-series
# variation. Only Version A recovers the average national transmission effect.
#
# Visual convention matches celina_lp_lpirfs_benchmark.r:
#   State FE only → dashed "22", blue
#   TWFE          → solid, black
#
# Run from project root:
#   Rscript scripts/reporting/celina_fe_comparison_ols.r

suppressPackageStartupMessages({
  library(tidyverse)
  library(sandwich)
})

cat("\n=== STATE FE vs TWFE — OLS BASELINE (DIRECTIONAL SHOCK SPLIT) ===\n\n")

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_HOR  <- 24L
CI_MULT  <- qnorm(0.95)           # 90% two-sided CI
OUT_PLT  <- "results/plots/fe_comparison_ols"
OUT_TBL  <- "results/tables/fe_comparison_ols"
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)

# ── Load and prep data ────────────────────────────────────────────────────────
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
    log_consumption  = log(consumption_index),
    log_bf           = log(coalesce(total_value_BF_old, 0) + 1),
    log_real_imports = log(coalesce(real_imports, 0) + 1),
    log_real_exports = log(coalesce(real_exports, 0) + 1),
    infl_yoy         = (ipca_index / dplyr::lag(ipca_index, 12) - 1) * 100,
    lag1_lc          = lag1_log_consumption,
    lag1_share_ph2m  = lag1_share_PH2M,
    lag1_share_wh2m  = lag1_share_WH2M
  ) |>
  ungroup() |>
  mutate(
    eps_rr_pos     = pmax(eps_rr, 0),
    eps_rr_neg_abs = pmax(-eps_rr, 0),
    pos_ph2m       = eps_rr_pos     * lag1_share_ph2m,
    pos_wh2m       = eps_rr_pos     * lag1_share_wh2m,
    neg_ph2m       = eps_rr_neg_abs * lag1_share_ph2m,
    neg_wh2m       = eps_rr_neg_abs * lag1_share_wh2m
  )

# Pre-compute SDs for 1-SD scaling
neg_abs_sd  <- sd(d_panel$eps_rr_neg_abs, na.rm = TRUE)
pos_sd      <- sd(d_panel$eps_rr_pos,     na.rm = TRUE)
wh2m_sd_bw  <- d_panel |>           # between-state SD of WH2M share (for Section 5)
  group_by(uf_code) |>
  summarise(m = mean(lag1_share_wh2m, na.rm = TRUE), .groups = "drop") |>
  pull(m) |> sd()

cat(sprintf("  SD(eps_rr_neg_abs) = %.4f  |  SD(eps_rr_pos) = %.4f\n",
            neg_abs_sd, pos_sd))
cat(sprintf("  Between-state SD(WH2M share) = %.4f\n\n", wh2m_sd_bw))

# ── Term definitions ──────────────────────────────────────────────────────────
MAIN_TERMS   <- c("eps_rr_pos", "eps_rr_neg_abs")
INT_TERMS    <- c("pos_ph2m", "pos_wh2m", "neg_ph2m", "neg_wh2m")
CONTROLS     <- c("lag1_share_ph2m", "lag1_share_wh2m",
                  "log_real_imports", "log_real_exports",
                  "infl_yoy", "log_bf", "lag1_lc")

INT_LABELS <- c(
  pos_ph2m = "Contractionary × PH2M",
  pos_wh2m = "Contractionary × WH2M",
  neg_ph2m = "Expansionary × PH2M",
  neg_wh2m = "Expansionary × WH2M"
)

REQUIRED_COLS <- c("y_h", MAIN_TERMS, INT_TERMS, CONTROLS,
                   "uf_code", "ref_month_yyyymm")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Specification definitions and estimation loop
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 1: Specification definitions ──\n\n")

# Version A — State FE only (individual)
# eps_rr_pos and eps_rr_neg_abs identified from national time-series variation.
# Produces estimates for both main effects and interaction terms.
#
# Version B — TWFE (twoways)
# Main effects EXCLUDED: they are in the column space of factor(ref_month_yyyymm).
# Including them would cause R to drop 2 time-FE dummies rather than the main
# effects (QR ordering keeps earlier terms), leaving the time FEs incomplete.
# Only the interaction terms — which vary cross-sectionally — are identified.

PE_SPECS <- list(
  individual = list(
    pe        = "individual",
    label     = "State FE only",
    pe_label  = "State FE",
    color     = "#1f77b4",
    ltype     = "22",
    terms     = c(MAIN_TERMS, INT_TERMS),
    fml_rhs   = paste(
      paste(c(MAIN_TERMS, INT_TERMS, CONTROLS), collapse = " + "),
      "+ factor(uf_code)"
    )
  ),
  twoways = list(
    pe        = "twoways",
    label     = "TWFE",
    pe_label  = "Two-way FE",
    color     = "black",
    ltype     = "solid",
    terms     = INT_TERMS,     # main effects absorbed by time FEs → not included
    fml_rhs   = paste(
      paste(c(INT_TERMS, CONTROLS), collapse = " + "),
      "+ factor(uf_code) + factor(ref_month_yyyymm)"
    )
  )
)

for (spec in PE_SPECS) {
  cat(sprintf("  %-14s  formula terms: %s + FEs\n",
              spec$label,
              paste(c(MAIN_TERMS[MAIN_TERMS %in% spec$terms], INT_TERMS,
                      "[controls]"), collapse = ", ")))
}
cat("\n")

# ── H-sample builder ──────────────────────────────────────────────────────────
make_h_sample <- function(d, h) {
  dh <- d |>
    group_by(uf_code) |>
    arrange(t_index) |>
    mutate(log_cons_lead = dplyr::lead(log_consumption, h)) |>
    ungroup() |>
    mutate(y_h = log_cons_lead - lag1_lc) |>
    filter(!is.na(y_h), !is.na(eps_rr),
           !is.na(lag1_share_ph2m), !is.na(lag1_share_wh2m),
           !is.na(infl_yoy), !is.na(log_bf),
           !is.na(log_real_imports), !is.na(log_real_exports),
           !is.na(lag1_lc))
  # Drop singletons
  dh |>
    group_by(uf_code)          |> filter(n() > 1) |> ungroup() |>
    group_by(ref_month_yyyymm) |> filter(n() > 1) |> ungroup()
}

# ── Estimation ────────────────────────────────────────────────────────────────
cat("── Estimation: 2 specs × 25 horizons ──\n")

irf_all <- map_dfr(PE_SPECS, function(spec) {
  fml <- as.formula(paste("y_h ~", spec$fml_rhs))
  cat(sprintf("  %s:", spec$label))

  h_res <- map_dfr(0L:MAX_HOR, function(h) {
    dh <- make_h_sample(d_panel, h)
    if (nrow(dh) < 50) return(NULL)

    m  <- suppressWarnings(lm(fml, data = dh))
    vc <- vcovCL(m, cluster = dh$uf_code, type = "HC1")
    cf <- coef(m)
    se <- sqrt(diag(vc))

    if (h %% 6 == 0) cat(sprintf(" h%02d", h))

    map_dfr(spec$terms, function(trm) {
      if (!trm %in% names(cf) || is.na(cf[trm])) {
        return(tibble(pe = spec$pe, pe_label = spec$pe_label,
                      horizon = h, term = trm, n_obs = nrow(dh),
                      est = NA_real_, se = NA_real_,
                      ci_lo = NA_real_, ci_hi = NA_real_))
      }
      e <- cf[trm]; s <- se[trm]
      tibble(pe = spec$pe, pe_label = spec$pe_label,
             horizon = h, term = trm, n_obs = nrow(dh),
             est = e, se = s,
             ci_lo = e - CI_MULT * s, ci_hi = e + CI_MULT * s)
    })
  })
  cat("\n")
  h_res
})

cat("\n")

# Label factors
SPEC_LABELS  <- setNames(map_chr(PE_SPECS, "pe_label"),   names(PE_SPECS))
SPEC_COLORS  <- setNames(map_chr(PE_SPECS, "color"),      map_chr(PE_SPECS, "pe_label"))
SPEC_LTYPES  <- setNames(map_chr(PE_SPECS, "ltype"),      map_chr(PE_SPECS, "pe_label"))

irf_all <- irf_all |>
  mutate(
    pe_label = factor(pe_label, levels = c("Two-way FE", "State FE")),
    int_label = INT_LABELS[term]
  )

write_csv(irf_all |> select(-int_label),
          file.path(OUT_TBL, "irf_fe_comparison_ols_all.csv"))
cat(sprintf("✓ irf_fe_comparison_ols_all.csv (%d rows)\n\n", nrow(irf_all)))

# ── Common plot theme ─────────────────────────────────────────────────────────
fe_theme <- function() {
  theme_bw(base_size = 11) +
    theme(
      panel.grid.minor       = element_blank(),
      panel.grid.major       = element_line(colour = "gray93", linewidth = 0.3),
      legend.position        = "bottom",
      legend.title           = element_blank(),
      plot.title             = element_text(hjust = 0.5, size = 11),
      plot.subtitle          = element_text(hjust = 0.5, size = 8.5, colour = "gray40"),
      strip.background       = element_blank(),
      strip.text             = element_text(size = 9.5, face = "bold")
    )
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: National transmission — Version A main effects only
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 2: National transmission (Version A main effects) ──\n")

main_irf <- irf_all |>
  filter(pe == "individual", term %in% MAIN_TERMS, !is.na(est)) |>
  mutate(
    est_1sd   = est   * if_else(term == "eps_rr_neg_abs", neg_abs_sd, pos_sd),
    ci_lo_1sd = ci_lo * if_else(term == "eps_rr_neg_abs", neg_abs_sd, pos_sd),
    ci_hi_1sd = ci_hi * if_else(term == "eps_rr_neg_abs", neg_abs_sd, pos_sd),
    term_label = case_when(
      term == "eps_rr_pos"     ~ "Contractionary shock (eps_rr_pos)",
      term == "eps_rr_neg_abs" ~ "Expansionary shock (eps_rr_neg_abs)"
    )
  )

# Peak response and sign flags
for (trm in MAIN_TERMS) {
  sub <- main_irf |> filter(term == trm)
  if (nrow(sub) == 0) next
  peak_h <- sub$horizon[which.max(abs(sub$est_1sd))]
  peak_v <- sub$est_1sd[which.max(abs(sub$est_1sd))]
  cat(sprintf("  %-18s  peak at h=%d: %.4f (1-SD units)\n", trm, peak_h, peak_v))
  if (trm == "eps_rr_neg_abs" && any(sub$est_1sd[sub$horizon %in% 0:6] < 0, na.rm = TRUE)) {
    cat(sprintf("  *** FLAG: eps_rr_neg_abs is NEGATIVE at h=0–6 — rate cuts associated\n"))
    cat(sprintf("      with consumption DECLINE → consistent with recession-signal interpretation\n"))
  }
}
cat("\n")

p_main <- ggplot(main_irf, aes(x = horizon, y = est_1sd)) +
  geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_lo_1sd, ymax = ci_hi_1sd), alpha = 0.15, fill = "#1f77b4") +
  geom_line(colour = "#1f77b4", linewidth = 0.9) +
  facet_wrap(~term_label, nrow = 1, scales = "free_y") +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  labs(
    title    = "Section 2: Average National Transmission — State FE Only (Version A)",
    subtitle = sprintf(
      "eps_rr_pos scaled by SD=%.4f  ·  eps_rr_neg_abs scaled by SD=%.4f  ·  90%% CI\n(Version B cannot estimate these: absorbed by year-month FEs)",
      pos_sd, neg_abs_sd
    ),
    x = "Horizon h (months)", y = "Cumulative log response (1-SD shock)"
  ) +
  fe_theme()

ggsave(file.path(OUT_PLT, "s2_national_transmission.png"),
       p_main, width = 11, height = 5.5, dpi = 300)
cat("  ✓ s2_national_transmission.png\n\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Interaction term overlay — solid (TWFE) vs dashed (State FE)
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 3: Interaction term overlay ──\n")

int_irf <- irf_all |>
  filter(term %in% INT_TERMS, !is.na(est)) |>
  mutate(int_label = factor(INT_LABELS[term], levels = unname(INT_LABELS)))

# neg_wh2m sign check at h=6-15
nw_check <- int_irf |>
  filter(term == "neg_wh2m", horizon >= 6L, horizon <= 15L)
cat("  neg_wh2m sign at h=6-15:\n")
for (p_lbl in levels(nw_check$pe_label)) {
  sub <- nw_check |> filter(pe_label == p_lbl)
  n_pos <- sum(sub$est > 0, na.rm = TRUE)
  cat(sprintf("    %-12s  positive %d/%d horizons  (wrong sign = %d/%d)\n",
              p_lbl, n_pos, nrow(sub), nrow(sub) - n_pos, nrow(sub)))
}
cat("\n")

p_int <- ggplot(int_irf,
                aes(x = horizon, y = est,
                    colour = pe_label, fill = pe_label,
                    linetype = pe_label)) +
  annotate("rect", xmin = 5.5, xmax = 15.5, ymin = -Inf, ymax = Inf,
           fill = "#ff7f0e", alpha = 0.08) +
  geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.35) +
  geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.10, colour = NA) +
  geom_line(linewidth = 0.9) +
  facet_wrap(~int_label, scales = "free_y", ncol = 2) +
  scale_colour_manual(values = SPEC_COLORS) +
  scale_fill_manual(values   = SPEC_COLORS, guide = "none") +
  scale_linetype_manual(values = SPEC_LTYPES) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  labs(
    title    = "Section 3: State FE vs TWFE — Interaction Term IRFs",
    subtitle = "Solid black = TWFE  ·  Dashed blue = State FE only  ·  90% CI\nOrange band = h=6–15 (placebo-confirmed signal window for neg_wh2m)",
    x = "Horizon h (months)", y = "Estimated coefficient"
  ) +
  fe_theme() +
  theme(legend.position = "bottom")

ggsave(file.path(OUT_PLT, "s3_interaction_overlay_4panel.png"),
       p_int, width = 11, height = 8, dpi = 300)
cat("  ✓ s3_interaction_overlay_4panel.png\n\n")

# Individual overlays for each interaction term
for (trm in INT_TERMS) {
  lbl <- INT_LABELS[trm]
  p_t <- ggplot(int_irf |> filter(term == trm),
                aes(x = horizon, y = est,
                    colour = pe_label, fill = pe_label, linetype = pe_label)) +
    { if (trm == "neg_wh2m")
        annotate("rect", xmin = 5.5, xmax = 15.5, ymin = -Inf, ymax = Inf,
                 fill = "#ff7f0e", alpha = 0.09)
      else list() } +
    geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.12, colour = NA) +
    geom_line(linewidth = 0.9) +
    scale_colour_manual(values = SPEC_COLORS) +
    scale_fill_manual(values   = SPEC_COLORS, guide = "none") +
    scale_linetype_manual(values = SPEC_LTYPES) +
    scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
    labs(title = sprintf("Section 3: %s — State FE vs TWFE", lbl),
         subtitle = "Solid black = TWFE  ·  Dashed blue = State FE only  ·  90% CI",
         x = "Horizon h (months)", y = "Estimated coefficient") +
    fe_theme()
  ggsave(file.path(OUT_PLT, sprintf("s3_%s_overlay.png", trm)),
         p_t, width = 9, height = 5.5, dpi = 300)
  cat(sprintf("  ✓ s3_%s_overlay.png\n", trm))
}
cat("\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Decomposition table at selected horizons
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 4: Decomposition table ──\n\n")

CHECK_HOR <- c(0L, 6L, 12L, 18L, 24L)

baseline_twfe <- irf_all |>
  filter(pe == "twoways", horizon %in% CHECK_HOR) |>
  select(horizon, term, est_twfe = est, se_twfe = se)

baseline_sfe <- irf_all |>
  filter(pe == "individual", horizon %in% CHECK_HOR) |>
  select(horizon, term, est_sfe = est, se_sfe = se)

decomp_tbl <- inner_join(baseline_sfe, baseline_twfe, by = c("horizon", "term")) |>
  mutate(
    diff_abs      = est_twfe - est_sfe,
    diff_sfe_se   = if_else(!is.na(se_sfe) & se_sfe > 0,
                             diff_abs / se_sfe, NA_real_),
    large_diff    = !is.na(diff_sfe_se) & abs(diff_sfe_se) > 1,
    across(c(est_sfe, se_sfe, est_twfe, se_twfe, diff_abs, diff_sfe_se),
           ~round(.x, 5))
  ) |>
  arrange(term, horizon)

write_csv(decomp_tbl, file.path(OUT_TBL, "decomp_table_ols.csv"))
cat("  ✓ decomp_table_ols.csv\n\n")

for (trm in INT_TERMS) {
  cat(sprintf("  %s:\n", INT_LABELS[trm]))
  decomp_tbl |>
    filter(term == trm) |>
    transmute(h = horizon,
              `State FE est` = est_sfe,
              `TWFE est`     = est_twfe,
              `Diff`         = diff_abs,
              `Diff/SE`      = round(diff_sfe_se, 2),
              flag           = if_else(large_diff, "* >1 SE", "")) |>
    print(n = Inf)
  cat("\n")
}

n_large <- sum(decomp_tbl$large_diff, na.rm = TRUE)
n_total <- sum(!is.na(decomp_tbl$diff_sfe_se))
cat(sprintf("  Large differences (>1 baseline SE): %d / %d spec×horizon combinations\n\n",
            n_large, n_total))

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Key comparison — national effect vs WH2M differential
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 5: National effect (Version A) vs WH2M differential (Version B) ──\n")

# Scaling:
#   eps_rr_neg_abs (Version A): multiply by SD(eps_rr_neg_abs)
#     → average response across states to 1-SD expansionary shock
#   neg_wh2m (Version B): multiply by SD(eps_rr_neg_abs)
#     → per unit of WH2M share, the EXTRA response to 1-SD shock
#     To get "at mean WH2M state" multiply further by between-SD(WH2M share);
#     here we scale by SD(eps_rr_neg_abs) only — same shock, different channel
s5_df <- bind_rows(
  irf_all |>
    filter(pe == "individual", term == "eps_rr_neg_abs", !is.na(est)) |>
    mutate(
      series    = "Aggregate: eps_rr_neg_abs (State FE)",
      colour    = "#1f77b4",
      est_sc    = est   * neg_abs_sd,
      ci_lo_sc  = ci_lo * neg_abs_sd,
      ci_hi_sc  = ci_hi * neg_abs_sd
    ),
  irf_all |>
    filter(pe == "twoways", term == "neg_wh2m", !is.na(est)) |>
    mutate(
      series    = "Differential: neg_wh2m (TWFE)",
      colour    = "black",
      est_sc    = est   * neg_abs_sd,
      ci_lo_sc  = ci_lo * neg_abs_sd,
      ci_hi_sc  = ci_hi * neg_abs_sd
    )
)

both_negative_h6_15 <- s5_df |>
  filter(horizon >= 6L, horizon <= 15L) |>
  group_by(series) |>
  summarise(all_neg = all(est_sc < 0, na.rm = TRUE), .groups = "drop")

cat("  Sign at h=6-15:\n")
for (i in seq_len(nrow(both_negative_h6_15))) {
  cat(sprintf("    %-42s  all negative: %s\n",
              both_negative_h6_15$series[i],
              both_negative_h6_15$all_neg[i]))
}

if (all(both_negative_h6_15$all_neg)) {
  cat("  → Both negative: recession-signal interpretation holds at aggregate AND distributional level\n")
} else if (both_negative_h6_15$all_neg[both_negative_h6_15$series == "Differential: neg_wh2m (TWFE)"]) {
  cat("  → Only neg_wh2m negative: wrong sign is specific to WH2M heterogeneity, not aggregate\n")
} else {
  cat("  → Mixed signs: recession-signal interpretation partial\n")
}
cat("\n")

p_s5 <- ggplot(s5_df,
               aes(x = horizon, y = est_sc, colour = series, linetype = series)) +
  annotate("rect", xmin = 5.5, xmax = 15.5, ymin = -Inf, ymax = Inf,
           fill = "#ff7f0e", alpha = 0.08) +
  geom_hline(yintercept = 0, colour = "gray30", linetype = "dashed", linewidth = 0.4) +
  geom_ribbon(aes(ymin = ci_lo_sc, ymax = ci_hi_sc, fill = series),
              alpha = 0.12, colour = NA) +
  geom_line(linewidth = 0.9) +
  scale_colour_manual(
    values = c("Aggregate: eps_rr_neg_abs (State FE)" = "#1f77b4",
               "Differential: neg_wh2m (TWFE)"        = "black")
  ) +
  scale_fill_manual(
    values = c("Aggregate: eps_rr_neg_abs (State FE)" = "#1f77b4",
               "Differential: neg_wh2m (TWFE)"        = "black"),
    guide = "none"
  ) +
  scale_linetype_manual(
    values = c("Aggregate: eps_rr_neg_abs (State FE)" = "22",
               "Differential: neg_wh2m (TWFE)"        = "solid")
  ) +
  scale_x_continuous(breaks = seq(0, MAX_HOR, 6)) +
  labs(
    title    = "Section 5: Aggregate Effect vs WH2M Differential — Both Scaled to 1-SD Shock",
    subtitle = sprintf(
      "Blue dashed = avg national transmission (State FE only)  ·  Black solid = WH2M differential (TWFE)\nScaled by SD(eps_rr_neg_abs)=%.4f  ·  Orange band = h=6–15 (placebo signal window)  ·  90%% CI",
      neg_abs_sd
    ),
    x = "Horizon h (months)", y = "Log response × SD(shock)"
  ) +
  fe_theme()

ggsave(file.path(OUT_PLT, "s5_national_vs_wh2m_differential.png"),
       p_s5, width = 11, height = 5.5, dpi = 300)
cat("  ✓ s5_national_vs_wh2m_differential.png\n\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Partial R² of year-month FEs at h=0
# ══════════════════════════════════════════════════════════════════════════════
cat("── Section 6: Partial R² of year-month FEs at h=0 ──\n\n")

dh0 <- make_h_sample(d_panel, 0L)

fml_sfe  <- as.formula(paste("y_h ~",
                              PE_SPECS$individual$fml_rhs))
fml_twfe <- as.formula(paste("y_h ~",
                              PE_SPECS$twoways$fml_rhs))

m_sfe  <- lm(fml_sfe,  data = dh0)
m_twfe <- lm(fml_twfe, data = dh0)

r2_sfe  <- summary(m_sfe)$r.squared
r2_twfe <- summary(m_twfe)$r.squared
partial_r2 <- (r2_twfe - r2_sfe) / (1 - r2_sfe)

cat(sprintf("  R²  (State FE only)  = %.4f  (%d obs)\n", r2_sfe,  nobs(m_sfe)))
cat(sprintf("  R²  (TWFE)           = %.4f  (%d obs)\n", r2_twfe, nobs(m_twfe)))
cat(sprintf("  Partial R² of year-month FEs = %.4f\n\n", partial_r2))
cat(sprintf(
  "  \"Year-month FEs explain %.1f%% of outcome variation beyond state FEs.\"\n\n",
  partial_r2 * 100
))

if (partial_r2 > 0.30) {
  cat("  → Above 30%: TWFE strongly preferred — common time confounders are substantial.\n")
} else if (partial_r2 > 0.10) {
  cat("  → 10–30%: Moderate confounder control from time FEs — TWFE advisable.\n")
} else {
  cat("  → Below 10%: Time FEs add little beyond state FEs at h=0 — specs will be similar.\n")
}
cat("\n")

# Save R² summary
r2_tbl <- tibble(
  spec          = c("State FE only", "TWFE"),
  r_squared     = c(r2_sfe, r2_twfe),
  n_obs         = c(nobs(m_sfe), nobs(m_twfe)),
  partial_r2_time_fe = c(NA_real_, partial_r2)
)
write_csv(r2_tbl, file.path(OUT_TBL, "partial_r2_ols.csv"))
cat("  ✓ partial_r2_ols.csv\n\n")

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Summary verdict
# ══════════════════════════════════════════════════════════════════════════════
cat("══════════════════════════════════════════════════════\n")
cat("  SECTION 7: SUMMARY\n")
cat("══════════════════════════════════════════════════════\n\n")

# (a) Average national transmission direction from Version A
neg_abs_peak_est <- main_irf |>
  filter(term == "eps_rr_neg_abs") |>
  filter(abs(est_1sd) == max(abs(est_1sd), na.rm = TRUE)) |>
  slice(1)
pos_peak_est <- main_irf |>
  filter(term == "eps_rr_pos") |>
  filter(abs(est_1sd) == max(abs(est_1sd), na.rm = TRUE)) |>
  slice(1)

neg_abs_early_neg <- main_irf |>
  filter(term == "eps_rr_neg_abs", horizon %in% 0:6) |>
  summarise(any_neg = any(est < 0, na.rm = TRUE)) |>
  pull(any_neg)

cat("  (a) Average national transmission (Version A main effects):\n")
cat(sprintf("      eps_rr_neg_abs peak = %.4f at h=%d  (positive = expected expansion)\n",
            neg_abs_peak_est$est_1sd, neg_abs_peak_est$horizon))
cat(sprintf("      eps_rr_pos     peak = %.4f at h=%d\n",
            pos_peak_est$est_1sd, pos_peak_est$horizon))
if (neg_abs_early_neg) {
  cat("      *** RECESSION SIGNAL: eps_rr_neg_abs negative at short horizons —\n")
  cat("          rate cuts associated with consumption decline on average\n")
}
cat("\n")

# (b) neg_wh2m sign change between specs
nw_sfe  <- irf_all |> filter(pe=="individual", term=="neg_wh2m",
                              horizon>=6L, horizon<=15L)
nw_twfe <- irf_all |> filter(pe=="twoways",    term=="neg_wh2m",
                              horizon>=6L, horizon<=15L)
sign_changes <- sum(sign(nw_sfe$est) != sign(nw_twfe$est), na.rm = TRUE)

cat("  (b) neg_wh2m sign at h=6-15:\n")
cat(sprintf("      State FE: %d/%d positive  |  TWFE: %d/%d positive\n",
            sum(nw_sfe$est > 0,  na.rm = TRUE), nrow(nw_sfe),
            sum(nw_twfe$est > 0, na.rm = TRUE), nrow(nw_twfe)))
cat(sprintf("      Sign changes between specs: %d/%d horizons\n",
            sign_changes, min(nrow(nw_sfe), nrow(nw_twfe))))
if (sign_changes == 0) {
  cat("      → No sign change: wrong sign on neg_wh2m is robust to FE choice\n")
} else {
  cat("      → Sign changes present: FE choice materially affects neg_wh2m sign\n")
}
cat("\n")

# (c) Confounder control
cat(sprintf("  (c) Time FE confounder control (partial R² at h=0): %.1f%%\n",
            partial_r2 * 100))
cat(sprintf("      Large interaction term differences (>1 SE): %d/%d checkpoints\n",
            n_large, n_total))
cat("\n")

# (d) Aggregate vs differential direction
cat("  (d) Aggregate vs WH2M differential sign alignment:\n")
for (i in seq_len(nrow(both_negative_h6_15))) {
  cat(sprintf("      %-42s  negative at h=6-15: %s\n",
              both_negative_h6_15$series[i],
              both_negative_h6_15$all_neg[i]))
}
if (all(both_negative_h6_15$all_neg)) {
  cat("      → Both negative: recession-signal holds at aggregate AND distributional level\n")
} else {
  cat("      → Signs diverge: wrong-sign WH2M is not driven by aggregate recession signal\n")
}

cat("\n══════════════════════════════════════════════════════\n\n")
cat(sprintf("✓ All plots  → %s/\n", OUT_PLT))
cat(sprintf("✓ All tables → %s/\n\n", OUT_TBL))
cat("Files produced:\n")
cat("  tables/irf_fe_comparison_ols_all.csv\n")
cat("  tables/decomp_table_ols.csv\n")
cat("  tables/partial_r2_ols.csv\n")
cat("  plots/s2_national_transmission.png\n")
cat("  plots/s3_interaction_overlay_4panel.png\n")
cat("  plots/s3_{term}_overlay.png  (×4)\n")
cat("  plots/s5_national_vs_wh2m_differential.png\n\n")
cat("=== FE COMPARISON OLS DONE ===\n")
