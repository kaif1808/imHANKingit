#!/usr/bin/env Rscript
# LP on STL seasonally-adjusted state income (mean_income_sa)
# Spec: lag1_tfe only (state FE + year-month FE, lag1 income control)
# Shock: mp_shock_di (DI surprise)
# CIs: pairs cluster bootstrap, B=499, 90% percentile, parallelised over B
#
# Also runs a national aggregate LP (population-weighted mean income)
# with Newey-West HAC SEs (no panel structure).
#
# Output:
#   results/tables/lp_income/   — irf CSVs per direction×rtype + combined
#   results/plots/lp_income/    — preferred IRF plots + national LP plot

library(tidyverse)
library(sandwich)
library(parallel)

set.seed(42)
N_CORES     <- max(1L, detectCores() - 1L)
B_BOOT      <- 499L
MAX_HORIZON <- 24L
CI_LEVEL    <- 90
CI_MULT     <- qnorm(1 - (1 - CI_LEVEL / 100) / 2)   # analytical fallback only

OUT_TBL <- "results/tables/lp_income"
OUT_PLT <- "results/plots/lp_income"
dir.create(OUT_TBL, showWarnings = FALSE, recursive = TRUE)
dir.create(OUT_PLT, showWarnings = FALSE, recursive = TRUE)

cat(sprintf("\n=== LP INCOME (lag1_tfe · DI shock · B=%d · %d cores) ===\n\n",
            B_BOOT, N_CORES))

# ── Load & rename ─────────────────────────────────────────────────────────────

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
if (!file.exists(lp_path)) stop(sprintf("Not found: %s", lp_path))

d_raw <- read_csv(lp_path, show_col_types = FALSE) |>
  rename(
    month_num       = month,
    lag1_share_ph2m = lag1_share_PH2M,
    lag1_share_wh2m = lag1_share_WH2M,
    mp_shock        = mp_shock_di
  )

cat(sprintf("✓ Loaded: %d rows, %d states, years %d–%d\n",
            nrow(d_raw), n_distinct(d_raw$uf_code),
            min(d_raw$year), max(d_raw$year)))

# ── Panel variables ───────────────────────────────────────────────────────────

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
    lag2_li          = lag(log_income_sa, 2),
    mp_shock_pos     = pmax(mp_shock, 0),
    mp_shock_neg_abs = abs(pmin(mp_shock, 0)),
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

cat(sprintf("  Controls: %s\n", paste(CTRL_BASE, collapse = ", ")))
cat(sprintf("  mp_shock non-zero: %d / %d obs\n\n",
            sum(panel$mp_shock != 0, na.rm = TRUE),
            sum(!is.na(panel$mp_shock))))

# ── Bootstrap helpers ─────────────────────────────────────────────────────────

