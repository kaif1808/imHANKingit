library(data.table)
library(arrow)
library(ggplot2)
national_income <- fread("Data/pnadcperiods_rendhabnominaltodos_2026-05-15.csv")
p <- ggplot(national_income, aes(x = date, y = monthly_x13)) +
  geom_line(colour = "#2c6fad", linewidth = 0.7) +
  geom_smooth(method = "loess", span = 0.2, se = FALSE,
              colour = "#d62728", linewidth = 0.5, linetype = "dashed") +
  scale_x_date(date_breaks = "1 year", date_labels = "%Y") +
  scale_y_continuous(labels = scales::comma_format(big.mark = ",")) +
  labs(
    title    = "Brazil: National Weighted Mean Habitual Real Income",
    subtitle = "PNADC monthly panel — determined-month observations only",
    x        = NULL,
    y        = "Mean real income (BRL)",
    caption  = "Source: PNADC via pnadc_matched_with_periods.parquet"
  ) +
  theme_minimal(base_size = 12) +
  theme(
    axis.text.x      = element_text(angle = 45, hjust = 1),
    panel.grid.minor = element_blank()
  )

ggsave("results/plots/basic_state_month_lp/pnadc_package_ts.png",
       p, width = 10, height = 5, dpi = 150)