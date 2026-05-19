#!/usr/bin/env Rscript
# R replication of lp_controls_130526.do
#
# Uses DI surprise mp_shock from the LP dataset (not narrative shocks).
# Runs 4 specs × 2 response types × 2 directions, h = 0–24, 90% CI.
#
# Specs:
#   lag1      — mp_shock_pos/neg + interactions + controls + lag1_lc + state FE
#   lag2      — as lag1 + lag2_lc
#   lag1_tfe  — interactions + controls + lag1_lc + state FE + year-month FE
#   lag2_tfe  — as lag1_tfe + lag2_lc
#
# Controls (controls_base in Stata):
#   lag1_share_ph2m, lag1_share_wh2m, log_imports, log_exports,
#   infl_yoy, log_bf (BF total value), log_credit_pf
#
# Response types: cumulative  (y = log_c[t+h] - lag1_lc)
#                 marginal    (y = log_c[t+h] - log_c[t+h-1])
#
# Output:
#   results/tables/lp_controls/  — one CSV per direction × rtype × spec
#                                  + irf_all_specs.csv (all stacked)
#   results/plots/lp_controls/   — irf_{con,exp}_{cumulative,marginal}_preferred.png
#                                  (preferred = lag1_tfe + lag2_tfe overlaid, PH2M | WH2M)

library(tidyverse)
library(sandwich)

set.seed(42)
cat("\n=== LP CONTROLS — R REPLICATION OF STATA SPEC ===\n\n")

MAX_HORIZON <- 24
CI_LEVEL    <- 90
CI_MULT     <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)   # ≈ 1.645  (matches Stata invnormal)

# ---- Output dirs ---------------------------------------------------------------
OUT_TBL <- "results/tables/lp_controls"
OUT_PLT <- "results/plots/lp_controls"
dir.create(OUT_TBL, showWarnings = FALSE, recursive = TRUE)
dir.create(OUT_PLT, showWarnings = FALSE, recursive = TRUE)

# ---- Load dataset --------------------------------------------------------------
lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(month_num       = month,
         lag1_share_ph2m = lag1_share_PH2M,
         lag1_share_wh2m = lag1_share_WH2M)

cat(sprintf("✓ Loaded: %d rows, %d states, years %d–%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code),
            min(d_raw$year), max(d_raw$year)))

# ---- Prepare variables (mirrors Stata data prep) --------------------------------
panel <- d_raw |>
  arrange(uf_code, year, month_num) |>
  group_by(uf_code) |>
  mutate(
    log_consumption  = log(consumption_index),                        # Stata: gen log_consumption = log(consumption_index)
    log_imports      = log(coalesce(vl_imports, 0)         + 1),     # gen log_imports = log(vl_imports + 1)
    log_exports      = log(coalesce(vl_exports, 0)         + 1),     # gen log_exports = log(vl_exports + 1)
    log_bf           = log(coalesce(total_value_BF_old, 0) + 1),     # gen log_bf      = log(total_value_bf_old + 1)
    infl_mom         = log(ipca_index) - log(lag(ipca_index, 1)),    # monthly fallback
    infl_yoy_raw     = log(ipca_index) - log(lag(ipca_index, 12)),   # gen infl_yoy
    infl_yoy         = coalesce(infl_yoy_raw, infl_mom * 12),        # replace infl_yoy = infl_mom*12 if missing
    lag1_lc          = lag(log_consumption),                          # by uf_code: gen lag1_lc
    lag2_lc          = lag(log_consumption, 2),                       # by uf_code: gen lag2_lc
    mp_shock_pos     = pmax(mp_shock, 0),                             # gen mp_shock_pos
    mp_shock_neg_abs = abs(pmin(mp_shock, 0)),                        # gen mp_shock_neg_abs
    mp_pos_x_ph2m    = mp_shock_pos     * lag1_share_ph2m,           # gen mp_pos_x_ph2m
    mp_pos_x_wh2m    = mp_shock_pos     * lag1_share_wh2m,           # gen mp_pos_x_wh2m
    mp_neg_x_ph2m    = mp_shock_neg_abs * lag1_share_ph2m,           # gen mp_neg_x_ph2m
    mp_neg_x_wh2m    = mp_shock_neg_abs * lag1_share_wh2m,           # gen mp_neg_x_wh2m
    ym               = year * 100L + month_num                        # year-month FE index (i.t_id)
  ) |>
  ungroup()

cat(sprintf("  mp_shock non-zero: %d / %d obs\n",
            sum(panel$mp_shock != 0, na.rm = TRUE), sum(!is.na(panel$mp_shock))))