# One pairs-cluster bootstrap rep: resample states with replacement
one_boot_rep <- function(seed, d, fml, params) {
  set.seed(seed)
  clusters  <- unique(d$uf_code)
  sampled   <- sample(clusters, length(clusters), replace = TRUE)
  boot_d    <- do.call(rbind, lapply(seq_along(sampled), function(i) {
    sub <- d[d$uf_code == sampled[i], ]
    sub$uf_code <- i   # unique numeric ID for this draw
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
  seeds  <- sample.int(.Machine$integer.max, B)
  reps   <- mclapply(seeds, one_boot_rep, d = d, fml = fml, params = params,
                     mc.cores = N_CORES)
  mat    <- do.call(rbind, reps)  # B × length(params)
  lo     <- apply(mat, 2, quantile, alpha / 2,       na.rm = TRUE)
  hi     <- apply(mat, 2, quantile, 1 - alpha / 2,   na.rm = TRUE)
  list(lo = lo, hi = hi)
}

get_coef_vc <- function(m, vc, term) {
  cn  <- rownames(vc); cf <- coef(m)
  idx <- grep(paste0("^", term, "$"), cn, perl = TRUE)[1]
  if (is.na(idx)) return(c(b = NA_real_, se = NA_real_))
  c(b = as.numeric(cf[cn[idx]]), se = sqrt(as.numeric(vc[idx, idx])))
}

# ── ① State panel LP — lag1_tfe ───────────────────────────────────────────────

DIRECTIONS <- c("con", "exp")
RTYPES     <- c("cumulative")
all_results <- list()
t_start <- proc.time()

for (direction in DIRECTIONS) {
  for (rtype in RTYPES) {

    x_ph2m      <- if (direction == "con") "mp_pos_x_ph2m" else "mp_neg_x_ph2m"
    x_wh2m      <- if (direction == "con") "mp_pos_x_wh2m" else "mp_neg_x_wh2m"

    fml_str <- paste("y_resp ~", x_ph2m, "+", x_wh2m, "+",
                     ctrl_str, "+ lag1_li + factor(uf_code) + factor(ym)")

    cat(sprintf("  %s | %s | lag1_tfe  [bootstrap B=%d]\n",
                direction, rtype, B_BOOT))

    rows <- vector("list", MAX_HORIZON + 1)

    for (h in 0:MAX_HORIZON) {

      d <- panel |>
        filter(!is.na(lag1_li), !is.na(mp_shock), !is.na(log_income_sa)) |>
        arrange(uf_code, year, month_num) |>
        group_by(uf_code) |>
        mutate(y_resp = lead(log_income_sa, h) - lag1_li) |>
        ungroup() |>
        filter(!is.na(y_resp))

      fml <- as.formula(fml_str)
      m   <- lm(fml, data = d)
      vc  <- sandwich::vcovCL(m, cluster = d$uf_code, type = "HC1")

      b_ph2m <- get_coef_vc(m, vc, x_ph2m)
      b_wh2m <- get_coef_vc(m, vc, x_wh2m)

      # Bootstrap CIs
      ci <- boot_ci(d, fml, params = c(x_ph2m, x_wh2m))

      rows[[h + 1]] <- tibble(
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
        shock_type    = if (direction == "con") "contractionary" else "expansionary"
      )

      if (h %% 8 == 0)
        cat(sprintf("    h=%02d  n=%d  PH2M=%+.4f [%+.4f, %+.4f]  WH2M=%+.4f [%+.4f, %+.4f]\n",
                    h, nrow(d),
                    b_ph2m[["b"]], ci$lo[[x_ph2m]], ci$hi[[x_ph2m]],
                    b_wh2m[["b"]], ci$lo[[x_wh2m]], ci$hi[[x_wh2m]]))
    }

    key <- paste(direction, rtype, "lag1_tfe", sep = "_")
    result <- bind_rows(rows)
    all_results[[key]] <- result
    fname <- sprintf("irf_%s_%s_lag1_tfe.csv", direction, rtype)
    write_csv(result, file.path(OUT_TBL, fname))
    cat(sprintf("    ✓ saved %s\n", fname))
  }
}

elapsed <- round((proc.time() - t_start)[3] / 60, 1)
irf_all <- bind_rows(all_results)
write_csv(irf_all, file.path(OUT_TBL, "irf_all_specs.csv"))
cat(sprintf("\n✓ State LP CSVs saved (%s min elapsed)\n\n", elapsed))

# ── ② National aggregate LP ───────────────────────────────────────────────────
# Collapse to population-weighted monthly mean; single time series → NW HAC SEs

cat("  National aggregate LP ...\n")

nat <- panel |>
  filter(!is.na(log_income_sa), !is.na(population)) |>
  group_by(ym, year, month_num) |>
  summarise(
    log_income_sa = weighted.mean(log_income_sa, population, na.rm = TRUE),
    infl_yoy      = weighted.mean(infl_yoy,      population, na.rm = TRUE),
    log_imports   = weighted.mean(log_imports,   population, na.rm = TRUE),
    log_exports   = weighted.mean(log_exports,   population, na.rm = TRUE),
    log_bf        = weighted.mean(log_bf,        population, na.rm = TRUE),
    mp_shock      = first(mp_shock),   # same for all states in a month
    .groups = "drop"
  ) |>
  arrange(ym) |>
  mutate(
    lag1_li          = lag(log_income_sa),
    mp_shock_pos     = pmax(mp_shock, 0),
    mp_shock_neg_abs = abs(pmin(mp_shock, 0))
  )

nat_rows <- list()

for (direction in DIRECTIONS) {
  shock_var <- if (direction == "con") "mp_shock_pos" else "mp_shock_neg_abs"

  for (rtype in RTYPES) {

    rows_n <- vector("list", MAX_HORIZON + 1)

    for (h in 0:MAX_HORIZON) {

      dn <- nat |>
        filter(!is.na(lag1_li), !is.na(mp_shock)) |>
        mutate(y_resp = lead(log_income_sa, h) - lag1_li) |>
        filter(!is.na(y_resp))

      fml_n <- as.formula(paste("y_resp ~", shock_var,
                                "+ lag1_li + infl_yoy + log_imports + log_exports + log_bf"))
      mn    <- lm(fml_n, data = dn)
      # Newey-West HAC: lag = h+1 to account for moving-average at horizon h
      vc_nw <- sandwich::NeweyWest(mn, lag = h + 1, prewhite = FALSE, adjust = TRUE)
      se_nw <- sqrt(diag(vc_nw))

      idx <- grep(paste0("^", shock_var, "$"), names(coef(mn)), perl = TRUE)[1]
      b   <- if (!is.na(idx)) coef(mn)[idx]   else NA_real_
      se  <- if (!is.na(idx)) se_nw[idx]      else NA_real_

      rows_n[[h + 1]] <- tibble(
        horizon       = h,
        b_mp_shock    = as.numeric(b),
        se_mp_shock   = as.numeric(se),
        ci_lo         = as.numeric(b) - CI_MULT * as.numeric(se),
        ci_hi         = as.numeric(b) + CI_MULT * as.numeric(se),
        nobs          = nrow(dn),
        response_type = rtype,
        shock_type    = if (direction == "con") "contractionary" else "expansionary"
      )
    }

    key_n <- paste("nat", direction, rtype, sep = "_")
    nat_rows[[key_n]] <- bind_rows(rows_n)
  }
}

nat_all <- bind_rows(nat_rows)
write_csv(nat_all, file.path(OUT_TBL, "irf_national_all.csv"))
cat("  ✓ National LP CSVs saved\n\n")

# ── ③ Plots ───────────────────────────────────────────────────────────────────

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

# 3a. State LP plots — PH2M | WH2M panels, one plot per direction×rtype
TYPE_COLS <- c(PH2M = "#2166ac", WH2M = "#d6604d")

for (direction in DIRECTIONS) {
  slabel <- if (direction == "con") "Contractionary (Rate Hikes)" else "Expansionary (Rate Cuts)"

  for (rtype in RTYPES) {
    ytitle <- "Cumulative log income response"

    plot_df <- all_results[[paste(direction, rtype, "lag1_tfe", sep = "_")]] |>
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
      facet_wrap(~ type, nrow = 1, scales = "free_y",
                 labeller = labeller(type = c(
                   PH2M = "PH2M exposure × MP shock",
                   WH2M = "WH2M exposure × MP shock"
                 ))) +
      scale_colour_manual(values = TYPE_COLS, guide = "none") +
      scale_fill_manual(  values = TYPE_COLS, guide = "none") +
      scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
      labs(
        title    = sprintf("Income LP IRFs — %s", slabel),
        subtitle = sprintf("Response: log(mean_income_sa) · Shock: DI surprise · lag1_tfe · %d%% bootstrap CI (B=%d)",
                           CI_LEVEL, B_BOOT),
        x = "Horizon (months)", y = ytitle
      ) + irf_theme()

    fname <- sprintf("irf_%s_%s_preferred.png", direction, rtype)
    ggsave(file.path(OUT_PLT, fname), p, width = 10, height = 4.5, dpi = 300)
    cat(sprintf("✓ State plot: %s\n", fname))
  }
}

# 3b. National LP — con + exp overlaid, cumulative only (one clean summary plot)
nat_plot_df <- nat_all |>
  filter(response_type == "cumulative") |>
  mutate(direction = if_else(shock_type == "contractionary",
                             "Contractionary (Rate Hikes)",
                             "Expansionary (Rate Cuts)"))

p_nat <- ggplot(nat_plot_df, aes(x = horizon, y = b_mp_shock,
                                  colour = direction, fill = direction)) +
  geom_hline(yintercept = 0, linewidth = 0.5) +
  geom_ribbon(aes(ymin = ci_lo, ymax = ci_hi), alpha = 0.15, colour = NA) +
  geom_line(linewidth = 0.9) +
  scale_colour_manual(values = c("Contractionary (Rate Hikes)" = "#d6604d",
                                 "Expansionary (Rate Cuts)"    = "#2166ac")) +
  scale_fill_manual(  values = c("Contractionary (Rate Hikes)" = "#d6604d",
                                 "Expansionary (Rate Cuts)"    = "#2166ac")) +
  scale_x_continuous(breaks = seq(0, MAX_HORIZON, 6), limits = c(0, MAX_HORIZON)) +
  labs(
    title    = "National Aggregate Income LP — Direct DI Shock Response",
    subtitle = sprintf("Response: pop-weighted log(mean_income_sa) · NW HAC SEs (lag=h+1) · %d%% CI", CI_LEVEL),
    x = "Horizon (months)", y = "Cumulative log income response",
    colour = NULL, fill = NULL
  ) + irf_theme() +
  theme(legend.position = "bottom")

ggsave(file.path(OUT_PLT, "irf_national_cumulative.png"),
       p_nat, width = 8, height = 4.5, dpi = 300)
cat("✓ National plot: irf_national_cumulative.png\n")

cat(sprintf("\n=== COMPLETE ===\n  Tables: %s/\n  Plots:  %s/\n", OUT_TBL, OUT_PLT))
