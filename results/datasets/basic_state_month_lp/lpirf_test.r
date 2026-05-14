library(lpirfs)
library(data.table)
library(ggplot2)

z_crit <- 1.96
hor <- 48

data <- fread("results/datasets/basic_state_month_lp/state_month_lp_dataset.csv")

# Keep a minimal, stable panel for lpirfs estimation.
panel_dt <- data[, .(
  uf_code,
  t_index,
  log_consumption,
  mp_shock_di
)]

# Use lpirfs directly for marginal IRFs (not cumulative multipliers),
# then accumulate to get long-run cumulative effects.
irf_obj <- lp_lin_panel(
  data_set = panel_dt,
  endog_data = "log_consumption",
  shock = "mp_shock_di",
  cumul_mult = FALSE,
  diff_shock = FALSE,
  panel_model = "within",
  panel_effect = "individual",
  robust_cov = NULL,
  confint = z_crit,
  hor = hor
)

irf_mean <- as.numeric(irf_obj$irf_panel_mean[1, ])
irf_low <- as.numeric(irf_obj$irf_panel_low[1, ])
irf_high <- as.numeric(irf_obj$irf_panel_up[1, ])
horizon <- seq_along(irf_mean) - 1

# Recover horizon-specific SE from the symmetric CI.
irf_se <- ((irf_high - irf_mean) + (irf_mean - irf_low)) / (2 * z_crit)

cum_irf <- cumsum(irf_mean)
cum_se <- sqrt(cumsum(irf_se^2))
cum_se <- cummax(cum_se) # enforce monotone widening uncertainty

out <- data.table(
  horizon = horizon,
  marginal_irf = irf_mean,
  marginal_se = irf_se,
  marginal_low = irf_low,
  marginal_high = irf_high,
  cumulative_irf = cum_irf,
  cumulative_se = cum_se,
  cumulative_low = cum_irf - z_crit * cum_se,
  cumulative_high = cum_irf + z_crit * cum_se
)

dir.create("results/tables/basic_state_month_lp", recursive = TRUE, showWarnings = FALSE)
dir.create("results/plots/basic_state_month_lp", recursive = TRUE, showWarnings = FALSE)

fwrite(out, "results/tables/basic_state_month_lp/lpirf_test_cumulative_irf.csv")

p <- ggplot(out, aes(x = horizon, y = cumulative_irf)) +
  geom_ribbon(aes(ymin = cumulative_low, ymax = cumulative_high), alpha = 0.18, fill = "#2C7FB8") +
  geom_line(linewidth = 1.1, color = "#1D4E89") +
  geom_hline(yintercept = 0, linetype = "dashed", color = "grey45") +
  labs(
    title = "Cumulative IRF from lpirfs",
    subtitle = "Shock: mp_shock_di (within-state panel LP)",
    x = "Horizon (months)",
    y = "Cumulative log-consumption response"
  ) +
  theme_minimal(base_size = 12)

ggsave(
  filename = "results/plots/basic_state_month_lp/lpirf_test_cumulative_irf.png",
  plot = p,
  width = 10,
  height = 6,
  dpi = 300
)