# Controls base — matches Stata local controls_base
CTRL_BASE <- c("lag1_share_ph2m", "lag1_share_wh2m",
               "log_imports", "log_exports", "infl_yoy", "log_bf")
if (sum(!is.na(panel$log_credit_pf)) > 10)
  CTRL_BASE <- c(CTRL_BASE, "log_credit_pf")
cat(sprintf("  Controls: %s\n", paste(CTRL_BASE, collapse = ", ")))

# ---- Helpers -------------------------------------------------------------------
vcov_cluster <- function(m, cluster_var)
  sandwich::vcovCL(m, cluster = cluster_var, type = "HC1")

get_coef <- function(m, vc, term) {
  cn  <- rownames(vc)
  cf  <- coef(m)
  idx <- grep(term, cn, perl = TRUE)[1]
  if (is.na(idx)) return(c(b = NA_real_, se = NA_real_))
  c(b  = as.numeric(cf[cn[idx]]),
    se = sqrt(as.numeric(vc[idx, idx])))
}

# ---- LP estimation loop --------------------------------------------------------
SPECS      <- c("lag1", "lag2", "lag1_tfe", "lag2_tfe")
RTYPES     <- c("cumulative", "marginal")
DIRECTIONS <- c("con", "exp")

all_results <- list()

for (direction in DIRECTIONS) {
  for (rtype in RTYPES) {
    for (spec in SPECS) {

      cat(sprintf("\n  %s | %s | %s\n", direction, rtype, spec))

      x_ph2m      <- if (direction == "con") "mp_pos_x_ph2m" else "mp_neg_x_ph2m"
      x_wh2m      <- if (direction == "con") "mp_pos_x_wh2m" else "mp_neg_x_wh2m"
      shock_level <- if (direction == "con") "mp_shock_pos"   else "mp_shock_neg_abs"
      ctrl_str    <- paste(CTRL_BASE, collapse = " + ")

      rows <- vector("list", MAX_HORIZON + 1)

      for (h in 0:MAX_HORIZON) {

        d <- panel |>
          filter(!is.na(lag1_lc), !is.na(mp_shock)) |>
          arrange(uf_code, year, month_num) |>
          group_by(uf_code) |>
          mutate(
            y_resp = if (rtype == "cumulative") {
              lead(log_consumption, h) - lag1_lc
            } else if (h == 0) {
              log_consumption - lag1_lc
            } else {
              lead(log_consumption, h) - lead(log_consumption, h - 1)
            }
          ) |>
          ungroup() |>
          filter(!is.na(y_resp))

        # Formula (mirrors each Stata spec exactly)
        fml_rhs <- switch(spec,
          lag1     = paste(shock_level, "+", x_ph2m, "+", x_wh2m, "+",
                           ctrl_str, "+ lag1_lc + factor(uf_code)"),
          lag2     = paste(shock_level, "+", x_ph2m, "+", x_wh2m, "+",
                           ctrl_str, "+ lag1_lc + lag2_lc + factor(uf_code)"),
          lag1_tfe = paste(x_ph2m, "+", x_wh2m, "+",
                           ctrl_str, "+ lag1_lc + factor(uf_code) + factor(ym)"),
          lag2_tfe = paste(x_ph2m, "+", x_wh2m, "+",
                           ctrl_str, "+ lag1_lc + lag2_lc + factor(uf_code) + factor(ym)")
        )

        m  <- lm(as.formula(paste("y_resp ~", fml_rhs)), data = d)
        vc <- vcov_cluster(m, d$uf_code)

        b_shock <- if (spec %in% c("lag1", "lag2"))
          get_coef(m, vc, paste0("^", shock_level, "$"))
        else c(b = NA_real_, se = NA_real_)

        b_ph2m <- get_coef(m, vc, paste0("^", x_ph2m, "$"))
        b_wh2m <- get_coef(m, vc, paste0("^", x_wh2m, "$"))

        rows[[h + 1]] <- tibble(
          horizon      = h,
          b_mp_shock   = b_shock[["b"]],
          se_mp_shock  = b_shock[["se"]],
          b_mp_x_ph2m  = b_ph2m[["b"]],
          se_mp_x_ph2m = b_ph2m[["se"]],
          ci_lo_ph2m   = b_ph2m[["b"]] - CI_MULT * b_ph2m[["se"]],
          ci_hi_ph2m   = b_ph2m[["b"]] + CI_MULT * b_ph2m[["se"]],
          b_mp_x_wh2m  = b_wh2m[["b"]],
          se_mp_x_wh2m = b_wh2m[["se"]],
          ci_lo_wh2m   = b_wh2m[["b"]] - CI_MULT * b_wh2m[["se"]],
          ci_hi_wh2m   = b_wh2m[["b"]] + CI_MULT * b_wh2m[["se"]],
          nobs         = nrow(d),
          response_type = rtype,
          spec          = spec,
          shock_type    = if (direction == "con") "contractionary" else "expansionary"
        )

        if (h %% 8 == 0)
          cat(sprintf("    h=%02d  n=%d  PH2M=%+.4f  WH2M=%+.4f\n",
                      h, nrow(d), b_ph2m[["b"]], b_wh2m[["b"]]))
      }

      result  <- bind_rows(rows)
      key     <- paste(direction, rtype, spec, sep = "_")
      all_results[[key]] <- result

      fname   <- sprintf("irf_%s_%s_%s.csv", direction, rtype, spec)
      write_csv(result, file.path(OUT_TBL, fname))
      cat(sprintf("    ✓ saved %s\n", fname))
    }
  }
}

