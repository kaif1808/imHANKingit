# =============================================================================
# Narrative monetary policy shocks for Brazil
# Replicating the methodology in:
#   Aragon, Medeiros, Mendes & Abreu (2026, Empirical Economics)
#   "Measuring monetary policy shocks and their effects in an emerging economy:
#    the case of Brazil"
#
# Pipeline:
#   1. Pull Selic target (SGS 432) and Focus expectations via rbcb
#   2. Build a Copom-meeting-level dataset
#   3. Estimate the Central Bank reaction function three ways and take the
#      residuals as monetary policy shocks:
#        (a) constant coefficients (OLS)               -> eps_rr
#        (b) structural breaks (Bai-Perron)            -> eps_sb
#        (c) time-varying parameters (Bayesian TVP)    -> eps_tvp
# =============================================================================


# ---- 0. Packages ------------------------------------------------------------

pkgs <- c("rbcb", "dplyr", "lubridate", "tidyr", "purrr",
          "strucchange", "shrinkTVP", "ggplot2", "readr", "tibble",
          "httr", "jsonlite")

to_install <- setdiff(pkgs, rownames(installed.packages()))
if (length(to_install) > 0) install.packages(to_install)
invisible(lapply(pkgs, library, character.only = TRUE))

set.seed(20260417)


# ---- 1. Sample parameters ---------------------------------------------------

# Focus daily survey has reliable coverage from ~late 2001 onward.
start_date <- as.Date("2001-11-01")
end_date   <- Sys.Date()


# ---- 2. Copom meeting dates -------------------------------------------------
# 
# NOTE: Verify this list against the official BCB Copom calendar at
#   https://www.bcb.gov.br/controleinflacao/copomcalendariominutas
# These are the *decision* dates (second day of the meeting).
# Meetings where the Selic target was left unchanged are also here -- that's
# why we cannot infer them from SGS 432 alone.
#
# Below is a best-effort list. Audit and amend before running.

copom_dates <- as.Date(c(
  # --- 2001 ---
  "2001-11-21","2001-12-19",
  # --- 2002 ---
  "2002-01-23","2002-02-20","2002-03-20","2002-04-17","2002-05-22",
  "2002-06-19","2002-07-17","2002-08-21","2002-09-18","2002-10-14",
  "2002-10-23","2002-11-20","2002-12-18",
  # --- 2003 ---
  "2003-01-22","2003-02-19","2003-02-21","2003-03-19","2003-04-23",
  "2003-05-21","2003-06-18","2003-07-23","2003-08-20","2003-09-17",
  "2003-10-22","2003-11-19","2003-12-17",
  # --- 2004 ---
  "2004-01-21","2004-02-18","2004-03-17","2004-04-14","2004-05-19",
  "2004-06-16","2004-07-21","2004-08-18","2004-09-15","2004-10-20",
  "2004-11-17","2004-12-15",
  # --- 2005 ---
  "2005-01-19","2005-02-16","2005-03-16","2005-04-20","2005-05-18",
  "2005-06-15","2005-07-20","2005-08-17","2005-09-14","2005-10-19",
  "2005-11-23","2005-12-14",
  # --- 2006 ---
  "2006-01-18","2006-03-08","2006-04-19","2006-05-31","2006-07-19",
  "2006-08-30","2006-10-18","2006-11-29",
  # --- 2007 ---
  "2007-01-24","2007-03-07","2007-04-18","2007-06-06","2007-07-18",
  "2007-09-05","2007-10-17","2007-12-05",
  # --- 2008 ---
  "2008-01-23","2008-03-05","2008-04-16","2008-06-04","2008-07-23",
  "2008-09-10","2008-10-29","2008-12-10",
  # --- 2009 ---
  "2009-01-21","2009-03-11","2009-04-29","2009-06-10","2009-07-22",
  "2009-09-02","2009-10-21","2009-12-09",
  # --- 2010 ---
  "2010-01-27","2010-03-17","2010-04-28","2010-06-09","2010-07-21",
  "2010-09-01","2010-10-20","2010-12-08",
  # --- 2011 ---
  "2011-01-19","2011-03-02","2011-04-20","2011-06-08","2011-07-20",
  "2011-08-31","2011-10-19","2011-11-30",
  # --- 2012 ---
  "2012-01-18","2012-03-07","2012-04-18","2012-05-30","2012-07-11",
  "2012-08-29","2012-10-10","2012-11-28",
  # --- 2013 ---
  "2013-01-16","2013-03-06","2013-04-17","2013-05-29","2013-07-10",
  "2013-08-28","2013-10-09","2013-11-27",
  # --- 2014 ---
  "2014-01-15","2014-02-26","2014-04-02","2014-05-28","2014-07-16",
  "2014-09-03","2014-10-29","2014-12-03",
  # --- 2015 ---
  "2015-01-21","2015-03-04","2015-04-29","2015-06-03","2015-07-29",
  "2015-09-02","2015-10-21","2015-11-25",
  # --- 2016 ---
  "2016-01-20","2016-03-02","2016-04-27","2016-06-08","2016-07-20",
  "2016-08-31","2016-10-19","2016-11-30",
  # --- 2017 ---
  "2017-01-11","2017-02-22","2017-04-12","2017-05-31","2017-07-26",
  "2017-09-06","2017-10-25","2017-12-06",
  # --- 2018 ---
  "2018-02-07","2018-03-21","2018-05-16","2018-06-20","2018-08-01",
  "2018-09-19","2018-10-31","2018-12-12",
  # --- 2019 ---
  "2019-02-06","2019-03-20","2019-05-08","2019-06-19","2019-07-31",
  "2019-09-18","2019-10-30","2019-12-11",
  # --- 2020 ---
  "2020-02-05","2020-03-18","2020-05-06","2020-06-17","2020-08-05",
  "2020-09-16","2020-10-28","2020-12-09",
  # --- 2021 ---
  "2021-01-20","2021-03-17","2021-05-05","2021-06-16","2021-08-04",
  "2021-09-22","2021-10-27","2021-12-08",
  # --- 2022 ---
  "2022-02-02","2022-03-16","2022-05-04","2022-06-15","2022-08-03",
  "2022-09-21","2022-10-26","2022-12-07",
  # --- 2023 ---
  "2023-02-01","2023-03-22","2023-05-03","2023-06-21","2023-08-02",
  "2023-09-20","2023-11-01","2023-12-13",
  # --- 2024 ---
  "2024-01-31","2024-03-20","2024-05-08","2024-06-19","2024-07-31",
  "2024-09-18","2024-11-06","2024-12-11",
  # --- 2025 ---
  "2025-01-29","2025-03-19","2025-05-07","2025-06-18","2025-07-30",
  "2025-09-17","2025-11-05","2025-12-10",
  # --- 2026 ---
  "2026-01-28","2026-03-18"
))

