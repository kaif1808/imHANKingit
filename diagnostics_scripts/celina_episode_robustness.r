#!/usr/bin/env Rscript
# Episode Exclusion Robustness — TWFE LP with eps_rr, consumption outcome
#
# Tests whether main heterogeneity results (contractionary/expansionary eps_rr
# × PH2M/WH2M) are robust to excluding three high-volatility macro episodes:
# 2015-16 recession, 2018 electoral uncertainty, 2020 COVID shock.
#
# Specification: cumulative LP-OLS, state + year-month FEs, HC1 state-clustered SEs.
# The time FE absorbs the national average shock; only cross-sectional variation
# in shock × HtM share is identified.
#
# Run from project root:
#   Rscript scripts/reporting/celina_episode_robustness.r
#
# Output:
#   results/plots/episode_robustness/
#   results/tables/episode_robustness/

suppressPackageStartupMessages({
  library(tidyverse)
  library(sandwich)
})

set.seed(42)
cat("\n=== EPISODE EXCLUSION ROBUSTNESS ===\n\n")

CI_MULT     <- qnorm(0.95)   # 90% CI
MAX_HORIZON <- 24L

OUT_PLT <- "results/plots/episode_robustness"
OUT_TBL <- "results/tables/episode_robustness"
dir.create(OUT_PLT, recursive = TRUE, showWarnings = FALSE)
dir.create(OUT_TBL, recursive = TRUE, showWarnings = FALSE)

# ── Load and prepare data ──────────────────────────────────────────────────────

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset_.csv"
if (!file.exists(lp_path)) {
  lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
  if (!file.exists(lp_path)) stop(sprintf("Dataset not found: %s", lp_path))
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
    # Year-over-year inflation from IPCA level index
    infl_yoy         = (ipca_index / lag(ipca_index, 12) - 1) * 100,
    lag1_lc          = lag1_log_consumption
  ) |>
  ungroup() |>
  mutate(
    # Split eps_rr into contractionary (rate hike) and expansionary (cut)
    eps_rr_neg_abs = pmax(-eps_rr, 0),   # contractionary, made positive
    eps_rr_pos     = pmax(eps_rr, 0),    # expansionary
    # Interactions: shock split × lagged state HtM share
    neg_ph2m = eps_rr_neg_abs * lag1_share_PH2M,
    neg_wh2m = eps_rr_neg_abs * lag1_share_WH2M,
    pos_ph2m = eps_rr_pos     * lag1_share_PH2M,
    pos_wh2m = eps_rr_pos     * lag1_share_WH2M
  )

cat(sprintf("  eps_rr_neg_abs nonzero: %d | eps_rr_pos nonzero: %d\n",
            sum(d_panel$eps_rr_neg_abs > 0, na.rm = TRUE),
            sum(d_panel$eps_rr_pos     > 0, na.rm = TRUE)))

# ── Section 1: Episode definitions ────────────────────────────────────────────
#
# Each window captures a macroeconomic episode that may confound identification
# of the monetary policy shock (eps_rr) with other demand or supply shocks.
#
#   crisis_2015 (201501–201612):
#     Dilma Rousseff's fiscal retrenchment, Petrobras scandal, and impeachment.
#     GDP fell ~7% over 2015–16. eps_rr tight monetary policy coincides with
#     recession-driven disinflation rather than demand management; BRL depreciated
#     ~50%, compressing real incomes independently of MP. HtM households may
#     respond to the recession channel, not the MP channel.
#
#   election_2018 (201807–201812):
#     Electoral uncertainty around Bolsonaro's October 2018 election. The BRL
#     depreciated ~15%, credit spreads widened, and the truckers' strike (May 2018)
#     disrupted supply chains. Non-MP financial tightening may be misattributed
#     to eps_rr if the shock absorbs some of this uncertainty.
#
#   covid_2020 (202003–202106):
#     Simultaneous demand collapse, supply disruption, and Brazil's Auxílio
#     Emergencial (~R$600/month) which massively and asymmetrically reached
#     PH2M households. Monetary and fiscal policy were both in extreme,
#     non-linear territory; eps_rr narrative shock may not be valid in this regime.
#     The fiscal transfer confounds consumption responses across HtM types.
#
#   any_episode:
#     Union of all three. Most conservative robustness check — excludes ~30% of
#     the sample and most of the macro volatility. High power cost but cleanest
#     identification if results hold.

