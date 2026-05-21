"""Synthetic POF and PNADC fixture builders for htm_classification tests."""
from __future__ import annotations

import pandas as pd


MORADOR_COLUMNS = [
    "COD_UPA",
    "NUM_DOM",
    "NUM_UC",
    "COD_INFORMANTE",
    "V0306",
    "age",
    "sex",
    "NIVEL_INSTRUCAO",
    "RENDA_TOTAL",
]
DOMICILIO_COLUMNS = ["COD_UPA", "NUM_DOM", "UF", "PESO_FINAL"]
INC_COLUMNS = [
    "COD_UPA",
    "NUM_DOM",
    "NUM_UC",
    "COD_INFORMANTE",
    "total_labor_income",
    "V5302",
    "V5303",
]
TRANS_COLUMNS = [
    "COD_UPA",
    "NUM_DOM",
    "NUM_UC",
    "COD_INFORMANTE",
    "pension_income",
    "govt_transfers",
    "financial_income",
    "other_labor_inc",
    "total_transfers",
]
ALUG_COLUMNS = [
    "COD_UPA",
    "NUM_DOM",
    "NUM_UC",
    "estimated_rent",
    "real_estate_annual",
]


def build_pof_morador(
    n_households: int = 4,
    members_per_hh: int = 3,
    head_age: int = 40,
    child_age: int = 10,
    adult_age: int = 35,
) -> pd.DataFrame:
    """Return a synthetic MORADOR-shaped DataFrame.

    Each household has one reference person (V0306 == 1), one adult spouse
    (V0306 == 2), and (members_per_hh - 2) children (V0306 == 3, age below 15).
    """
    if members_per_hh < 2:
        raise ValueError("members_per_hh must be >= 2")

    rows = []
    for hh in range(n_households):
        rows.append(dict(
            COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=1,
            V0306=1, age=head_age, sex=1, NIVEL_INSTRUCAO=5, RENDA_TOTAL=3000.0,
        ))
        rows.append(dict(
            COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=2,
            V0306=2, age=adult_age, sex=2, NIVEL_INSTRUCAO=5, RENDA_TOTAL=3000.0,
        ))
        for j in range(members_per_hh - 2):
            rows.append(dict(
                COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=3 + j,
                V0306=3, age=child_age, sex=1, NIVEL_INSTRUCAO=1, RENDA_TOTAL=3000.0,
            ))
    return pd.DataFrame(rows, columns=MORADOR_COLUMNS)


def build_pof_domicilio(n_households: int = 4, uf: int = 35) -> pd.DataFrame:
    """Return a synthetic DOMICILIO-shaped DataFrame."""
    return pd.DataFrame([
        dict(COD_UPA=1000 + hh, NUM_DOM=1, UF=uf, PESO_FINAL=100.0)
        for hh in range(n_households)
    ], columns=DOMICILIO_COLUMNS)


def build_pof_income_inputs(
    n_households: int = 4,
    labor_income_per_head: float = 2500.0,
    pension_per_head: float = 0.0,
    financial_income_per_head: float = 0.0,
    transfers_per_head: float = 0.0,
    estimated_rent: float = 800.0,
) -> dict[str, pd.DataFrame]:
    """Return dict with keys `inc`, `trans`, `alug` for household/person inputs.

    Each frame includes household/person key columns (`COD_UPA`, `NUM_DOM`,
    `NUM_UC`; plus `COD_INFORMANTE` where person-level) alongside income fields.
    """
    inc = pd.DataFrame([
        dict(COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=1,
             total_labor_income=labor_income_per_head, V5302=1, V5303=1)
        for hh in range(n_households)
    ], columns=INC_COLUMNS)
    trans = pd.DataFrame([
        dict(COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=1,
             pension_income=pension_per_head, govt_transfers=transfers_per_head,
             financial_income=financial_income_per_head, other_labor_inc=0.0,
             total_transfers=pension_per_head + transfers_per_head
                              + financial_income_per_head)
        for hh in range(n_households)
    ], columns=TRANS_COLUMNS)
    alug = pd.DataFrame([
        dict(COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1,
             estimated_rent=estimated_rent, real_estate_annual=estimated_rent * 12)
        for hh in range(n_households)
    ], columns=ALUG_COLUMNS)
    return {"inc": inc, "trans": trans, "alug": alug}
