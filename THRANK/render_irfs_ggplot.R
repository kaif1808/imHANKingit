#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
thrank_dir <- if (length(args) >= 1) args[[1]] else "THRANK/results/baseline"
compare_dir <- if (length(args) >= 2) args[[2]] else "THRANK/results/compare_baseline"
out_dir <- if (length(args) >= 3) args[[3]] else compare_dir

dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
plot_dir <- file.path(out_dir, "plots")
dir.create(plot_dir, recursive = TRUE, showWarnings = FALSE)

suppressPackageStartupMessages({
  library(ggplot2)
  library(dplyr)
})

pretty_dataset <- function(x) {
  recode(
    x,
    lp_controls = "LP controls",
    lp_income = "LP income",
    lp_wealth = "LP wealth"
  )
}

thrank_pos_file <- file.path(thrank_dir, "irf_mp_pos_shock_cumulative.csv")
thrank_legacy_file <- file.path(thrank_dir, "irf_mp_shock_cumulative.csv")
thrank_neg_file <- file.path(thrank_dir, "irf_mp_neg_shock_cumulative.csv")
has_neg_file <- file.exists(thrank_neg_file)

if (file.exists(thrank_pos_file)) {
  thrank_file <- thrank_pos_file
} else if (file.exists(thrank_legacy_file)) {
  thrank_file <- thrank_legacy_file
} else {
  stop(
    "Missing THRANK cumulative IRF file. Need either ",
    thrank_pos_file,
    " or ",
    thrank_legacy_file
  )
}

thrank <- read.csv(thrank_file, check.names = FALSE)

series_map <- data.frame(
  var = c("Y", "cR", "cW", "cP", "pi", "R", "r", "q", "hW", "bW"),
  label = c("Output", "Ricardian Consumption", "WH2M Consumption", "PH2M Consumption", "Inflation", "Policy Rate", "Real Rate", "House Price", "WH2M Housing", "WH2M Debt"),
  unit = c("pct", "pct", "pct", "pct", "bps", "bps", "bps", "pct", "pct", "pct"),
  scale = c(100, 100, 100, 100, 10000, 10000, 10000, 100, 100, 100),
  stringsAsFactors = FALSE
)

plot_df <- do.call(rbind, lapply(seq_len(nrow(series_map)), function(i) {
  v <- series_map$var[[i]]
  if (!v %in% names(thrank)) return(NULL)
  data.frame(
    horizon = thrank$t,
    variable = series_map$label[[i]],
    unit = series_map$unit[[i]],
    value = thrank[[v]] * series_map$scale[[i]],
    stringsAsFactors = FALSE
  )
}))

p1 <- ggplot(plot_df, aes(x = horizon, y = value)) +
  geom_hline(yintercept = 0, color = "#8d99ae", linewidth = 0.35) +
  geom_line(color = "#0b4f6c", linewidth = 0.8) +
  facet_wrap(~variable, scales = "free_y", ncol = 2) +
  labs(
    title = "THRANK Cumulative Monetary IRFs",
    subtitle = "Units: pct for real quantities, bps for rates and inflation",
    x = "Horizon (months)",
    y = "Response"
  ) +
  theme_bw(base_size = 11) +
  theme(
    plot.title = element_text(face = "bold"),
    strip.text = element_text(face = "bold"),
    panel.grid.minor = element_blank(),
    panel.grid.major = element_line(color = "gray92", linewidth = 0.3)
  )

ggsave(
  filename = file.path(plot_dir, "thrank_irf_ggplot_cumulative.png"),
  plot = p1,
  width = 12,
  height = 10,
  dpi = 220
)