d_panel <- d_panel |>
  mutate(
    crisis_2015   = ref_month_yyyymm >= 201501 & ref_month_yyyymm <= 201612,
    election_2018 = ref_month_yyyymm >= 201807 & ref_month_yyyymm <= 201812,
    covid_2020    = ref_month_yyyymm >= 202003 & ref_month_yyyymm <= 202106,
    any_episode   = crisis_2015 | election_2018 | covid_2020
  )

cat("\nEpisode observation counts (state × month):\n")
cat(sprintf("  crisis_2015:   %4d obs  (%.1f%% of panel)\n",
            sum(d_panel$crisis_2015), 100 * mean(d_panel$crisis_2015)))
cat(sprintf("  election_2018: %4d obs  (%.1f%% of panel)\n",
            sum(d_panel$election_2018), 100 * mean(d_panel$election_2018)))
cat(sprintf("  covid_2020:    %4d obs  (%.1f%% of panel)\n",
            sum(d_panel$covid_2020), 100 * mean(d_panel$covid_2020)))
cat(sprintf("  any_episode:   %4d obs  (%.1f%% of panel)\n",
            sum(d_panel$any_episode), 100 * mean(d_panel$any_episode)))

# ── Section 2: Episode descriptives ───────────────────────────────────────────
#
# Diagnoses the identifying variation lost by each exclusion.
#
# High pct_var_in → episode contains a disproportionate share of shock variation
#   (large shocks during the episode). Excluding it loses a lot of statistical
#   power. Results from exclusion should be interpreted cautiously.
# Low pct_var_in → little variation inside the window. Exclusion costs little;
#   if results change anyway, they may have been driven by the episode's confounders
#   even without much shock variation.

nat_eps <- d_panel |>
  distinct(ref_month_yyyymm, eps_rr,
           crisis_2015, election_2018, covid_2020, any_episode)

episode_keys <- c("crisis_2015", "election_2018", "covid_2020", "any_episode")
episode_lbls <- c("2015-16 Recession", "2018 Election", "2020 COVID", "Any Episode")

desc_rows <- map2(episode_keys, episode_lbls, function(key, lbl) {
  inside  <- nat_eps[[key]]
  n_mons  <- sum(inside)
  n_drop  <- n_mons * n_distinct(d_panel$uf_code)
  eps_in  <- nat_eps$eps_rr[inside]
  eps_out <- nat_eps$eps_rr[!inside]
  ss_all  <- sum(nat_eps$eps_rr^2, na.rm = TRUE)
  ss_in   <- sum(eps_in^2, na.rm = TRUE)
  tibble(
    episode     = lbl,
    n_months    = n_mons,
    n_dropped   = n_drop,
    pct_obs     = round(100 * n_drop / nrow(d_panel), 1),
    mean_in     = round(mean(eps_in, na.rm = TRUE), 4),
    sd_in       = round(sd(eps_in, na.rm = TRUE), 4),
    mean_out    = round(mean(eps_out, na.rm = TRUE), 4),
    sd_out      = round(sd(eps_out, na.rm = TRUE), 4),
    pct_var_in  = round(100 * ss_in / ss_all, 1)
  )
})

desc_tbl <- bind_rows(desc_rows)
write_csv(desc_tbl, file.path(OUT_TBL, "episode_descriptives.csv"))

cat("\n── Episode descriptives ──\n")
print(desc_tbl, n = Inf)
cat("  pct_var_in = share of total eps_rr² (variation) falling within the window\n")

# ── Section 3: Baseline LP ─────────────────────────────────────────────────────
# ── Section 4: Episode exclusion robustness ────────────────────────────────────
#
# (Sections 3 and 4 are run jointly through the LP function below)
#
# Full specification:
#   y_{s,t+h} - y_{s,t-1} = α_s + α_t
#     + β1·(eps_neg × PH2M_{s,t-1}) + β2·(eps_neg × WH2M_{s,t-1})
#     + β3·(eps_pos × PH2M_{s,t-1}) + β4·(eps_pos × WH2M_{s,t-1})
#     + γ1·PH2M_{s,t-1} + γ2·WH2M_{s,t-1}
#     + γ3·log_imports + γ4·log_exports + γ5·infl_yoy
#     + γ6·log_bf + γ7·lag1_lc
#     + ε_{s,t+h}
#
# where α_s = state FE, α_t = year-month FE (absorbs national average shock level)
# Clustered SEs: HC1 at state level (27 clusters)