copom_dates <- sort(unique(copom_dates))
copom_dates <- copom_dates[copom_dates >= start_date & copom_dates <= end_date]
message("Using ", length(copom_dates), " Copom meetings.")


# ---- 3. Inflation targets (pi*) from CMN ------------------------------------
#
# Source: BCB "Histórico de metas para a inflação no Brasil" (CMN resolutions).
# For 2003 and 2004 the "adjusted" targets (Carta Aberta) are used.

inflation_targets <- tribble(
  ~year, ~target,
  1999,  8.00,
  2000,  6.00,
  2001,  4.00,
  2002,  3.50,
  2003,  8.50,   # adjusted target (original: 4.00)
  2004,  5.50,   # adjusted target (original: 3.75)
  2005,  4.50,
  2006,  4.50,
  2007,  4.50,
  2008,  4.50,
  2009,  4.50,
  2010,  4.50,
  2011,  4.50,
  2012,  4.50,
  2013,  4.50,
  2014,  4.50,
  2015,  4.50,
  2016,  4.50,
  2017,  4.50,
  2018,  4.50,
  2019,  4.25,
  2020,  4.00,
  2021,  3.75,
  2022,  3.50,
  2023,  3.25,
  2024,  3.00,
  2025,  3.00,
  2026,  3.00,
  2027,  3.00
)


