"""Validity regression tests for htm_classification.py."""

import numpy as np
import pandas as pd
import pytest

from scripts.reporting import htm_classification as htm
from tests.fixtures import (
    build_pof_domicilio,
    build_pof_income_inputs,
    build_pof_morador,
)


def _make_fake_read_dispatch(tables: dict[str, pd.DataFrame]):
    """Return read_pof_table-compatible dispatcher that always returns string columns.

    POF fixed-width readers in production land as strings before numeric coercion, so
    these test fixtures mirror that contract by casting each returned table to str.
    """

    def fake_read(txt_filename, _sheet_name):
        if txt_filename == "INVENTARIO.txt" and txt_filename not in tables:
            return pd.DataFrame(
                columns=["COD_UPA", "NUM_DOM", "NUM_UC", "V9001", "V1404"]
            )
        if txt_filename not in tables:
            expected = ", ".join(sorted(tables))
            raise AssertionError(
                f"unexpected txt filename: {txt_filename}; expected one of: {expected}"
            )
        return tables[txt_filename].astype(str)

    return fake_read


def test_empty_bin_uses_national_prior_not_uniform():
    """Empty bins should shrink to POF national shares, not a uniform prior."""
    pof_national = {"p_ph2m": 0.215, "p_wh2m": 0.193, "p_ric": 0.592}

    p_ph2m, p_wh2m, p_ric = htm._smoothed_shares(
        weighted_ph2m=0.0,
        weighted_wh2m=0.0,
        weighted_ric=0.0,
        total_weight=0.0,
        pof_national=pof_national,
        alpha=htm.ALPHA_SMOOTH,
    )

    assert p_ph2m == pytest.approx(0.215, abs=1e-6)
    assert p_wh2m == pytest.approx(0.193, abs=1e-6)
    assert p_ric == pytest.approx(0.592, abs=1e-6)
    assert p_ph2m + p_wh2m + p_ric == pytest.approx(1.0, abs=1e-9)


def test_smoothed_shares_vectorized_series_preserves_probabilities():
    pof_national = {"p_ph2m": 0.215, "p_wh2m": 0.193, "p_ric": 0.592}

    p_ph2m, p_wh2m, p_ric = htm._smoothed_shares(
        weighted_ph2m=pd.Series([0.0, 20.0], index=["empty", "non_empty"]),
        weighted_wh2m=pd.Series([0.0, 30.0], index=["empty", "non_empty"]),
        weighted_ric=pd.Series([0.0, 50.0], index=["empty", "non_empty"]),
        total_weight=pd.Series([0.0, 100.0], index=["empty", "non_empty"]),
        pof_national=pof_national,
        alpha=htm.ALPHA_SMOOTH,
    )

    row_sums = p_ph2m + p_wh2m + p_ric
    assert row_sums["empty"] == pytest.approx(1.0, abs=1e-9)
    assert row_sums["non_empty"] == pytest.approx(1.0, abs=1e-9)
    assert p_ph2m["empty"] == pytest.approx(pof_national["p_ph2m"], abs=1e-12)
    assert p_wh2m["empty"] == pytest.approx(pof_national["p_wh2m"], abs=1e-12)
    assert p_ric["empty"] == pytest.approx(pof_national["p_ric"], abs=1e-12)


def test_smoothed_shares_rejects_invalid_alpha_or_denominator():
    pof_national = {"p_ph2m": 0.215, "p_wh2m": 0.193, "p_ric": 0.592}

    with pytest.raises(ValueError, match="alpha must be > 0"):
        htm._smoothed_shares(
            weighted_ph2m=0.0,
            weighted_wh2m=0.0,
            weighted_ric=0.0,
            total_weight=0.0,
            pof_national=pof_national,
            alpha=0.0,
        )

    with pytest.raises(ValueError, match="total_weight \\+ alpha must be > 0"):
        htm._smoothed_shares(
            weighted_ph2m=0.0,
            weighted_wh2m=0.0,
            weighted_ric=0.0,
            total_weight=-0.2,
            pof_national=pof_national,
            alpha=0.1,
        )


