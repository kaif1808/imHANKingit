#!/usr/bin/env python3
"""Compatibility entry point for `scripts.reporting.cumulative_irf_heterogeneity`."""

from scripts.reporting.cumulative_irf_heterogeneity import *  # noqa: F401,F403
from scripts.reporting.cumulative_irf_heterogeneity import main


if __name__ == "__main__":
    raise SystemExit(main())
