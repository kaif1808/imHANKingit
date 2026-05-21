#!/usr/bin/env python3
"""Compatibility entry point for `scripts.reporting.htm_classification`."""

import sys

from scripts.reporting import htm_classification as _impl


if __name__ == "__main__":
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