def test_inactive_zero_income_with_rent_is_not_classified_wh2m():
    """A rent-backed illiquid case with nonpositive income must be excluded."""
    row = pd.Series(
        {
            "liquid_ratio": 0.0,
            "illiquid_assets": 12_000.0,
            "illiquid_ratio": float("nan"),
            "monthly_income": 0.0,
            "is_poor": True,
        }
    )
    assert htm._classify_with_exclusion(row) == "inactive_excluded"


def test_classify_with_exclusion_routes_positive_income_normally():
    row = pd.Series(
        {
            "liquid_ratio": 0.1,
            "illiquid_ratio": 5.0,
            "monthly_income": 1500.0,
            "is_poor": False,
        }
    )
    assert htm._classify_with_exclusion(row) == "WH2M"


def test_classify_with_exclusion_excludes_invalid_liquid_ratio():
    row = pd.Series(
        {
            "liquid_ratio": float("nan"),
            "illiquid_ratio": 1.0,
            "monthly_income": 1200.0,
            "is_poor": False,
        }
    )
    assert htm._classify_with_exclusion(row) == "inactive_excluded"


def test_build_pof_bin_shares_excludes_invalid_rows_before_probabilities(monkeypatch, tmp_path):
    n_households = 6
    dom = build_pof_domicilio(n_households=n_households, uf=35)
    dom["PESO_FINAL"] = 1.0

    mor = build_pof_morador(n_households=n_households, members_per_hh=2)[
        ["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE", "V0306", "NIVEL_INSTRUCAO"]
    ].copy()
    mor["V0403"] = 40 + (mor["COD_UPA"] - 1000)
    mor["V0404"] = 1
    renda_total_map = {
        1000: 0.0,
        1001: 36_000.0,
        1002: 48_000.0,
        1003: 60_000.0,
        1004: 72_000.0,
        1005: 84_000.0,
    }
    mor["RENDA_TOTAL"] = mor["COD_UPA"].map(renda_total_map)

    inc_base = build_pof_income_inputs(
        n_households=n_households,
        labor_income_per_head=3000.0,
        pension_per_head=0.0,
        financial_income_per_head=0.0,
        transfers_per_head=0.0,
        estimated_rent=500.0,
    )
    inc = pd.concat(
        [inc_base["inc"], inc_base["inc"].assign(COD_INFORMANTE=2)], ignore_index=True
    ).rename(columns={"total_labor_income": "V8500_DEFLA"})
    inc.loc[inc["COD_UPA"] == 1000, "V8500_DEFLA"] = 0.0
    inc.loc[inc["COD_UPA"] == 1001, "V8500_DEFLA"] = 3000.0
    inc.loc[inc["COD_UPA"] == 1002, "V8500_DEFLA"] = 4000.0
    inc.loc[inc["COD_UPA"] == 1003, "V8500_DEFLA"] = 5000.0
    inc.loc[inc["COD_UPA"] == 1004, "V8500_DEFLA"] = 6000.0
    inc.loc[inc["COD_UPA"] == 1005, "V8500_DEFLA"] = 7000.0
    inc["V8500_DEFLA"] = inc["V8500_DEFLA"] + inc["COD_INFORMANTE"] * 10.0
    inc.loc[inc["COD_UPA"] == 1000, "V8500_DEFLA"] = 0.0

    oth = pd.DataFrame(
        [
            {"COD_UPA": 1000 + i, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "QUADRO": 57, "V9001": 0, "V8500_DEFLA": 0.0}
            for i in range(0, 6)
        ]
    )
    alug = inc_base["alug"].rename(columns={"estimated_rent": "V8000_DEFLA"})
    alug.loc[alug["COD_UPA"] == 1000, "V8000_DEFLA"] = 1000.0
    alug.loc[alug["COD_UPA"] != 1000, "V8000_DEFLA"] = 500.0

    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor,
                "RENDIMENTO_TRABALHO.txt": inc,
                "OUTROS_RENDIMENTOS.txt": oth,
                "ALUGUEL_ESTIMADO.txt": alug,
            }
        ),
    )
    monkeypatch.setattr(htm, "DIAGNOSTICS_DIR", tmp_path / "diag")
    monkeypatch.setattr(htm, "TABLES_DIR", tmp_path / "tables")

    bin_shares, _edges, pof_national = htm.build_pof_bin_shares(tmp_path / "tables")

    assert (tmp_path / "diag" / "pof_zero_income_excluded.csv").exists()
    assert pof_national["p_ph2m"] + pof_national["p_wh2m"] + pof_national["p_ric"] == pytest.approx(1.0, abs=1e-9)
    assert bin_shares["weighted_n"].sum() == pytest.approx(5.0, abs=1e-9)


