#!/usr/bin/env python3
"""Plot SSJ monetary-shock IRFs by agent type."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]
INFILE = ROOT / "results" / "tables" / "hank_ssj_agent_type_irfs.csv"
OUTDIR = ROOT / "results" / "plots"


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(INFILE)

    # Percent IRFs by type
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(df["t"], df["C_PH2M_pct"], label="PH2M", linewidth=2.2)
    ax.plot(df["t"], df["C_WH2M_pct"], label="WH2M", linewidth=2.2)
    ax.plot(df["t"], df["C_RIC_pct"], label="Ricardian", linewidth=2.2)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_xlabel("Months after shock")
    ax.set_ylabel("Consumption IRF (% of type SS consumption)")
    ax.set_title("Monetary Shock IRFs by Agent Type (Percent)")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(OUTDIR / "hank_ssj_agent_type_irfs_pct.png", dpi=180)
    plt.close(fig)

    # Level IRFs by type
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(df["t"], df["C_PH2M"], label="PH2M", linewidth=2.2)
    ax.plot(df["t"], df["C_WH2M"], label="WH2M", linewidth=2.2)
    ax.plot(df["t"], df["C_RIC"], label="Ricardian", linewidth=2.2)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_xlabel("Months after shock")
    ax.set_ylabel("Consumption IRF (level deviation)")
    ax.set_title("Monetary Shock IRFs by Agent Type (Levels)")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(OUTDIR / "hank_ssj_agent_type_irfs_level.png", dpi=180)
    plt.close(fig)

    # Cumulative level IRFs by type
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(df["t"], df["C_PH2M"].cumsum(), label="PH2M", linewidth=2.2)
    ax.plot(df["t"], df["C_WH2M"].cumsum(), label="WH2M", linewidth=2.2)
    ax.plot(df["t"], df["C_RIC"].cumsum(), label="Ricardian", linewidth=2.2)
    ax.axhline(0.0, color="black", linewidth=0.9)
    ax.set_xlabel("Months after shock")
    ax.set_ylabel("Cumulative consumption IRF")
    ax.set_title("Cumulative Monetary Shock IRFs by Agent Type")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(OUTDIR / "hank_ssj_agent_type_irfs_cumulative.png", dpi=180)
    plt.close(fig)

    print("Saved plots:")
    print(OUTDIR / "hank_ssj_agent_type_irfs_pct.png")
    print(OUTDIR / "hank_ssj_agent_type_irfs_level.png")
    print(OUTDIR / "hank_ssj_agent_type_irfs_cumulative.png")


if __name__ == "__main__":
    main()