# ---- 4. Pull Selic target (SGS 432) -----------------------------------------
# Direct httr call, bypassing rbcb, with User-Agent to avoid 406 errors.
sgs_fetch <- function(code, start_date, end_date, chunk_years = 9) {
  start_date <- as.Date(start_date)
  end_date   <- as.Date(end_date)

  # Build chunk boundaries, each ≤ chunk_years wide
  breaks <- seq(from = start_date, to = end_date,
                by = sprintf("%d years", chunk_years))
  if (tail(breaks, 1) < end_date) breaks <- c(breaks, end_date)

  fetch_one <- function(s, e) {
    url <- sprintf(
      "https://api.bcb.gov.br/dados/serie/bcdata.sgs.%s/dados?formato=csv&dataInicial=%s&dataFinal=%s",
      code,
      format(s, "%d/%m/%Y"),
      format(e, "%d/%m/%Y")
    )
    tmp <- tempfile(fileext = ".csv")
    on.exit(unlink(tmp), add = TRUE)
    download.file(url, tmp, method = "libcurl", quiet = TRUE,
                  headers = c("User-Agent" = "Mozilla/5.0"))
    raw <- read.csv2(tmp, stringsAsFactors = FALSE)
    tibble::tibble(
      date         = as.Date(raw$data, format = "%d/%m/%Y"),
      selic_target = as.numeric(gsub(",", ".", raw$valor))
    )
  }

  pieces <- list()
  for (i in seq_len(length(breaks) - 1)) {
    s <- breaks[i]
    e <- if (i == length(breaks) - 1) breaks[i + 1] else breaks[i + 1] - 1
    message("  fetching chunk ", format(s), " -> ", format(e))
    pieces[[i]] <- fetch_one(s, e)
  }
  dplyr::bind_rows(pieces) |> dplyr::distinct() |> dplyr::arrange(date)
}

message("Fetching Selic target (SGS 432) ...")
selic_raw <- sgs_fetch(432, start_date, end_date) |> arrange(date)

all_days <- tibble(date = seq.Date(min(selic_raw$date), max(selic_raw$date), by = "day"))
selic_daily <- all_days |>
  left_join(selic_raw, by = "date") |>
  tidyr::fill(selic_target, .direction = "down")



# ---- 5. Pull Focus expectations (annual) -- chunked by year -----------------

fetch_focus_chunk <- function(yr) {
  res <- try(
    rbcb::get_market_expectations(
      type       = "annual",
      indic      = c("IPCA", "PIB Total"),
      start_date = as.Date(sprintf("%d-01-01", yr)),
      end_date   = as.Date(sprintf("%d-12-31", yr)),
      keep_names = TRUE,
      `$top`     = 100000
    ),
    silent = TRUE
  )
  if (inherits(res, "try-error")) return(NULL)
  res
}

years_to_pull <- seq(year(start_date), year(end_date))
message("Fetching Focus expectations year by year ...")
focus_raw <- purrr::map_dfr(years_to_pull, function(y) {
  message("  year ", y)
  fetch_focus_chunk(y)
})

message("Focus rows pulled: ", nrow(focus_raw))

focus_clean <- focus_raw |>
  rename_with(tolower) |>
  {
    if ("basecalculo" %in% names(.)) {
      dplyr::filter(., basecalculo == 0)
    } else {
      .
    }
  } |>
  transmute(
    date   = as.Date(data),
    indic  = indicador,
    ref_yr = suppressWarnings(as.integer(datareferencia)),
    median = mediana
  ) |>
  filter(!is.na(ref_yr)) |>
  distinct(date, indic, ref_yr, .keep_all = TRUE)

focus_wide <- focus_clean |>
  mutate(horizon = ref_yr - year(date)) |>
  filter(horizon %in% c(0L, 1L)) |>
  mutate(var = case_when(
    indic == "IPCA"      & horizon == 0 ~ "pi_e_0",
    indic == "IPCA"      & horizon == 1 ~ "pi_e_1",
    indic == "PIB Total" & horizon == 0 ~ "y_e_0",
    indic == "PIB Total" & horizon == 1 ~ "y_e_1"
  )) |>
  select(date, var, median) |>
  pivot_wider(names_from = var, values_from = median) |>
  arrange(date)

# ---- 6. Build meeting-level panel -------------------------------------------
#
# For each Copom meeting date, pull:
#   - Selic target BEFORE the meeting (ib_t): target on (meeting_date - 1).
#   - Selic target AFTER the meeting (i_t): target on meeting_date.
#     Note: BCB usually posts the new target the evening of the decision; the
#     SGS series shows the new target starting the next business day. We
#     therefore take the target on meeting_date + 1 as i_t (robust to the
#     announcement-day convention).
#   - Focus data from the last available business day strictly before the
#     meeting.

get_target_on <- function(d) {
  # Last available SGS target up to date d (inclusive)
  v <- selic_daily$selic_target[selic_daily$date <= d]
  if (length(v) == 0) return(NA_real_)
  tail(v, 1)
}

get_focus_before <- function(d) {
  f <- focus_wide |> filter(date < d)
  if (nrow(f) == 0) return(tibble(pi_e_0 = NA, pi_e_1 = NA, y_e_0 = NA, y_e_1 = NA))
  tail(f, 1) |> select(pi_e_0, pi_e_1, y_e_0, y_e_1)
}


