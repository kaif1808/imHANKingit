from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render IRF CSVs into PNG images without matplotlib.")
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=Path("THRANK/output/irf_mp_shock.csv"),
        help="Path to monetary-shock IRF CSV.",
    )
    parser.add_argument(
        "--output-png",
        type=Path,
        default=Path("THRANK/output/irf_mp_shock_pillow.png"),
        help="Output PNG path.",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="THRANK Monetary Shock IRFs",
        help="Figure title.",
    )
    return parser.parse_args()


def _fit_series(y: np.ndarray, left: int, top: int, width: int, height: int) -> list[tuple[float, float]]:
    t = np.arange(len(y), dtype=float)
    y_min = float(np.min(y))
    y_max = float(np.max(y))
    if abs(y_max - y_min) < 1e-12:
        y_max = y_min + 1.0
    x = left + (t / max(1.0, len(y) - 1.0)) * width
    y_norm = (y - y_min) / (y_max - y_min)
    y_px = top + (1.0 - y_norm) * height
    return list(zip(x, y_px))


def render_irf_png(input_csv: Path, output_png: Path, title: str) -> None:
    if not input_csv.exists():
        raise FileNotFoundError(f"Missing IRF CSV: {input_csv}")

    df = pd.read_csv(input_csv)
    if "t" not in df.columns:
        raise ValueError(f"{input_csv} must include a 't' column.")

    vars_to_plot = [c for c in df.columns if c != "t"]
    if not vars_to_plot:
        raise ValueError("No IRF variables found to plot.")

    ncols = 4
    nrows = int(np.ceil(len(vars_to_plot) / ncols))
    panel_w, panel_h = 280, 180
    margin_x, margin_y = 20, 24
    title_h = 50
    width = margin_x * 2 + ncols * panel_w
    height = title_h + margin_y + nrows * panel_h + margin_y

    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.text((margin_x, 16), title, fill="black", font=font)

    for idx, var in enumerate(vars_to_plot):
        row = idx // ncols
        col = idx % ncols
        x0 = margin_x + col * panel_w
        y0 = title_h + row * panel_h
        x1 = x0 + panel_w - 16
        y1 = y0 + panel_h - 20

        draw.rectangle((x0, y0, x1, y1), outline="#C0C0C0", width=1)
        draw.text((x0 + 6, y0 + 4), var, fill="black", font=font)

        plot_left = x0 + 8
        plot_top = y0 + 20
        plot_w = (x1 - x0) - 16
        plot_h = (y1 - y0) - 30

        series = df[var].to_numpy(dtype=float)
        y_min = float(np.min(series))
        y_max = float(np.max(series))
        if y_min <= 0 <= y_max:
            zero_rel = (0.0 - y_min) / (y_max - y_min + 1e-16)
            y_zero = plot_top + (1.0 - zero_rel) * plot_h
            draw.line([(plot_left, y_zero), (plot_left + plot_w, y_zero)], fill="#AAAAAA", width=1)

        points = _fit_series(series, plot_left, plot_top, plot_w, plot_h)
        draw.line(points, fill="#0B5FFF", width=2)

        draw.text((plot_left, plot_top + plot_h + 2), f"min={y_min:.4g}", fill="#555555", font=font)
        draw.text((plot_left + plot_w - 70, plot_top + plot_h + 2), f"max={y_max:.4g}", fill="#555555", font=font)

    output_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_png)


def main() -> None:
    args = parse_args()
    render_irf_png(args.input_csv, args.output_png, args.title)
    print(f"Wrote IRF image: {args.output_png}")


if __name__ == "__main__":
    main()