aligned_file <- file.path(compare_dir, "thrank_lp_aligned_series.csv")
if (file.exists(aligned_file)) {
  aligned <- read.csv(aligned_file, check.names = FALSE)

  required_cols <- c(
    "dataset",
    "group",
    "direction",
    "horizon",
    "lp_estimate_1sd",
    "lp_ci_low_1sd",
    "lp_ci_high_1sd",
    "model_1sd_termshock"
  )
  missing_cols <- setdiff(required_cols, names(aligned))
  if (length(missing_cols) > 0) {
    stop("Aligned series missing required columns: ", paste(missing_cols, collapse = ", "))
  }

  overlay_subtitle <- if (has_neg_file) {
    "Expansionary panels use direct THRANK expansionary-shock IRFs"
  } else {
    "Expansionary panels use sign inversion fallback (no separate expansionary IRF file)"
  }

  plot_aligned <- aligned %>%
    mutate(
      dataset = factor(dataset, levels = c("lp_controls", "lp_income", "lp_wealth")),
      dataset_label = pretty_dataset(as.character(dataset)),
      facet_term = factor(
        paste(group, direction),
        levels = c(
          "PH2M contractionary",
          "PH2M expansionary",
          "WH2M contractionary",
          "WH2M expansionary"
        )
      )
    )

  p2 <- ggplot(plot_aligned, aes(x = horizon)) +
    geom_hline(yintercept = 0, color = "#8d99ae", linewidth = 0.35) +
    geom_ribbon(
      aes(ymin = lp_ci_low_1sd, ymax = lp_ci_high_1sd),
      fill = "#bdbdbd",
      alpha = 0.35
    ) +
    geom_line(aes(y = lp_estimate_1sd, color = "Empirical LP"), linewidth = 0.9) +
    geom_line(
      aes(y = model_1sd_termshock, color = "THRANK structural"),
      linewidth = 0.85,
      linetype = "22"
    ) +
    scale_color_manual(
      values = c(
        "Empirical LP" = "#1f78b4",
        "THRANK structural" = "#d7301f"
      )
    ) +
    facet_grid(dataset_label ~ facet_term, scales = "free_y") +
    labs(
      title = "DI-shock TWFE LP vs THRANK (Cumulative, 1-SD term-shock units)",
      subtitle = overlay_subtitle,
      x = "Horizon (months)",
      y = "Cumulative response",
      color = NULL
    ) +
    theme_bw(base_size = 10.5) +
    theme(
      plot.title = element_text(face = "bold"),
      strip.text = element_text(face = "bold"),
      legend.position = "top",
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(color = "gray92", linewidth = 0.3)
    )

  ggsave(
    filename = file.path(plot_dir, "thrank_vs_lp_overlay_ggplot.png"),
    plot = p2,
    width = 16,
    height = 10,
    dpi = 240
  )

  plot_dataset_overlay <- function(dataset_key, horizon_max) {
    sub <- plot_aligned %>%
      filter(dataset == dataset_key, horizon <= horizon_max)
    if (nrow(sub) == 0) {
      return(invisible(NULL))
    }

    y_vals <- c(
      sub$lp_ci_low_1sd,
      sub$lp_ci_high_1sd,
      sub$lp_estimate_1sd,
      sub$model_1sd_termshock
    )
    y_lim <- max(abs(y_vals), na.rm = TRUE)
    if (!is.finite(y_lim) || y_lim < 1e-4) {
      y_lim <- 1e-3
    }
    y_lim <- 1.08 * y_lim

    ds_label <- pretty_dataset(as.character(dataset_key))
    p_ds <- ggplot(sub, aes(x = horizon)) +
      geom_hline(yintercept = 0, color = "#8d99ae", linewidth = 0.35) +
      geom_ribbon(
        aes(ymin = lp_ci_low_1sd, ymax = lp_ci_high_1sd),
        fill = "#bdbdbd",
        alpha = 0.35
      ) +
      geom_line(aes(y = lp_estimate_1sd, color = "Empirical LP"), linewidth = 1.0) +
      geom_line(
        aes(y = model_1sd_termshock, color = "THRANK structural"),
        linewidth = 0.95,
        linetype = "22"
      ) +
      scale_color_manual(
        values = c(
          "Empirical LP" = "#1f78b4",
          "THRANK structural" = "#d7301f"
        )
      ) +
      facet_wrap(~facet_term, ncol = 2, scales = "fixed") +
      coord_cartesian(ylim = c(-y_lim, y_lim)) +
      scale_x_continuous(breaks = seq(0, horizon_max, by = 6), limits = c(0, horizon_max)) +
      labs(
        title = paste0(ds_label, ": empirical LP vs THRANK"),
        subtitle = paste0(
          "Cumulative response in 1-SD term-shock units, H0-H",
          horizon_max,
          " | ",
          overlay_subtitle
        ),
        x = "Horizon (months)",
        y = "Cumulative response",
        color = NULL
      ) +
      theme_bw(base_size = 11.5) +
      theme(
        plot.title = element_text(face = "bold"),
        strip.text = element_text(face = "bold"),
        legend.position = "top",
        panel.grid.minor = element_blank(),
        panel.grid.major = element_line(color = "gray92", linewidth = 0.3)
      )

    out_name <- paste0(
      "thrank_vs_lp_",
      as.character(dataset_key),
      "_overlay_h0_h",
      horizon_max,
      ".png"
    )
    ggsave(
      filename = file.path(plot_dir, out_name),
      plot = p_ds,
      width = 12,
      height = 8,
      dpi = 260
    )
  }

  for (ds in levels(plot_aligned$dataset)) {
    plot_dataset_overlay(ds, horizon_max = 48)
    plot_dataset_overlay(ds, horizon_max = 24)
  }
}

message("Wrote ggplot IRF figures to: ", plot_dir)
