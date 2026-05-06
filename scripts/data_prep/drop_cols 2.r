library(data.table)
library(dplyr)
library(arrow)
library(PNADCperiods)

pnadc <- as.data.table(read_parquet("pnadc_matched.parquet"))

# Identify reference periods (month, fortnight, week)
crosswalk <- pnadc_identify_periods(pnadc, verbose = TRUE)

# Check determination rates
crosswalk[, .(
  month_rate = mean(determined_month),
  fortnight_rate = mean(determined_fortnight),
  week_rate = mean(determined_week)
)]

result <- pnadc_apply_periods(
  pnadc,
  crosswalk,
  weight_var = "V1028",
  anchor = "quarter",
  calibrate = TRUE,
  calibration_unit = "month"
)

rm(pnadc)
fwrite(crosswalk, "crosswalk.csv")
rm(crosswalk)

  
  cols_to_drop <- c(
    "ref_fortnight_in_month",
    "ref_fortnight_in_quarter",
    "ref_week_in_month",
    "ref_week_in_quarter",
    "ref_fortnight_yyyyff",
    "ref_week_yyyyww",
    "determined_fortnight",
    "determined_week"
  )
  drop_now <- intersect(cols_to_drop, names(result))
  if (length(drop_now) > 0L) {
    result[, (drop_now) := NULL]
  }
write_parquet(result, "pnadc_matched_with_periods.parquet")

# Monthly unemployment rate
monthly_unemployment <- result[determined_month == TRUE, .(
  unemployment_rate = sum((VD4002 == 2) * weight_monthly, na.rm = TRUE) /
    sum((VD4001 == 1) * weight_monthly, na.rm = TRUE)
), by = ref_month_yyyymm]

# Monthly unemployment rate by state
monthly_unemployment_by_state <- result[determined_month == TRUE, .(
  unemployment_rate = sum((VD4002 == 2) * weight_monthly, na.rm = TRUE) /
    sum((VD4001 == 1) * weight_monthly, na.rm = TRUE),
  employed_weight = sum((VD4001 == 1) * weight_monthly, na.rm = TRUE),
  unemployed_weight = sum((VD4002 == 2) * weight_monthly, na.rm = TRUE)
), by = .(UF, ref_month_yyyymm)]

# Labour force participation by state and month
monthly_lfpr_by_state <- result[, .(
  labour_force_participation_rate = sum((VD4001 %in% c(1L, 2L)) * weight_monthly, na.rm = TRUE) /
    sum(weight_monthly, na.rm = TRUE),
  labour_force_weight = sum((VD4001 %in% c(1L, 2L)) * weight_monthly, na.rm = TRUE),
  population = sum(weight_monthly, na.rm = TRUE)
), by = .(UF, ref_month_yyyymm)]

# Employment composition by work type among employed people
monthly_work_type_by_state <- result[VD4001 == 1L, .(
  formal_share = sum((formal == 1) * weight_monthly, na.rm = TRUE) /
    sum(weight_monthly, na.rm = TRUE),
  informal_share = sum((informal == 1) * weight_monthly, na.rm = TRUE) /
    sum(weight_monthly, na.rm = TRUE),
  conta_propria_share = sum((conta_propria == 1) * weight_monthly, na.rm = TRUE) /
    sum(weight_monthly, na.rm = TRUE),
  employed_weight = sum(weight_monthly, na.rm = TRUE)
), by = .(UF, ref_month_yyyymm)]

# Monthly population
monthly_pop <- result[, .(
  population = sum(weight_monthly, na.rm = TRUE)
), by = ref_month_yyyymm]

# Combined state-month labour-market summary
state_month_labour_market <- Reduce(
  function(x, y) merge(x, y, by = c("UF", "ref_month_yyyymm"), all = TRUE),
  list(
    monthly_unemployment_by_state,
    monthly_lfpr_by_state,
    monthly_work_type_by_state
  )
)
state_month_labour_market[, month_key := sprintf("%06d", as.integer(ref_month_yyyymm))]
state_month_labour_market[, `:=`(
  uf_code = as.integer(UF),
  year = as.integer(substr(month_key, 1, 4)),
  month = as.integer(substr(month_key, 5, 6))
)]
state_month_labour_market[, month_key := NULL]

if (!dir.exists("results/tables")) {
  dir.create("results/tables", recursive = TRUE, showWarnings = FALSE)
}
write_parquet(state_month_labour_market, "results/tables/state_month_labour_market.parquet")