def _run_pof_classification_from_fixtures(monkeypatch, tmp_path):
    """Run build_pof_bin_shares from synthetic fixtures with heterogeneous types."""
    n_households = 200
    mor = build_pof_morador(n_households=n_households, members_per_hh=2)
    dom = build_pof_domicilio(n_households=n_households, uf=35)
    income_head = build_pof_income_inputs(
        n_households=n_households,
        labor_income_per_head=3000.0,
        pension_per_head=0.0,
        financial_income_per_head=0.0,
        transfers_per_head=0.0,
        estimated_rent=200.0,
    )
    income = {
        "inc": pd.concat(
            [
                income_head["inc"],
                income_head["inc"].assign(COD_INFORMANTE=2),
            ],
            ignore_index=True,
        ),
        "trans": pd.concat(
            [
                income_head["trans"],
                income_head["trans"].assign(COD_INFORMANTE=2),
            ],
            ignore_index=True,
        ),
        "alug": income_head["alug"].copy(),
    }

    # 1000-1039 -> PH2M, 1040-1069 -> WH2M, 1070-1199 -> Ricardian.
    ph2m_mask = income["inc"]["COD_UPA"] <= 1039
    wh2m_mask = (income["inc"]["COD_UPA"] >= 1040) & (income["inc"]["COD_UPA"] <= 1069)
    ric_mask = income["inc"]["COD_UPA"] >= 1070

    inc_u = income["inc"]["COD_UPA"] - 1000
    income["inc"].loc[ph2m_mask, "total_labor_income"] = 2800.0 + (inc_u[ph2m_mask] % 40)
    income["inc"].loc[wh2m_mask, "total_labor_income"] = 900.0 + (inc_u[wh2m_mask] % 30)
    income["inc"].loc[ric_mask, "total_labor_income"] = 2800.0 + (inc_u[ric_mask] % 130)

    income["trans"]["pension_income"] = 0.0
    income["trans"]["govt_transfers"] = 0.0
    income["trans"]["other_labor_inc"] = 0.0
    income["trans"]["financial_income"] = 0.0
    income["trans"].loc[ric_mask, "financial_income"] = 1100.0 + (inc_u[ric_mask] % 130)
    income["trans"]["total_transfers"] = income["trans"]["financial_income"]

    income["alug"]["estimated_rent"] = 200.0
    income["alug"].loc[wh2m_mask, "estimated_rent"] = 500.0
    income["alug"]["real_estate_annual"] = income["alug"]["estimated_rent"] * 12.0

    person_monthly = income["inc"][
        ["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE", "total_labor_income"]
    ].merge(
        income["trans"][
            ["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE", "total_transfers"]
        ],
        on=["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE"],
        how="left",
    )
    person_monthly["RENDA_TOTAL"] = (
        person_monthly["total_labor_income"] + person_monthly["total_transfers"]
    ) * 12.0
    mor = mor.merge(
        person_monthly[["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE", "RENDA_TOTAL"]],
        on=["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE"],
        how="left",
        suffixes=("", "_person"),
    )
    mor["RENDA_TOTAL"] = mor["RENDA_TOTAL_person"]
    mor = mor.drop(columns=["RENDA_TOTAL_person"])

    trans = income["trans"]
    frames = []
    for quadro, col in [
        (55, "pension_income"),
        (56, "govt_transfers"),
        (57, "financial_income"),
        (54, "other_labor_inc"),
    ]:
        part = trans[["COD_UPA", "NUM_DOM", "NUM_UC", "COD_INFORMANTE", col]].copy()
        part["QUADRO"] = quadro
        part["V9001"] = 0
        part["V8500_DEFLA"] = part[col]
        frames.append(
            part[
                [
                    "COD_UPA",
                    "NUM_DOM",
                    "NUM_UC",
                    "COD_INFORMANTE",
                    "QUADRO",
                    "V9001",
                    "V8500_DEFLA",
                ]
            ]
        )
    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor.rename(columns={"age": "V0403", "sex": "V0404"}),
                "RENDIMENTO_TRABALHO.txt": income["inc"].rename(
                    columns={"total_labor_income": "V8500_DEFLA"}
                ),
                "OUTROS_RENDIMENTOS.txt": pd.concat(frames, ignore_index=True),
                "ALUGUEL_ESTIMADO.txt": income["alug"].rename(
                    columns={"estimated_rent": "V8000_DEFLA"}
                ),
            }
        ),
    )
    monkeypatch.setattr(htm, "TABLES_DIR", tmp_path / "tables")
    monkeypatch.setattr(htm, "DIAGNOSTICS_DIR", tmp_path / "diag")
    bin_shares, _edges, pof_national = htm.build_pof_bin_shares(tmp_path / "tables")
    return bin_shares, pof_national


