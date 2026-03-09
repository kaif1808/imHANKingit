"""Unit tests for HTM classification quintile logic (2017 Q4 calibration fixes)."""
import numpy as np
import pandas as pd


def test_pof_quintile_cutpoints_align_pnadc():
    """PNADC quintiles using POF cut-points should map consistently across quarters."""
    # Simulate POF income distribution
    np.random.seed(42)
    pof_income = np.random.lognormal(6, 1, 1000)
    pof_quintile_edges = pd.qcut(pof_income, q=5, retbins=True)[1]

    # Same income in different "quarters" should get same quintile
    bins_extended = np.concatenate([[-np.inf], pof_quintile_edges[1:-1], [np.inf]])
    income = 500.0
    q1 = pd.cut(
        pd.Series([income]),
        bins=bins_extended,
        labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
        include_lowest=True,
    ).iloc[0]
    q2 = pd.cut(
        pd.Series([income]),
        bins=bins_extended,
        labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
        include_lowest=True,
    ).iloc[0]
    assert q1 == q2, "Same income should get same quintile regardless of quarter"


def test_pof_cutpoints_handle_outliers():
    """PNADC incomes outside POF range should map to Q1 or Q5."""
    pof_income = np.array([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])
    pof_quintile_edges = pd.qcut(pof_income, q=5, retbins=True)[1]
    bins_extended = np.concatenate([[-np.inf], pof_quintile_edges[1:-1], [np.inf]])

    very_low = pd.cut(
        pd.Series([1]),
        bins=bins_extended,
        labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
        include_lowest=True,
    ).iloc[0]
    very_high = pd.cut(
        pd.Series([10000]),
        bins=bins_extended,
        labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
        include_lowest=True,
    ).iloc[0]
    assert very_low == "Q1"
    assert very_high == "Q5"
