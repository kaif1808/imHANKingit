from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


SERIES_META = {
    "Y": ("Output (pct)", 100.0),
    "cR": ("Ricardian Consumption (pct)", 100.0),
    "cW": ("WH2M Consumption (pct)", 100.0),
    "cP": ("PH2M Consumption (pct)", 100.0),
    "pi": ("Inflation (bps)", 10000.0),
    "R": ("Policy Rate (bps)", 10000.0),
    "r": ("Real Rate (bps)", 10000.0),
    "X": ("Markup (pct)", 100.0),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build interpretable monetary IRFs (tables + image).")
    parser.add_argument(
        "--input-csv",
        type=Path,
        required=True,
        help="Path to irf_mp_shock.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for outputs.",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="THRANK Monetary Shock IRFs",
        help="Figure title.",
    )
    return parser.parse_args()


def _render_line_panel(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    label: str,
    panel: tuple[int, int, int, int],
    color: str,
    font: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = panel
    draw.rectangle(panel, outline="#C8CDD8", width=1)
    draw.text((x0 + 8, y0 + 6), label, fill="black", font=font)

    left = x0 + 8
    top = y0 + 24
    right = x1 - 8
    bottom = y1 - 16
    w = max(1, right - left)
    h = max(1, bottom - top)

    x = df[x_col].to_numpy()
    y = df[y_col].to_numpy()
    ymin = float(y.min())
    ymax = float(y.max())
    if abs(ymax - ymin) < 1e-12:
        ymax = ymin + 1.0

    if ymin <= 0.0 <= ymax:
        zero_rel = (0.0 - ymin) / (ymax - ymin)
        yzero = top + (1.0 - zero_rel) * h
        draw.line([(left, yzero), (right, yzero)], fill="#9EA3AE", width=1)

    pts = []
    for xi, yi in zip(x, y, strict=True):
        px = left + (float(xi) - float(x.min())) / max(1e-12, float(x.max()) - float(x.min())) * w
        py = top + (1.0 - (float(yi) - ymin) / (ymax - ymin)) * h
        pts.append((px, py))
    draw.line(pts, fill=color, width=2)
    draw.text((left, bottom + 2), f"min {ymin:.3g}", fill="#4E5563", font=font)
    draw.text((right - 70, bottom + 2), f"max {ymax:.3g}", fill="#4E5563", font=font)


def build_interpretable_outputs(input_csv: Path, output_dir: Path, title: str) -> None:
    df_raw = pd.read_csv(input_csv)
    if "t" not in df_raw.columns:
        raise ValueError("Input IRF CSV must contain column 't'.")

    missing = [k for k in SERIES_META if k not in df_raw.columns]
    if missing:
        raise ValueError(f"Input IRF CSV missing required columns: {missing}")

    df = pd.DataFrame({"t": df_raw["t"]})
    for key, (pretty, scale) in SERIES_META.items():
        df[pretty] = df_raw[key] * scale

    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / "irf_monetary_interpretable.csv", index=False)

    horizons = [0, 1, 3, 6, 12, 24, 36]
    horizon_df = df[df["t"].isin(horizons)].copy()
    horizon_df.to_csv(output_dir / "irf_monetary_key_horizons.csv", index=False)

    # Render an easy-to-read dashboard with eight panels.
    width, height = 1300, 900
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    draw.text((20, 14), title, fill="black", font=font)
    draw.text((20, 30), "Units: pct = percent deviations; bps = basis points", fill="#4E5563", font=font)

    variables = list(SERIES_META.values())
    colors = ["#005BBB", "#E66100", "#5D3A9B", "#2A9D8F", "#D62828", "#003049", "#6D6875", "#8AB17D"]
    ncols, nrows = 2, 4
    panel_w = (width - 60) // ncols
    panel_h = (height - 80) // nrows
    idx = 0
    for r in range(nrows):
        for c in range(ncols):
            label = variables[idx][0]
            panel = (
                20 + c * panel_w,
                50 + r * panel_h,
                20 + (c + 1) * panel_w - 10,
                50 + (r + 1) * panel_h - 10,
            )
            _render_line_panel(draw, df, "t", label, label, panel, colors[idx], font)
            idx += 1

    img.save(output_dir / "irf_monetary_interpretable.png")


def main() -> None:
    args = parse_args()
    build_interpretable_outputs(args.input_csv, args.output_dir, args.title)
    print(f"Wrote interpretable IRFs in {args.output_dir}")


if __name__ == "__main__":
    main()