def test_pof_national_shares_within_literature_range(monkeypatch, tmp_path):
    _bins, nat = _run_pof_classification_from_fixtures(monkeypatch, tmp_path)
    assert nat["p_ph2m"] + nat["p_wh2m"] + nat["p_ric"] == pytest.approx(1.0, abs=1e-12)
    assert 0.15 <= nat["p_ph2m"] <= 0.30, f"PH2M={nat['p_ph2m']:.3f} outside [0.15, 0.30]"
    assert 0.10 <= nat["p_wh2m"] <= 0.25, f"WH2M={nat['p_wh2m']:.3f} outside [0.10, 0.25]"
    assert 0.50 <= nat["p_ric"] <= 0.75, f"Ric={nat['p_ric']:.3f} outside [0.50, 0.75]"
    assert nat["p_ph2m"] == pytest.approx(0.20, abs=1e-9)
    assert nat["p_wh2m"] == pytest.approx(0.15, abs=1e-9)
    assert nat["p_ric"] == pytest.approx(0.65, abs=1e-9)


def test_classification_unit_is_household_head(monkeypatch, tmp_path):
    """bin_shares should count households, not adult persons."""
    bins, _nat = _run_pof_classification_from_fixtures(monkeypatch, tmp_path)
    assert bins["raw_n"].sum() <= 200, (
        f"bin_shares totals {int(bins['raw_n'].sum())} > 200 households "
        "(person-level inflation regressed)"
    )


def test_per_capita_income_uses_all_residents_not_only_adults(monkeypatch, tmp_path):
    """pc_income should divide by all residents, including children."""
    mor = build_pof_morador(
        n_households=1, members_per_hh=4, head_age=40, adult_age=35, child_age=8
    )
    dom = build_pof_domicilio(n_households=1)
    income = build_pof_income_inputs(
        n_households=1, labor_income_per_head=3000.0, estimated_rent=0.0
    )

    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor.rename(columns={"age": "V0403", "sex": "V0404"}),
                "RENDIMENTO_TRABALHO.txt": income["inc"].rename(
                    columns={"total_labor_income": "V8500_DEFLA"}
                ),
                "OUTROS_RENDIMENTOS.txt": income["trans"].assign(
                    QUADRO=55, V9001=0, V8500_DEFLA=0.0
                )[
                    [
                        "COD_UPA",
                        "NUM_DOM",
                        "NUM_UC",
                        "COD_INFORMANTE",
                        "QUADRO",
                        "V9001",
                        "V8500_DEFLA",
                    ]
                ],
                "ALUGUEL_ESTIMADO.txt": income["alug"].assign(V8000_DEFLA=0.0),
            }
        ),
    )
    monkeypatch.setattr(htm, "TABLES_DIR", tmp_path / "t")
    monkeypatch.setattr(htm, "DIAGNOSTICS_DIR", tmp_path / "d")

    hh_frame = htm.build_pof_household_frame()
    assert hh_frame["pc_income"].iloc[0] == pytest.approx(3000.0 / 4.0)


