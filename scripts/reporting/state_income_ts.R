library(data.table)
library(arrow)
library(ggplot2)

pnadc <- as.data.table(read_parquet("pnadc_matched_with_periods.parquet"))

# ── 1. State × month weighted mean income ────────────────────────────────────

state_month_income <- pnadc[
  determined_month == TRUE & !is.na(rendimento_habitual_real),
  .(
    mean_income  = sum(rendimento_habitual_real * weight_monthly, na.rm = TRUE) /
                     sum(weight_monthly, na.rm = TRUE),
    n_obs        = .N,
    total_weight = sum(weight_monthly, na.rm = TRUE)
  ),
  by = .(UF, ref_month_yyyymm)
]

month_key <- sprintf("%06d", as.integer(state_month_income$ref_month_yyyymm))
state_month_income[, `:=`(
  uf_code = as.integer(UF),
  year    = as.integer(substr(month_key, 1, 4)),
  month   = as.integer(substr(month_key, 5, 6))
)]
setorder(state_month_income, uf_code, ref_month_yyyymm)

# ── 2. STL seasonal adjustment — per state ────────────────────────────────────
# Requires a complete monthly grid; interpolate isolated NAs linearly before
# decomposing, then re-attach SA = trend + remainder.

stl_decomp <- function(x) {
  # Linear interpolation for any interior NAs (rare edge states)
  if (any(is.na(x))) {
    idx <- seq_along(x)
    x   <- approx(idx[!is.na(x)], x[!is.na(x)], xout = idx)$y
  }
  fit <- stl(ts(x, frequency = 12), s.window = 13, robust = TRUE)
  list(
    sa    = drop(fit$time.series[, "trend"] + fit$time.series[, "remainder"]),
    trend = drop(fit$time.series[, "trend"])
  )
}

state_month_income[, c("mean_income_sa", "mean_income_trend") := {
  d <- stl_decomp(mean_income)
  list(d$sa, d$trend)
}, by = UF]

# ── 3. National aggregate ─────────────────────────────────────────────────────

national_income <- pnadc[
  determined_month == TRUE & !is.na(rendimento_habitual_real),
  .(
    mean_income  = sum(rendimento_habitual_real * weight_monthly, na.rm = TRUE) /
                     sum(weight_monthly, na.rm = TRUE),
    n_obs        = .N,
    total_weight = sum(weight_monthly, na.rm = TRUE)
  ),
  by = ref_month_yyyymm
]

nat_key <- sprintf("%06d", as.integer(national_income$ref_month_yyyymm))
national_income[, `:=`(
  year  = as.integer(substr(nat_key, 1, 4)),
  month = as.integer(substr(nat_key, 5, 6))
)]
national_income[, date := as.Date(sprintf("%d-%02d-01", year, month))]
setorder(national_income, ref_month_yyyymm)

nat_decomp <- stl_decomp(national_income$mean_income)
national_income[, mean_income_sa    := nat_decomp$sa]
national_income[, mean_income_trend := nat_decomp$trend]

# ── 4. Write CSVs ─────────────────────────────────────────────────────────────

for (d in c("results/tables", "results/plots/basic_state_month_lp")) {
  if (!dir.exists(d)) dir.create(d, recursive = TRUE, showWarnings = FALSE)
}

fwrite(state_month_income, "results/tables/state_month_income_ts.csv")
fwrite(national_income,    "results/tables/national_income_ts.csv")

# ── 5. Plots ──────────────────────────────────────────────────────────────────

# 5a. Raw with STL trend overlay
p_raw <- ggplot(national_income, aes(x = date)) +
  geom_line(aes(y = mean_income), colour = "#2c6fad", linewidth = 0.7) +
  geom_line(aes(y = mean_income_trend), colour = "#d62728",
            linewidth = 0.8, linetype = "dashed") +
  scale_x_date(date_breaks = "1 year", date_labels = "%Y") +
  scale_y_continuous(labels = scales::comma_format()) +
  labs(
    title    = "Brazil: National Weighted Mean Habitual Real Income",
    subtitle = "Blue = raw series · Red dashed = STL trend",
    x        = NULL, y = "Mean real income (BRL)",
    caption  = "Source: PNADC via pnadc_matched_with_periods.parquet"
  ) +
  theme_minimal(base_size = 12) +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        panel.grid.minor = element_blank())

ggsave("results/plots/basic_state_month_lp/national_income_ts.png",
       p_raw, width = 10, height = 5, dpi = 150)

# 5b. Three-panel: raw / SA / trend
plot_dt <- melt(
  national_income[, .(
    date,
    `1. Raw`                 = mean_income,
    `2. Seasonally adjusted` = mean_income_sa,
    `3. STL trend`           = mean_income_trend
  )],
  id.vars = "date", variable.name = "series", value.name = "income"
)

p_sa <- ggplot(plot_dt, aes(x = date, y = income, colour = series)) +
  geom_line(linewidth = 0.7) +
  facet_wrap(~series, ncol = 1, scales = "free_y") +
  scale_colour_manual(
    values = c("1. Raw"                 = "#2c6fad",
               "2. Seasonally adjusted" = "#e07b00",
               "3. STL trend"           = "#2ca02c"),
    guide = "none"
  ) +
  scale_x_date(date_breaks = "1 year", date_labels = "%Y") +
  scale_y_continuous(labels = scales::comma_format()) +
  labs(
    title    = "Brazil: National Income — Raw / SA / Trend",
    subtitle = "STL decomposition, s.window = 13, robust = TRUE · SA = trend + remainder",
    x = NULL, y = "Mean real income (BRL)",
    caption  = "Source: PNADC via pnadc_matched_with_periods.parquet"
  ) +
  theme_minimal(base_size = 12) +
  theme(axis.text.x    = element_text(angle = 45, hjust = 1),
        panel.grid.minor = element_blank(),
        strip.text     = element_text(face = "bold"))

ggsave("results/plots/basic_state_month_lp/national_income_ts_sa.png",
       p_sa, width = 10, height = 9, dpi = 150)

# ── 6. Merge mean_income + mean_income_sa into LP dataset ────────────────────

lp_path <- "results/datasets/basic_state_month_lp/state_month_lp_dataset.csv"
lp <- fread(lp_path)

income_keys <- state_month_income[, .(uf_code, year, month, mean_income, mean_income_sa, mean_income_trend)]

for (col in c("mean_income", "mean_income_sa", "mean_income_trend")) {
  if (col %in% names(lp)) lp[, (col) := NULL]
}

lp <- merge(lp, income_keys, by = c("uf_code", "year", "month"), all.x = TRUE)
fwrite(lp, lp_path)

# ── 7. Summary ────────────────────────────────────────────────────────────────

cat(sprintf("State series : %d rows, %d states, %d–%d\n",
  nrow(state_month_income), length(unique(state_month_income$UF)),
  min(state_month_income$ref_month_yyyymm),
  max(state_month_income$ref_month_yyyymm)))
cat(sprintf("National ts  : %d months  raw %.0f–%.0f  SA %.0f–%.0f BRL\n",
  nrow(national_income),
  min(national_income$mean_income),   max(national_income$mean_income),
  min(national_income$mean_income_sa), max(national_income$mean_income_sa)))
cat(sprintf("LP dataset   : %d rows — mean_income %d / mean_income_sa %d / mean_income_trend %d matched\n",
  nrow(lp), sum(!is.na(lp$mean_income)), sum(!is.na(lp$mean_income_sa)),
  sum(!is.na(lp$mean_income_trend))))
