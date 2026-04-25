"""Unit tests for DataZoom pretreated `faixa_*` → numeric mappings."""
import numpy as np
import pandas as pd
import pytest

from pnad_faixa_pretreat import (
    _faixa_educ_to_vd3004_one,
    _faixa_idade_to_age_one,
    faixa_educ_to_vd3004,
    faixa_idade_to_age,
)


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Entre 18 e 24 anos", 21.0),
        ("Entre 25 e 29 anos", 27.0),
        ("Entre 50 e 59 anos", 55.0),
        ("60 anos ou mais", 65.0),
    ],
)
def test_faixa_idade_common_bands(label, expected):
    assert _faixa_idade_to_age_one(label) == expected


def test_faixa_idade_series():
    s = pd.Series(
        ["Entre 18 e 24 anos", "60 anos ou mais", None],
    )
    out = faixa_idade_to_age(s)
    assert out.iloc[0] == 21.0
    assert out.iloc[1] == 65.0
    assert np.isnan(out.iloc[2])


@pytest.mark.parametrize(
    "label, expected_vd",
    [
        ("Sem instrução", 1.0),
        ("1 a 7 anos de estudo", 2.0),
        ("9 a 14 anos de estudo", 5.0),
    ],
)
def test_faixa_educ_common_bands(label, expected_vd):
    assert _faixa_educ_to_vd3004_one(label) == expected_vd


def test_faixa_educ_series():
    s = pd.Series(
        [
            "Sem instruç£o",  # mojibake pattern seen in some exports
            "1 a 7 anos de estudo",
        ],
    )
    out = faixa_educ_to_vd3004(s)
    assert out.iloc[0] == 1.0
    assert out.iloc[1] == 2.0