def test_duplicate_head_household_is_deduplicated_deterministically(monkeypatch):
    mor = pd.DataFrame(
        [
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V0306": 1, "V0403": 40, "V0404": 1, "NIVEL_INSTRUCAO": 5, "RENDA_TOTAL": 24000.0},
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 2, "V0306": 1, "V0403": 41, "V0404": 2, "NIVEL_INSTRUCAO": 4, "RENDA_TOTAL": 24000.0},
        ]
    )
    dom = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "UF": 35, "PESO_FINAL": 1.0}])
    inc = pd.DataFrame(
        [
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V8500_DEFLA": 2000.0, "V5302": 1, "V5303": 1},
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 2, "V8500_DEFLA": 0.0, "V5302": 0, "V5303": 2},
        ]
    )
    oth = pd.DataFrame(
        [{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "QUADRO": 57, "V8500_DEFLA": 0.0}]
    )
    alug = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V8000_DEFLA": 0.0}])
    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor,
                "RENDIMENTO_TRABALHO.txt": inc,
                "OUTROS_RENDIMENTOS.txt": oth,
                "ALUGUEL_ESTIMADO.txt": alug,
            }
        ),
    )
    hh = htm.build_pof_household_frame()
    assert len(hh) == 1
    assert hh.duplicated(["COD_UPA", "NUM_DOM", "NUM_UC"]).sum() == 0
    assert hh["COD_INFORMANTE"].iloc[0] == 1


def test_missing_head_household_is_dropped(monkeypatch):
    mor = pd.DataFrame(
        [
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V0306": 2, "V0403": 40, "V0404": 1, "NIVEL_INSTRUCAO": 5, "RENDA_TOTAL": 24000.0},
        ]
    )
    dom = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "UF": 35, "PESO_FINAL": 1.0}])
    inc = pd.DataFrame(
        [{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V8500_DEFLA": 2000.0, "V5302": 1, "V5303": 1}]
    )
    oth = pd.DataFrame(
        [{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "QUADRO": 57, "V8500_DEFLA": 0.0}]
    )
    alug = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V8000_DEFLA": 0.0}])
    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor,
                "RENDIMENTO_TRABALHO.txt": inc,
                "OUTROS_RENDIMENTOS.txt": oth,
                "ALUGUEL_ESTIMADO.txt": alug,
            }
        ),
    )
    hh = htm.build_pof_household_frame()
    assert hh.empty


def test_conflicting_member_labor_flags_do_not_override_selected_head(monkeypatch):
    mor = pd.DataFrame(
        [
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V0306": 1, "V0403": 40, "V0404": 1, "NIVEL_INSTRUCAO": 5, "RENDA_TOTAL": 24000.0},
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 2, "V0306": 2, "V0403": 39, "V0404": 2, "NIVEL_INSTRUCAO": 4, "RENDA_TOTAL": 24000.0},
        ]
    )
    dom = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "UF": 35, "PESO_FINAL": 1.0}])
    inc = pd.DataFrame(
        [
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V8500_DEFLA": 2000.0, "V5302": 1, "V5303": 1},
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 2, "V8500_DEFLA": 1000.0, "V5302": 0, "V5303": 2},
        ]
    )
    oth = pd.DataFrame(
        [{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "QUADRO": 57, "V8500_DEFLA": 0.0}]
    )
    alug = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V8000_DEFLA": 0.0}])
    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor,
                "RENDIMENTO_TRABALHO.txt": inc,
                "OUTROS_RENDIMENTOS.txt": oth,
                "ALUGUEL_ESTIMADO.txt": alug,
            }
        ),
    )
    hh = htm.build_pof_household_frame()
    assert hh["COD_INFORMANTE"].iloc[0] == 1
    assert hh["V5302"].iloc[0] == 1
    assert hh["V5303"].iloc[0] == 1


