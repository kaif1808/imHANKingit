library(data.table)
library(datazoom.social)
# Download the data
load_pnadc(
  save_to = "PNAD-C-Treated",
  years = 2015:2017,
  panel = "advanced",
  raw_data = FALSE
)

load_pnadc(
  save_to = "PNAD-C-Treated",
  years = 2017:2019,
  panel = "advanced",
  raw_data = FALSE
)

load_pnadc(
  save_to = "PNAD-C-Treated",
  years = 2019:2021,
  panel = "advanced",
  raw_data = FALSE
)