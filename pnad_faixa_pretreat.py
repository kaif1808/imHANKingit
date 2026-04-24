"""
Map DataZoom-style `faixa_idade` and `faixa_educ` strings to numeric age and IBGE
VD3004–compatible codes for the PNAD-C pretreated branch in `htm_classification.py`.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd


def _strip_accents(s: str) -> str:
    t = unicodedata.normalize("NFKD", s)
    return "".join(c for c in t if not unicodedata.combining(c))


# Midpoints / representative ages (years) for age-group binning; must align
# with `age_to_group` cut points (15+ kept by pipeline).
_FAIXA_IDADE_AGE: dict[str, float] = {
    "menor de 14": 10.0,
    "menor de 14 anos": 10.0,
    "ate 14 anos": 10.0,
    "entre 14 e 17 anos": 16.0,
    "entre 18 e 24 anos": 21.0,
    "entre 25 e 29 anos": 27.0,
    "entre 30 e 39 anos": 35.0,
    "entre 40 e 49 anos": 45.0,
    "entre 50 e 59 anos": 55.0,
    "60 anos ou mais": 65.0,
    "de 60 anos ou mais": 65.0,
    "de 60 anos": 65.0,
    "60 ou mais": 65.0,
}


def _faixa_idade_to_age_one(label: object) -> float:
    if label is None or (isinstance(label, float) and np.isnan(label)):
        return np.nan
    raw = str(label).strip()
    if not raw:
        return np.nan
    key = _strip_accents(raw).lower()
    if key in _FAIXA_IDADE_AGE:
        return _FAIXA_IDADE_AGE[key]
    # e.g. "15 e 19" — take midpoint if two integers present
    nums = re.findall(r"\b(\d{1,2})\b", key)
    if len(nums) >= 2:
        a, b = int(nums[0]), int(nums[1])
        if a < b:
            return float((a + b) / 2.0)
    if key.isdigit():
        v = int(key)
        if 0 <= v <= 120:
            return float(v)
    return np.nan


def faixa_idade_to_age(serie: pd.Series) -> pd.Series:
    """Map DataZoom `faixa_idade` labels to a numeric `age` for binning (series)."""
    return serie.map(_faixa_idade_to_age_one).astype(float)


def _faixa_educ_to_vd3004_one(label: object) -> float:
    """Map a single `faixa_educ` string to 1..7 (VD3004)."""
    if label is None or (isinstance(label, float) and np.isnan(label)):
        return np.nan
    t = _strip_accents(str(label).strip().lower().replace("£", ""))
    if not t:
        return np.nan
    # Sem instrução / muito curto
    if "sem inst" in t or "analfab" in t or t.startswith("0 "):
        return 1.0
    if "muito curto" in t or "menos de 1" in t:
        return 1.0
    if "1 a 7" in t or re.search(r"\b1?\s*-\s*7\b", t):
        return 2.0
    if "8 a 9" in t or re.search(r"\b8+\s*-\s*9\b", t) or re.search(
        r"fundamental\s+compl", t
    ):
        return 3.0
    if "9 a 11" in t or re.search(
        r"medio\s*in", t
    ) or re.search(r"médio\s*in", t):
        return 4.0
    if "9 a 14" in t or re.search(
        r"12?\s*-\s*1[34]", t
    ) or re.search(r"medio\s*compl", t) or re.search(
        r"12.*14", t
    ):
        if "incom" in t:
            return 4.0
        return 5.0
    if "11 a 14" in t:
        if "incom" in t:
            return 4.0
        return 5.0
    if re.search(
        r"1[35].*ou mais|superi|técn|universi", t
    ) or "pos grad" in t:
        if "incom" in t:
            return 6.0
        return 7.0
    return np.nan


def faixa_educ_to_vd3004(serie: pd.Series) -> pd.Series:
    return serie.map(_faixa_educ_to_vd3004_one).astype(float)