def test_vehicle_valuation_car_8yr_old():
    assert htm._vehicle_value(code="1403001", acquisition_year=2010) == pytest.approx(10800.0)


def test_vehicle_valuation_old_motorcycle_hits_floor():
    assert htm._vehicle_value(code="1403101", acquisition_year=1990) == pytest.approx(1000.0)


def test_non_vehicle_code_returns_zero():
    assert htm._vehicle_value(code="1404001", acquisition_year=2015) == 0.0


def test_numeric_vehicle_code_maps_correctly():
    assert htm._vehicle_value(code=1403001.0, acquisition_year=2010) == pytest.approx(10800.0)


def test_vehicle_quantity_rule_missing_vs_zero():
    assert htm._vehicle_value(code=1403001.0, acquisition_year=2018) * 1.0 == pytest.approx(30000.0)
    assert htm._vehicle_value(code=1403001.0, acquisition_year=2018) * 0.0 == pytest.approx(0.0)


def test_household_frame_vehicle_aggregation_with_numeric_codes_and_quantities(monkeypatch):
    mor = pd.DataFrame(
        [
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V0306": 1, "V0403": 40, "V0404": 1, "NIVEL_INSTRUCAO": 5, "RENDA_TOTAL": 24000.0},
        ]
    )
    dom = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "UF": 35, "PESO_FINAL": 1.0}])
    inc = pd.DataFrame(
        [{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V8500_DEFLA": 2000.0, "V5302": 1, "V5303": 1}]
    )
    oth = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "QUADRO": 57, "V8500_DEFLA": 0.0}])
    alug = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V8000_DEFLA": 0.0}])
    inv = pd.DataFrame(
        [
            # 2 cars from 2010: 2 * 10800
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V9001": 1403001.0, "V1404": 2010.0, "V9005": 2.0},
            # missing qty motorcycle from 1990: 1 * 1000
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V9001": 1403101.0, "V1404": 1990.0, "V9005": None},
            # explicit zero qty should contribute zero
            {"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V9001": 1403001.0, "V1404": 2010.0, "V9005": 0.0},
        ]
    )
    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor,
                "RENDIMENTO_TRABALHO.txt": inc,
                "OUTROS_RENDIMENTOS.txt": oth,
                "ALUGUEL_ESTIMADO.txt": alug,
                "INVENTARIO.txt": inv,
            }
        ),
    )
    monkeypatch.setattr(htm, "USE_VEHICLE_VALUATION", True)
    hh = htm.build_pof_household_frame()
    assert hh["vehicle_value"].iloc[0] == pytest.approx(22600.0)


def test_household_frame_vehicle_valuation_off_zeroes_vehicle_contribution(monkeypatch):
    mor = pd.DataFrame(
        [{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V0306": 1, "V0403": 40, "V0404": 1, "NIVEL_INSTRUCAO": 5, "RENDA_TOTAL": 24000.0}]
    )
    dom = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "UF": 35, "PESO_FINAL": 1.0}])
    inc = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "COD_INFORMANTE": 1, "V8500_DEFLA": 2000.0, "V5302": 1, "V5303": 1}])
    oth = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "QUADRO": 57, "V8500_DEFLA": 0.0}])
    alug = pd.DataFrame([{"COD_UPA": 1000, "NUM_DOM": 1, "NUM_UC": 1, "V8000_DEFLA": 0.0}])
    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor,
                "RENDIMENTO_TRABALHO.txt": inc,
                "OUTROS_RENDIMENTOS.txt": oth,
                "ALUGUEL_ESTIMADO.txt": alug,
            }
        ),
    )
    monkeypatch.setattr(htm, "USE_VEHICLE_VALUATION", False)
    hh = htm.build_pof_household_frame()
    assert hh["vehicle_value"].iloc[0] == pytest.approx(0.0)