INTERACTION_TERMS <- c("neg_ph2m", "neg_wh2m", "pos_ph2m", "pos_wh2m")
INTERACTION_LBLS  <- c(
  neg_ph2m = "Contractionary × PH2M",
  neg_wh2m = "Contractionary × WH2M",
  pos_ph2m = "Expansionary × PH2M",
  pos_wh2m = "Expansionary × WH2M"
)

CTRL_VARS <- c("lag1_share_PH2M", "lag1_share_WH2M",
               "log_real_imports", "log_real_exports",
               "infl_yoy", "log_bf", "lag1_lc")

run_lp_horizon <- function(data, h) {
  d_h <- data |>
    group_by(uf_code) |>
    arrange(t_index) |>
    mutate(log_cons_lead = lead(log_consumption, h)) |>
    ungroup() |>
    mutate(y_h = log_cons_lead - lag1_lc) |>
    filter(!is.na(y_h), !is.na(eps_rr),
           !is.na(lag1_share_PH2M), !is.na(lag1_share_WH2M),
           !is.na(infl_yoy), !is.na(log_bf),
           !is.na(log_real_imports), !is.na(log_real_exports))

  if (nrow(d_h) < 50) return(NULL)

  # Drop singleton FE groups (states or months with only 1 obs at this horizon)
  d_h <- d_h |>
    group_by(uf_code) |> filter(n() > 1) |> ungroup() |>
    group_by(ref_month_yyyymm) |> filter(n() > 1) |> ungroup()

  if (nrow(d_h) < 50) return(NULL)

  fml <- as.formula(paste(
    "y_h ~",
    paste(c(INTERACTION_TERMS, CTRL_VARS), collapse = " + "),
    "+ factor(uf_code) + factor(ref_month_yyyymm)"
  ))

  m <- tryCatch(lm(fml, data = d_h), error = function(e) NULL)
  if (is.null(m)) return(NULL)

  vc <- tryCatch(
    vcovCL(m, cluster = ~uf_code, data = d_h, type = "HC1"),
    error = function(e) NULL
  )
  if (is.null(vc)) return(NULL)

  cf <- coef(m)
  se <- sqrt(diag(vc))

  # Only return the four interaction terms
  terms_present <- intersect(INTERACTION_TERMS, names(cf))
  if (length(terms_present) < length(INTERACTION_TERMS)) return(NULL)

  tibble(
    horizon = h,
    nobs    = nrow(d_h),
    term    = terms_present,
    est     = cf[terms_present],
    se      = se[terms_present]
  )
}

run_lp <- function(data, label) {
  n_mons <- n_distinct(data$ref_month_yyyymm)
  cat(sprintf("  %-38s  (months = %d, obs = %d)\n",
              label, n_mons, nrow(data)))
  rows <- map(0L:MAX_HORIZON, ~run_lp_horizon(data, .x))
  bind_rows(compact(rows)) |> mutate(spec = label)
}

# Specs: baseline + four episode exclusions
specs <- list(
  baseline    = d_panel,
  ex_crisis   = d_panel |> filter(!crisis_2015),
  ex_election = d_panel |> filter(!election_2018),
  ex_covid    = d_panel |> filter(!covid_2020),
  ex_any      = d_panel |> filter(!any_episode)
)

SPEC_LABELS <- c(
  baseline    = "Baseline (full sample)",
  ex_crisis   = "Excl. 2015-16 Recession",
  ex_election = "Excl. 2018 Election",
  ex_covid    = "Excl. 2020 COVID",
  ex_any      = "Excl. All Episodes"
)

cat("\n── Running LP variants ──\n")
all_irf <- imap(specs, ~run_lp(.x, SPEC_LABELS[[.y]])) |> bind_rows()
write_csv(all_irf, file.path(OUT_TBL, "episode_robustness_irf.csv"))
cat(sprintf("\n✓ IRF estimates: %d rows → episode_robustness_irf.csv\n", nrow(all_irf)))