fetch_year <- function(code, yr) {
  url <- sprintf(
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.%s/dados?formato=csv&dataInicial=01/01/%d&dataFinal=31/12/%d",
    code, yr, yr
  )
  tmp <- tempfile(fileext = ".csv")
  ok <- try(download.file(url, tmp, method = "libcurl", quiet = TRUE,
                          headers = c("User-Agent" = "Mozilla/5.0")),
            silent = TRUE)
  if (inherits(ok, "try-error") || !file.exists(tmp) || file.size(tmp) < 50) {
    return(tibble::tibble(date = as.Date(character()),
                          selic_target = numeric()))
  }
  raw <- read.csv2(tmp, stringsAsFactors = FALSE)
  unlink(tmp)
  tibble::tibble(
    date         = as.Date(raw$data, format = "%d/%m/%Y"),
    selic_target = as.numeric(gsub(",", ".", raw$valor))
  )
}

years <- 1999:as.integer(format(Sys.Date(), "%Y"))

pieces <- list()
for (y in years) {
  pieces[[as.character(y)]] <- fetch_year(432, y)
  cat(y, ":", nrow(pieces[[as.character(y)]]), "rows\n")
  Sys.sleep(0.3)   # avoid rate-limit
}

selic_raw <- dplyr::bind_rows(pieces) |>
  dplyr::distinct() |>
  dplyr::arrange(date)

cat("\nTOTAL:", nrow(selic_raw), "rows, from",
    format(min(selic_raw$date)), "to", format(max(selic_raw$date)), "\n")

all_days <- tibble(date = seq.Date(min(selic_raw$date), max(selic_raw$date), by = "day"))
selic_daily <- all_days |>
  left_join(selic_raw, by = "date") |>
  tidyr::fill(selic_target, .direction = "down")

cat("selic_daily:", nrow(selic_daily), "rows\n")


panel <- tibble(date = copom_dates) |>
  mutate(
    year_t    = year(date),
    ib_t      = purrr::map_dbl(date, ~ get_target_on(.x - 1)),
    i_t       = purrr::map_dbl(date, ~ get_target_on(.x + 1)),
    delta_i_t = i_t - ib_t
  ) |>
  bind_cols(purrr::map_dfr(copom_dates, get_focus_before))

# Attach inflation targets for current year (pi*_0) and following year (pi*_1)
tgt0 <- inflation_targets |> rename(year_t  = year, pi_star_0 = target)
tgt1 <- inflation_targets |> rename(year_t1 = year, pi_star_1 = target)

panel <- panel |>
  mutate(year_t1 = year_t + 1L) |>
  left_join(tgt0, by = "year_t") |>
  left_join(tgt1, by = "year_t1") |>
  select(-year_t1)

# Deviations from target
panel <- panel |>
  mutate(
    dev_0 = pi_e_0 - pi_star_0,
    dev_1 = pi_e_1 - pi_star_1
  )

# Drop rows with missing regressors (mainly the very first meetings where
# Focus may be thin or target lookups miss).
panel <- panel |> filter(!is.na(delta_i_t), !is.na(pi_e_0), !is.na(pi_e_1),
                         !is.na(y_e_0),    !is.na(y_e_1))

# Meeting-to-meeting differences and lags of Delta i
panel <- panel |>
  arrange(date) |>
  mutate(
    d_dev_0    = dev_0 - lag(dev_0),
    d_dev_1    = dev_1 - lag(dev_1),
    d_y_e_0    = y_e_0 - lag(y_e_0),
    d_y_e_1    = y_e_1 - lag(y_e_1),
    delta_i_l1 = lag(delta_i_t, 1),
    delta_i_l2 = lag(delta_i_t, 2)
  )

# Estimation sample: drop initial rows that lack lags / differences
est_df <- panel |>
  filter(complete.cases(delta_i_t, ib_t, dev_0, dev_1, y_e_0, y_e_1,
                        d_dev_0, d_dev_1, d_y_e_0, d_y_e_1,
                        delta_i_l1, delta_i_l2))

message("Estimation sample: ", nrow(est_df), " meetings, from ",
        min(est_df$date), " to ", max(est_df$date))


# ---- 7. Specification (a): constant coefficients (OLS) ----------------------

rxn_formula <- delta_i_t ~ ib_t + dev_0 + dev_1 + y_e_0 + y_e_1 +
                           d_dev_0 + d_dev_1 + d_y_e_0 + d_y_e_1 +
                           delta_i_l1 + delta_i_l2