def test_main_sets_vehicle_valuation_off_flag(monkeypatch, tmp_path):
    orig_use_vehicle = htm.USE_VEHICLE_VALUATION
    pnad_path = tmp_path / "pnad.parquet"
    pnad_path.write_text("placeholder")

    monkeypatch.setattr(
        htm,
        "parse_args",
        lambda _argv=None: type(
            "Args",
            (),
            {
                "vehicle_valuation": "off",
                "pnad_parquet": pnad_path,
                "batch_size": 1,
                "per_quarter_quintiles": False,
                "no_legacy_quarterly": True,
                "no_choropleth": True,
                "write_selic_sensitivity": False,
            },
        )(),
    )

    def fake_build():
        assert htm.USE_VEHICLE_VALUATION is False
        shares = pd.DataFrame({"bin_key": [], "p_ph2m": [], "p_wh2m": [], "p_ric": [], "weighted_n": [], "raw_n": []})
        return shares, pd.Series([0, 1, 2, 3, 4, 5]).to_numpy(), {"p_ph2m": 0.2, "p_wh2m": 0.2, "p_ric": 0.6}

    monkeypatch.setattr(htm, "build_pof_bin_shares", fake_build)
    monkeypatch.setattr(htm, "process_pnadc_parquet", lambda *a, **k: (pd.DataFrame(columns=htm.FINAL_MONTHLY_COLUMNS), pd.DataFrame(columns=htm.FINAL_MONTHLY_COLUMNS), pd.DataFrame()))
    monkeypatch.setattr(htm, "_write_outputs", lambda *a, **k: {"monthly_expected": tmp_path / "a.parquet", "monthly_mc": tmp_path / "b.parquet", "coverage": tmp_path / "c.csv"})
    monkeypatch.setattr(htm, "_print_validation_summary", lambda *a, **k: None)
    monkeypatch.setattr(htm, "aggregate_monthly_to_legacy_quarterly", lambda _x: pd.DataFrame())
    monkeypatch.setattr(htm, "generate_quarterly_choropleths", lambda *_a, **_k: False)
    assert htm.main([]) == 0
    assert htm.USE_VEHICLE_VALUATION is orig_use_vehicle


def test_selic_sensitivity_emits_expected_grid(monkeypatch, tmp_path):
    orig_selic = htm.SELIC_RATE
    mor = build_pof_morador(n_households=10)
    dom = build_pof_domicilio(n_households=10)
    income = build_pof_income_inputs(n_households=10)
    # Ensure non-degenerate pc_income quintiles.
    income["inc"]["total_labor_income"] = (
        1500.0 + (income["inc"]["COD_UPA"] - 1000) * 150.0
    )

    monkeypatch.setattr(
        htm,
        "read_pof_table",
        _make_fake_read_dispatch(
            {
                "DOMICILIO.txt": dom,
                "MORADOR.txt": mor.rename(columns={"age": "V0403", "sex": "V0404"}),
                "RENDIMENTO_TRABALHO.txt": income["inc"].rename(
                    columns={"total_labor_income": "V8500_DEFLA"}
                ),
                "OUTROS_RENDIMENTOS.txt": income["trans"].assign(
                    QUADRO=55, V9001=0, V8500_DEFLA=0.0
                )[
                    [
                        "COD_UPA",
                        "NUM_DOM",
                        "NUM_UC",
                        "COD_INFORMANTE",
                        "QUADRO",
                        "V9001",
                        "V8500_DEFLA",
                    ]
                ],
                "ALUGUEL_ESTIMADO.txt": income["alug"].assign(V8000_DEFLA=0.0),
                "INVENTARIO.txt": pd.DataFrame(
                    columns=["COD_UPA", "NUM_DOM", "NUM_UC", "V9001", "V9005", "V1404"]
                ),
            }
        ),
    )
    monkeypatch.setattr(htm, "DIAGNOSTICS_DIR", tmp_path / "diag")
    monkeypatch.setattr(htm, "TABLES_DIR", tmp_path / "tab")
    canonical_tables = tmp_path / "tables"
    canonical_tables.mkdir(parents=True, exist_ok=True)
    canonical_stage1 = canonical_tables / "pof_bin_shares.csv"
    canonical_stage1.write_text("do-not-overwrite")
    out_path = htm.write_selic_sensitivity()
    df = pd.read_csv(out_path)
    assert list(df["selic"].round(4)) == [0.065, 0.09, 0.14]
    assert df[["p_ph2m", "p_wh2m", "p_ric"]].notna().all().all()
    assert htm.SELIC_RATE == orig_selic
    assert canonical_stage1.read_text() == "do-not-overwrite"


