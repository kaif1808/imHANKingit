#!/usr/bin/env python3
"""
Generate per-quarter HTM choropleth maps from state_quarter_htm_shares.csv.

Reads the state × quarter CSV, downloads IBGE state boundaries, and produces
one 4-panel choropleth (PH2M, WH2M, total HtM, Ricardian) per quarter.
"""

import argparse
import io
import ssl
import tempfile
import zipfile
from pathlib import Path
from urllib import request as urllib_request

import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / "results"
TABLES_DIR = RESULTS_DIR / "tables"
PLOTS_DIR = RESULTS_DIR / "plots"
SHP_URL = (
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/"
    "malhas_territoriais/malhas_municipais/municipio_2022/"
    "Brasil/BR/BR_UF_2022.zip"
)

PANELS = [
    ("PH2M", "Poor HtM", "#b2182b", "#fddbc7"),
    ("WH2M", "Wealthy HtM", "#2166ac", "#d1e5f0"),
    ("total_HtM", "Total HtM", "#542788", "#f7f7f7"),
    ("Ricardian", "Ricardian", "#1b7837", "#d9f0d3"),
]

REGION_MAP = {
    "Norte": ["AM", "PA", "AC", "RO", "RR", "AP", "TO"],
    "Nordeste": ["MA", "PI", "CE", "RN", "PB", "PE", "AL", "SE", "BA"],
    "Sudeste": ["MG", "ES", "RJ", "SP"],
    "Sul": ["PR", "SC", "RS"],
    "Centro-Oeste": ["MT", "MS", "GO", "DF"],
}