# ── Section 5: Comparison plots ───────────────────────────────────────────────
#
# One plot per interaction term, overlaying five IRF paths + 90% CIs.
#
# How to read:
#   Stable result: colored lines track the black baseline closely.
#   Unstable result: a colored line diverges in sign or magnitude, identifying
#     which episode was driving the baseline pattern.
#   Narrower CI after exclusion: the excluded episode contained noisy observations
#     that inflated SE rather than point estimates.

SPEC_COLOURS <- c(
  "Baseline (full sample)"   = "black",
  "Excl. 2015-16 Recession"  = "#d62728",
  "Excl. 2018 Election"       = "#ff7f0e",
  "Excl. 2020 COVID"         = "#1f77b4",
  "Excl. All Episodes"       = "#2ca02c"
)

SPEC_SIZES <- c(
  "Baseline (full sample)"   = 1.1,
  "Excl. 2015-16 Recession"  = 0.75,
  "Excl. 2018 Election"       = 0.75,
  "Excl. 2020 COVID"         = 0.75,
  "Excl. All Episodes"       = 0.75
)

SPEC_LTYPES <- c(
  "Baseline (full sample)"   = "solid",
  "Excl. 2015-16 Recession"  = "dashed",
  "Excl. 2018 Election"       = "dashed",
  "Excl. 2020 COVID"         = "dashed",
  "Excl. All Episodes"       = "dashed"
)

ep_theme <- function() {
  theme_bw(base_size = 11) +
    theme(
      panel.grid.minor       = element_blank(),
      panel.grid.major       = element_line(color = "gray93", linewidth = 0.3),
      strip.background       = element_blank(),
      legend.position        = "inside",
      legend.position.inside = c(0.01, 0.01),
      legend.justification   = c(0, 0),
      legend.background      = element_rect(fill = alpha("white", 0.9), color = NA),
      legend.title           = element_blank(),
      legend.text            = element_text(size = 8.5),
      axis.title             = element_text(size = 10),
      plot.title             = element_text(size = 11, hjust = 0.5),
      plot.subtitle          = element_text(size = 8.5, hjust = 0.5, color = "gray40")
    )
}

plot_df <- all_irf |>
  mutate(
    ci_lo = est - CI_MULT * se,
    ci_hi = est + CI_MULT * se,
    spec  = factor(spec, levels = names(SPEC_COLOURS))
  )

cat("\n── Generating plots ──\n")
for (trm in INTERACTION_TERMS) {
  df_t <- plot_df |> filter(term == trm)

  p <- ggplot(df_t, aes(x = horizon, colour = spec, fill = spec,
                         linetype = spec, linewidth = spec)) +
    geom_hline(yintercept = 0, linetype = "dashed",
               colour = "gray20", linewidth = 0.4) +
    geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi),
                alpha = 0.07, colour = NA) +
    geom_line(aes(y = est)) +
    scale_colour_manual(values = SPEC_COLOURS) +
    scale_fill_manual(values = SPEC_COLOURS) +
    scale_linetype_manual(values = SPEC_LTYPES) +
    scale_linewidth_manual(values = SPEC_SIZES) +
    scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6),
                       limits = c(0, MAX_HORIZON)) +
    labs(
      title    = sprintf("Episode Robustness: %s", INTERACTION_LBLS[trm]),
      subtitle = paste0("TWFE LP · eps_rr · State + year-month FE · ",
                        "HC1 state-clustered SE · 90% CI · h = 0-24"),
      x = "Horizon (months)",
      y = "Cumulative log consumption response"
    ) + ep_theme()

  fname <- sprintf("episode_robustness_%s.png", trm)
  ggsave(file.path(OUT_PLT, fname), p, width = 9, height = 5.5, dpi = 300)
  cat(sprintf("  ✓ %s\n", fname))
}

# 4-panel version: all interaction terms in one figure
p4 <- plot_df |>
  mutate(term_label = factor(INTERACTION_LBLS[term],
                             levels = unname(INTERACTION_LBLS))) |>
  ggplot(aes(x = horizon, colour = spec, fill = spec,
             linetype = spec, linewidth = spec)) +
  geom_hline(yintercept = 0, linetype = "dashed",
             colour = "gray20", linewidth = 0.35) +
  geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.07, colour = NA) +
  geom_line(aes(y = est)) +
  facet_wrap(~term_label, scales = "free_y", ncol = 2) +
  scale_colour_manual(values = SPEC_COLOURS) +
  scale_fill_manual(values = SPEC_COLOURS) +
  scale_linetype_manual(values = SPEC_LTYPES) +
  scale_linewidth_manual(values = SPEC_SIZES) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6),
                     limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "Episode Exclusion Robustness — All Interaction Terms",
    subtitle = "TWFE LP · eps_rr · State + year-month FE · HC1 state-clustered SE · 90% CI",
    x = "Horizon (months)", y = "Cumulative log consumption response"
  ) + ep_theme() +
  theme(legend.position        = "bottom",
        legend.justification   = "center")