fit_rr <- lm(rxn_formula, data = est_df)
summary(fit_rr)

est_df$eps_rr <- residuals(fit_rr)


# ---- 8. Specification (b): Bai-Perron structural breaks ---------------------
#
# Following Bai & Perron (1998, 2003): test for up to m breaks, pick # of
# breaks by BIC, then estimate a piecewise-constant reaction function.
# The paper finds 3 breaks.

n_obs  <- nrow(est_df)
n_reg  <- 12                       # 11 regressors + intercept
h_safe <- max(0.10, (n_reg + 2) / n_obs)

bp_model <- strucchange::breakpoints(rxn_formula, data = est_df, h = h_safe)
print(summary(bp_model))

opt_m    <- which.min(BIC(bp_model)) - 1   # 0-indexed count of breaks
message("Bai-Perron BIC-optimal number of breaks: ", opt_m)

# Force 3 breaks as in the paper (change if you want BIC-selected instead)
m_breaks <- 3
bp_fit   <- strucchange::breakpoints(bp_model, breaks = m_breaks)

break_dates <- est_df$date[bp_fit$breakpoints]
message("Break dates (m = ", m_breaks, "): ",
        paste(format(break_dates), collapse = "; "))

# Build regime dummy and estimate piecewise OLS
est_df$regime <- factor(strucchange::breakfactor(bp_fit, breaks = m_breaks))
fit_sb <- lm(update(rxn_formula, . ~ regime / (.) + 0), data = est_df)
est_df$eps_sb <- residuals(fit_sb)


# ---- 9. Specification (c): Bayesian time-varying parameters -----------------
#
# shrinkTVP implements Cadonna, Frühwirth-Schnatter & Knaus (2020)
# triple-gamma / NGG shrinkage prior. This is the exact package cited in the
# paper (Knaus et al. 2021).
#
# The paper uses 200,000 iterations with 100,000 burn-in, thinning 20.
# That takes hours. We use a lighter default; scale up for the final run.

n_iter  <- 30000     # paper: 200000
n_burn  <- 10000     # paper: 100000
n_thin  <- 10        # paper: 20

message("Estimating TVP reaction function via shrinkTVP ...")
fit_tvp <- shrinkTVP::shrinkTVP(
  formula  = rxn_formula,
  data     = est_df,
  mod_type = "triple",
  niter    = n_iter,
  nburn    = n_burn,
  nthin    = n_thin,
  display_progress = TRUE
)

# Residuals: use the residuals() method for shrinkTVP (posterior draws per t).
# Take the posterior median across draws to get one shock per meeting.
res_draws <- residuals(fit_tvp)     # matrix: draws x T
est_df$eps_tvp <- apply(res_draws, 2, median)


# ---- 10. Collect shocks, save, plot -----------------------------------------

shocks <- est_df |>
  select(date, delta_i_t, eps_rr, eps_sb, eps_tvp)

out_dir <- "./output"
dir.create(out_dir, showWarnings = FALSE)

readr::write_csv(shocks, file.path(out_dir, "mp_shocks_meeting.csv"))

# Monthly aggregation (sum of shocks within calendar month), useful for SVAR-IV
shocks_monthly <- shocks |>
  mutate(ym = floor_date(date, "month")) |>
  group_by(ym) |>
  summarise(across(c(eps_rr, eps_sb, eps_tvp), ~ sum(.x, na.rm = TRUE)),
            .groups = "drop")

readr::write_csv(shocks_monthly, file.path(out_dir, "mp_shocks_monthly.csv"))

# Plot
shocks_long <- shocks |>
  pivot_longer(starts_with("eps_"), names_to = "spec", values_to = "shock")

p <- ggplot(shocks_long, aes(x = date, y = shock, colour = spec)) +
  geom_hline(yintercept = 0, linetype = 2, alpha = 0.4) +
  geom_line(alpha = 0.85) +
  facet_wrap(~ spec, ncol = 1, scales = "free_y") +
  labs(x = NULL, y = "p.p.",
       title = "Narrative monetary policy shocks for Brazil",
       subtitle = "Residuals of Copom reaction function (meeting frequency)") +
  theme_minimal() + theme(legend.position = "none")

ggsave(file.path(out_dir, "mp_shocks.png"), p, width = 9, height = 7, dpi = 150)

message("Done. Shocks written to ", normalizePath(out_dir))

