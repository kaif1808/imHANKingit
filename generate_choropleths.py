#!/usr/bin/env python3
"""Compatibility entry point for `scripts.reporting.generate_choropleths`."""

from scripts.reporting.generate_choropleths import *  # noqa: F401,F403
from scripts.reporting.generate_choropleths import main


if __name__ == "__main__":
    raise SystemExit(main())