ggsave(file.path(OUT_PLT, "episode_robustness_4panel.png"),
       p4, width = 11, height = 8, dpi = 300)
cat("  ✓ episode_robustness_4panel.png\n")

# ── Section 6: Stability summary table ────────────────────────────────────────
#
# For each interaction term × exclusion × horizon ∈ {0, 6, 12, 18, 24}:
# reports estimate, SE, sign match with baseline, and deviation in baseline SEs.
#
# Flagging rule:
#   sign_flip:    sign(est_excl) ≠ sign(est_base) — qualitative reversal
#   large_shift:  |est_excl - est_base| > 1 × se_base — > 1 SE deviation
#   flagged:      either of the above
#
# Early-horizon flags (h=0, h=6) are more alarming than late-horizon flags.
# A sign flip at h=0 means the contemporaneous heterogeneity completely reverses
# when the episode is removed.

CHECK_HORIZONS <- c(0L, 6L, 12L, 18L, 24L)

base_ref <- all_irf |>
  filter(spec == SPEC_LABELS["baseline"],
         horizon %in% CHECK_HORIZONS) |>
  select(horizon, term, est_base = est, se_base = se)

stability_tbl <- all_irf |>
  filter(spec != SPEC_LABELS["baseline"],
         horizon %in% CHECK_HORIZONS) |>
  left_join(base_ref, by = c("horizon", "term")) |>
  mutate(
    sign_match  = sign(est) == sign(est_base),
    delta_in_se = abs(est - est_base) / se_base,
    sign_flip   = !sign_match & !is.na(est_base),
    large_shift = delta_in_se > 1,
    flagged     = sign_flip | large_shift
  ) |>
  mutate(across(c(est, se, est_base, se_base, delta_in_se), ~round(.x, 5))) |>
  select(term, spec, horizon, est, se, est_base, se_base,
         sign_match, delta_in_se, sign_flip, large_shift, flagged) |>
  arrange(term, spec, horizon)

write_csv(stability_tbl, file.path(OUT_TBL, "stability_summary.csv"))

cat("\n── Stability summary (check horizons: 0, 6, 12, 18, 24) ──\n")
flags <- stability_tbl |> filter(flagged)
if (nrow(flags) == 0) {
  cat("  No flags — all exclusion IRFs within 1 SE of baseline, no sign flips.\n")
  cat("  → Main results are robust to episode exclusion.\n")
} else {
  cat(sprintf("  %d flagged horizon × exclusion combinations:\n", nrow(flags)))
  print(
    flags |>
      transmute(term, exclusion = spec, h = horizon,
                est_excl = est, est_base, delta_se = delta_in_se,
                sign_flip, large_shift),
    n = Inf
  )
}

# Flag rate by interaction term
flag_rate <- stability_tbl |>
  group_by(term) |>
  summarise(n_flagged = sum(flagged, na.rm = TRUE),
            n_total   = n(),
            flag_rate = round(n_flagged / n_total, 2),
            .groups   = "drop")

write_csv(flag_rate, file.path(OUT_TBL, "flag_rate_by_term.csv"))
cat("\nFlag rate by interaction term:\n")
print(flag_rate)

cat(sprintf("\n✓ All plots  → %s/\n", OUT_PLT))
cat(sprintf("✓ All tables → %s/\n", OUT_TBL))
cat("\n=== EPISODE EXCLUSION ROBUSTNESS DONE ===\n")
cat("\nINTERPRETATION:\n")
cat("  Stable:    colored lines track black baseline closely — episode not driving results.\n")
cat("  Unstable:  colored line diverges → that episode confounded baseline estimates.\n")
cat("  Flags:     stability_summary.csv → sign flips or |Δ| > 1 SE at check horizons.\n")
cat("  Power cost: episode_descriptives.csv → pct_var_in shows variation lost per exclusion.\n")