def test_pnadc_unmatched_share_below_threshold():
    """Synthetic PNADC batch must keep unmatched share below the review gate."""
    bin_shares = pd.DataFrame(
        {
            "bin_key": ["Southeast|35-44|male|secondary|Q3|formal"],
            "p_ph2m": [0.2],
            "p_wh2m": [0.3],
            "p_ric": [0.5],
            "weighted_n": [100.0],
        }
    )
    bin_shares.attrs["pof_national"] = {"p_ph2m": 0.215, "p_wh2m": 0.193, "p_ric": 0.592}
    pof_edges = np.array([0, 500, 1000, 2000, 3000, 5000], dtype=float)
    batch = pd.DataFrame(
        [
            dict(
                UF=35,
                V2009=40,
                V2007=1,
                VD3004=5,
                V2001=1,
                rendimento_habitual_real=1500.0,
                ref_month_yyyymm=201701,
                ref_month_in_year=1,
                weight_monthly=1.0,
                formal=1,
                conta_propria=0,
                informal=0,
                ocupado=1,
                desocupado=0,
                id_rs=f"rs-{i}",
                id_ind=f"ind-{i}",
            )
            for i in range(50)
        ]
    )
    prepared = htm.prepare_pnadc_batch(batch, bin_shares, pof_edges, bin_strategy="A")
    unmatched = prepared["_unmatched_bin"].mean()
    assert unmatched <= 0.45, f"unmatched_share={unmatched:.3f} > 0.45"


def test_monthly_coverage_marks_covid_disruption_months():
    expected = pd.DataFrame(
        {
            "uf_code": [35, 35],
            "year": [2020, 2020],
            "month": [4, 8],
            "ref_month_yyyymm": [202004, 202008],
            "share_PH2M": [0.2, 0.2],
            "share_WH2M": [0.3, 0.3],
            "share_Ricardian": [0.5, 0.5],
            "share_H2M": [0.5, 0.5],
            "total_weight": [10.0, 20.0],
            "n_obs": [1, 2],
            "n_unmatched": [0, 0],
        }
    )
    coverage = htm._build_monthly_coverage(
        expected,
        [{"n_raw": 3, "n_included": 3, "excluded_by_month": pd.DataFrame()}],
    )

    flags = dict(zip(coverage["ref_month_yyyymm"], coverage["covid_q2q3_2020"]))
    assert flags[202004] == 1
    assert flags[202008] == 0


def test_temporal_trend_summary_weighted_by_state_month(tmp_path):
    monthly = pd.DataFrame(
        {
            "year": [2019, 2019],
            "share_PH2M": [0.2, 0.4],
            "share_WH2M": [0.1, 0.3],
            "share_Ricardian": [0.7, 0.3],
            "total_weight": [1.0, 3.0],
        }
    )
    path = htm.write_temporal_trend_summary(monthly, tmp_path)
    out = pd.read_csv(path)

    assert out["national_PH2M"].iloc[0] == pytest.approx(0.35)
    assert out["national_WH2M"].iloc[0] == pytest.approx(0.25)
    assert out["national_H2M"].iloc[0] == pytest.approx(0.60)