# ---- Combined CSV --------------------------------------------------------------
irf_all <- bind_rows(all_results)
write_csv(irf_all, file.path(OUT_TBL, "irf_all_specs.csv"))
cat(sprintf("\n✓ All CSVs saved to %s/\n", OUT_TBL))

# ---- Plots (preferred specs: lag1_tfe + lag2_tfe; PH2M | WH2M panels) ----------
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

SPEC_COLOURS <- c(lag1_tfe = "#2166ac", lag2_tfe = "#d6604d")
SPEC_LABELS  <- c(lag1_tfe = "lag1 + time FE", lag2_tfe = "lag2 + time FE")

for (direction in DIRECTIONS) {
  slabel <- if (direction == "con") "Contractionary (Rate Hikes)" else "Expansionary (Rate Cuts)"

  for (rtype in RTYPES) {
    ytitle <- if (rtype == "cumulative") "Cumulative log response" else "Marginal log response"

    # Reshape to long for clean facet_wrap (mirrors Stata graph combine)
    plot_df <- bind_rows(
      all_results[[paste(direction, rtype, "lag1_tfe", sep = "_")]],
      all_results[[paste(direction, rtype, "lag2_tfe", sep = "_")]]
    ) |>
      mutate(spec = factor(spec, levels = c("lag1_tfe", "lag2_tfe"))) |>
      pivot_longer(
        cols      = c(b_mp_x_ph2m, b_mp_x_wh2m),
        names_to  = "type_raw",
        values_to = "estimate"
      ) |>
      mutate(
        type  = if_else(type_raw == "b_mp_x_ph2m", "PH2M", "WH2M"),
        ci_lo = if_else(type_raw == "b_mp_x_ph2m", ci_lo_ph2m, ci_lo_wh2m),
        ci_hi = if_else(type_raw == "b_mp_x_ph2m", ci_hi_ph2m, ci_hi_wh2m),
        type  = factor(type, levels = c("PH2M", "WH2M"))
      )

    p <- plot_df |>
      ggplot(aes(x = horizon, y = estimate, color = spec, fill = spec)) +
      geom_hline(yintercept = 0, color = "black", linewidth = 0.5) +
      geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.2, color = NA) +
      geom_line(linewidth = 0.9) +
      facet_wrap(~ type, nrow = 1, scales = "free_y",
                 labeller = labeller(type = c(PH2M = "PH2M exposure × MP shock",
                                              WH2M = "WH2M exposure × MP shock"))) +
      scale_color_manual(values = SPEC_COLOURS, labels = SPEC_LABELS) +
      scale_fill_manual( values = SPEC_COLOURS, labels = SPEC_LABELS) +
      scale_x_continuous(breaks = seq(0, MAX_HORIZON, by = 6),
                         limits = c(0, MAX_HORIZON)) +
      labs(
        title    = sprintf("State-Month %s LP IRFs — %s", rtype, slabel),
        subtitle = "MP shock × household-share interactions (preferred specs with time FE) · 90% CI",
        x        = "Horizon (months)",
        y        = ytitle
      ) +
      irf_theme()

    fname <- sprintf("irf_%s_%s_preferred.png", direction, rtype)
    ggsave(file.path(OUT_PLT, fname), p, width = 10, height = 4.5, dpi = 300)
    cat(sprintf("✓ Saved: %s\n", fname))
  }
}

cat(sprintf("\n✓ All plots → %s/\n", OUT_PLT))
cat("\n=== LP ESTIMATION COMPLETE ===\n")
cat(sprintf("  Tables: %s/\n", OUT_TBL))
cat(sprintf("  Plots:  %s/\n", OUT_PLT))