def load_ibge_shapefile():
    """Download and load IBGE state boundaries."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    shp_dir = Path(tempfile.mkdtemp())
    req = urllib_request.Request(SHP_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib_request.urlopen(req, timeout=120, context=ctx) as r:
        with zipfile.ZipFile(io.BytesIO(r.read())) as z:
            z.extractall(shp_dir)
    brazil = gpd.read_file(next(shp_dir.glob("*.shp"))).to_crs("EPSG:4326")
    brazil["uf_code"] = brazil["CD_UF"].astype(int)
    sigla_to_region = {s: r for r, states in REGION_MAP.items() for s in states}
    brazil["macro_region"] = brazil["SIGLA_UF"].map(sigla_to_region)
    regions_gdf = brazil.dissolve(by="macro_region").reset_index()
    return brazil, regions_gdf


def compute_global_vmin_vmax(state_qtr_valid):
    """Compute vmin/vmax per variable across all quarters for consistent color scaling."""
    df = state_qtr_valid.copy()
    df["total_HtM"] = df["share_PH2M"] + df["share_WH2M"]
    df["PH2M"] = df["share_PH2M"]
    df["WH2M"] = df["share_WH2M"]
    df["Ricardian"] = df["share_Ricardian"]
    ranges = {}
    for col, _, _, _ in PANELS:
        vals = df[col].dropna()
        ranges[col] = (
            vals.quantile(0.05) if len(vals) > 0 else 0,
            vals.quantile(0.95) if len(vals) > 0 else 1,
        )
    return ranges


def plot_choropleth(gdf, regions_gdf, grp, yr, qtr, out_path, vmin_vmax):
    """Create and save 4-panel choropleth for one quarter."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 14))
    fig.patch.set_facecolor("#F7F4EF")
    axes = axes.flatten()

    for ax, (col, title, dark, light) in zip(axes, PANELS):
        ax.set_facecolor("#cce5f0")
        vmin, vmax = vmin_vmax.get(col, (0, 1))
        cmap = mcolors.LinearSegmentedColormap.from_list(col, [light, dark], N=256)
        gdf.plot(
            column=col,
            ax=ax,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            linewidth=0.35,
            edgecolor="white",
            missing_kwds={"color": "#cccccc"},
        )
        regions_gdf.plot(ax=ax, facecolor="none", edgecolor="#222222", linewidth=1.6)
        for _, row in gdf.iterrows():
            pt = row.geometry.representative_point()
            if pd.notna(row[col]):
                ax.annotate(
                    row["SIGLA_UF"],
                    xy=(pt.x, pt.y),
                    ha="center",
                    va="center",
                    fontsize=5.2,
                    color="white",
                    fontweight="bold",
                    path_effects=[pe.withStroke(linewidth=1.2, foreground="#00000055")],
                )
        for _, rrow in regions_gdf.iterrows():
            rpt = rrow.geometry.centroid
            ax.annotate(
                rrow["macro_region"],
                xy=(rpt.x, rpt.y),
                ha="center",
                va="center",
                fontsize=7,
                color="#111111",
                fontstyle="italic",
                fontweight="bold",
                alpha=0.55,
            )
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=mcolors.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, fraction=0.028, pad=0.02, shrink=0.72)
        cbar.ax.yaxis.set_tick_params(labelsize=8, color="0.4")
        cbar.set_label("Share", fontsize=8, color="0.4")
        cbar.ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
        if len(gdf[gdf[col].notna()]) > 0:
            lo_row = gdf.loc[gdf[col].idxmin()]
            hi_row = gdf.loc[gdf[col].idxmax()]
            ax.set_title(
                f"{title} share\n↑ {hi_row['SIGLA_UF']} {hi_row[col]:.1%}   "
                f"↓ {lo_row['SIGLA_UF']} {lo_row[col]:.1%}",
                fontsize=11,
                pad=8,
                color="#111111",
            )
        else:
            ax.set_title(f"{title} share", fontsize=11, pad=8, color="#111111")
        ax.axis("off")

    wt = gdf["uf_code"].map(grp.set_index("uf_code")["total_weight"]).fillna(1)

    def wnat(c):
        return np.average(gdf[c].fillna(0), weights=wt)

    fig.suptitle(
        f"HTM Agent-Type Shares by Brazilian State  (PNADC {yr} Q{qtr})\n"
        f"Population-weighted national:  PH2M {wnat('PH2M'):.1%}  │  "
        f"WH2M {wnat('WH2M'):.1%}  │  Total HtM {wnat('total_HtM'):.1%}  │  "
        f"Ricardian {wnat('Ricardian'):.1%}\n"
        "Bold borders = macro-region boundaries",
        fontsize=11,
        y=1.005,
        color="#111111",
        linespacing=1.7,
    )
    plt.tight_layout(h_pad=3, w_pad=2)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Generate per-quarter HTM choropleth maps from state_quarter_htm_shares.csv"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=TABLES_DIR / "state_quarter_htm_shares.csv",
        help="Path to state_quarter_htm_shares.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PLOTS_DIR,
        help="Directory for output PNG files",
    )
    args = parser.parse_args()

    state_qtr = pd.read_csv(args.input)
    state_qtr_valid = state_qtr.dropna(subset=["year", "quarter"])

    if state_qtr_valid.empty:
        print("No valid year/quarter data in CSV.")
        return 1

    print("Downloading IBGE state boundaries...")
    try:
        brazil, regions_gdf = load_ibge_shapefile()
    except Exception as e:
        print(f"Could not download IBGE shapefile: {e}")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    vmin_vmax = compute_global_vmin_vmax(state_qtr_valid)

    for (yr, qtr), grp in state_qtr_valid.groupby(["year", "quarter"]):
        yr, qtr = int(yr), int(qtr)
        htm_q = grp.assign(uf_code=lambda d: d["uf_code"].astype(int)).copy()
        htm_q["PH2M"] = htm_q["share_PH2M"]
        htm_q["WH2M"] = htm_q["share_WH2M"]
        htm_q["Ricardian"] = htm_q["share_Ricardian"]
        htm_q["total_HtM"] = htm_q["PH2M"] + htm_q["WH2M"]
        gdf = brazil.merge(
            htm_q[["uf_code", "PH2M", "WH2M", "Ricardian", "total_HtM", "total_weight"]],
            on="uf_code",
            how="left",
        )
        out_png = out_dir / f"choropleth_htm_{yr}Q{qtr}.png"
        plot_choropleth(gdf, regions_gdf, grp, yr, qtr, out_png, vmin_vmax)
        print(f"  Saved {out_png.name}")

    print(f"\nDone. Choropleths saved to {out_dir}")
    return 0


if __name__ == "__main__":
    exit(main())
