#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
compare_dir <- if (length(args) >= 1) args[[1]] else "THRANK/results/compare_tuned_joint_di_twfe"
plot_dir <- file.path(compare_dir, "plots")
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

f <- file.path(compare_dir, "augmented_scaling_aligned.csv")
if (!file.exists(f)) {
  stop("Missing file: ", f)
}

d <- read.csv(f, check.names = FALSE)

pos <- d %>%
  transmute(
    dataset = dataset,
    group = group,
    direction = "contractionary",
    horizon = horizon,
    y = y_pos,
    pred_struct = x_pos,
    pred_aug = pred_pos_aug
  )
neg <- d %>%
  transmute(
    dataset = dataset,
    group = group,
    direction = "expansionary",
    horizon = horizon,
    y = y_neg,
    pred_struct = x_neg,
    pred_aug = pred_neg_aug
  )

pdat <- bind_rows(pos, neg) %>%
  mutate(
    dataset = factor(dataset, levels = c("lp_controls", "lp_income", "lp_wealth")),
    dataset_label = pretty_dataset(as.character(dataset)),
    facet_term = factor(
      paste(group, direction),
      levels = c("PH2M contractionary", "PH2M expansionary", "WH2M contractionary", "WH2M expansionary")
    )
  )

p <- ggplot(pdat, aes(x = horizon)) +
  geom_hline(yintercept = 0, color = "#8d99ae", linewidth = 0.35) +
  geom_line(aes(y = y, color = "Empirical LP"), linewidth = 0.8) +
  geom_line(aes(y = pred_struct, color = "THRANK structural"), linewidth = 0.75, linetype = "22") +
  geom_line(aes(y = pred_aug, color = "THRANK + augmented layer"), linewidth = 0.8, linetype = "solid") +
  scale_color_manual(
    values = c(
      "Empirical LP" = "#1f78b4",
      "THRANK structural" = "#d7301f",
      "THRANK + augmented layer" = "#1a9850"
    )
  ) +
  facet_grid(dataset_label ~ facet_term, scales = "free_y") +
  labs(
    title = "DI-TWFE LP vs THRANK: Structural vs Augmented Layer",
    subtitle = "Augmented layer adds dataset/group gains and group-level expansionary asymmetry",
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

ggsave(file.path(plot_dir, "thrank_vs_lp_overlay_augmented.png"), p, width = 16, height = 10, dpi = 240)

plot_dataset_overlay <- function(dataset_key, horizon_max) {
  sub <- pdat %>%
    filter(dataset == dataset_key, horizon <= horizon_max)
  if (nrow(sub) == 0) {
    return(invisible(NULL))
  }

  y_vals <- c(
    sub$y,
    sub$pred_struct,
    sub$pred_aug
  )
  y_lim <- max(abs(y_vals), na.rm = TRUE)
  if (!is.finite(y_lim) || y_lim < 1e-4) {
    y_lim <- 1e-3
  }
  y_lim <- 1.08 * y_lim

  ds_label <- pretty_dataset(as.character(dataset_key))
  p_ds <- ggplot(sub, aes(x = horizon)) +
    geom_hline(yintercept = 0, color = "#8d99ae", linewidth = 0.35) +
    geom_line(aes(y = y, color = "Empirical LP"), linewidth = 1.0) +
    geom_line(aes(y = pred_struct, color = "THRANK structural"), linewidth = 0.95, linetype = "22") +
    geom_line(aes(y = pred_aug, color = "THRANK + augmented layer"), linewidth = 0.95) +
    scale_color_manual(
      values = c(
        "Empirical LP" = "#1f78b4",
        "THRANK structural" = "#d7301f",
        "THRANK + augmented layer" = "#1a9850"
      )
    ) +
    facet_wrap(~facet_term, ncol = 2, scales = "fixed") +
    coord_cartesian(ylim = c(-y_lim, y_lim)) +
    scale_x_continuous(breaks = seq(0, horizon_max, by = 6), limits = c(0, horizon_max)) +
    labs(
      title = paste0(ds_label, ": structural vs augmented THRANK fit"),
      subtitle = paste0("Cumulative response in 1-SD term-shock units, H0-H", horizon_max),
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
    "_overlay_augmented_h0_h",
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

for (ds in levels(pdat$dataset)) {
  plot_dataset_overlay(ds, horizon_max = 48)
  plot_dataset_overlay(ds, horizon_max = 24)
}

message("Wrote augmented overlay to: ", plot_dir)
