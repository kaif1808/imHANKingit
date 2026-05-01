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
rm(crosswalk)

  
  cols_to_drop <- c(
    "ref_month_in_quarter",
    "ref_fortnight_in_month",
    "ref_fortnight_in_quarter",
    "ref_week_in_month",
    "ref_week_in_quarter",
    "ref_fortnight_yyyyff",
    "ref_week_yyyyww",
    "determined_month",
    "determined_fortnight",
    "determined_week"
  )
  drop_now <- intersect(cols_to_drop, names(result))
  if (length(drop_now) > 0L) {
    result[, (drop_now) := NULL]
  }
write_parquet(result, "pnadc_matched_with_periods.parquet")