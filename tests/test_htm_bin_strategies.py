import numpy as np
import pandas as pd
import pytest

from scripts.reporting import htm_classification as htm


def test_labor_status_3way_collapses_self_employed_to_employed():
    df = pd.DataFrame(
        {
            "formal": [1, 0, 0, 0, 0],
            "conta_propria": [0, 1, 0, 0, 0],
            "informal": [0, 0, 1, 0, 0],
            "desocupado": [0, 0, 0, 1, 0],
        }
    )
    out = htm._labor_status_3way(df).tolist()
    assert out == ["employed", "employed", "employed", "unemployed", "inactive"]


def test_income_band_absolute_partitions_at_documented_cutpoints():
    income = pd.Series([100.0, 170.0, 500.0, 700.0, 1500.0, 2000.0, 3500.0, 4000.0, 10000.0])
    bands = htm._income_band_absolute(income).tolist()
    assert bands == ["B1", "B1", "B2", "B2", "B3", "B3", "B4", "B4", "B5"]


def test_build_bin_key_strategy_g_uses_3way_labour_and_bands():
    df = pd.DataFrame(
        {
            "macro_region": ["South"],
            "age_group": ["35-44"],
            "gender": ["male"],
            "education_group": ["secondary"],
            "labor_status": ["formal"],
            "labor_status_3way": ["employed"],
            "pc_income_quintile": ["Q3"],
            "income_band_absolute": ["B3"],
        }
    )
    key = htm._build_bin_key(df, strategy="G").iloc[0]
    assert key == "South|35-44|male|secondary|B3|employed"


def test_pnadc_strategy_g_matches_absolute_band_bin():
    bin_shares = pd.DataFrame(
        {
            "bin_key": ["Southeast|35-44|male|secondary|B3|employed"],
            "p_ph2m": [0.2],
            "p_wh2m": [0.3],
            "p_ric": [0.5],
            "weighted_n": [100.0],
        }
    )
    bin_shares.attrs["pof_national"] = {"p_ph2m": 0.25, "p_wh2m": 0.25, "p_ric": 0.50}
    batch = pd.DataFrame(
        [
            {
                "UF": 35,
                "V2009": 40,
                "V2007": 1,
                "VD3004": 5,
                "V2001": 1,
                "rendimento_habitual_real": 1500.0,
                "ref_month_yyyymm": 201701,
                "ref_month_in_year": 1,
                "weight_monthly": 1.0,
                "formal": 1,
                "conta_propria": 0,
                "informal": 0,
                "ocupado": 1,
                "desocupado": 0,
                "id_rs": "rs-1",
                "id_ind": "ind-1",
            }
        ]
    )

    prepared = htm.prepare_pnadc_batch(
        batch,
        bin_shares,
        np.array([0, 500, 1000, 2000, 3000, 5000], dtype=float),
        bin_strategy="G",
    )

    assert prepared["_unmatched_bin"].iloc[0] is np.False_
    assert prepared["bin_key"].iloc[0] == "Southeast|35-44|male|secondary|B3|employed"


def test_main_both_uses_canonical_strategy_for_unsuffixed_outputs(monkeypatch, tmp_path):
    pnad_path = tmp_path / "pnad.parquet"
    pnad_path.write_text("placeholder")
    calls = {"write": [], "trend": [], "selic_strategy": []}

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
                "write_selic_sensitivity": True,
                "bin_strategy": "both",
                "canonical_strategy": "A",
                "exclude_covid_disruption": False,
            },
        )(),
    )

    def fake_build():
        shares = pd.DataFrame(
            {
                "bin_key": [f"key-{htm.BIN_STRATEGY}"],
                "p_ph2m": [0.2],
                "p_wh2m": [0.3],
                "p_ric": [0.5],
                "weighted_n": [1.0],
            }
        )
        return shares, np.array([0, 1, 2, 3, 4, 5], dtype=float), {
            "p_ph2m": 0.2,
            "p_wh2m": 0.3,
            "p_ric": 0.5,
        }

    def fake_process(*_args, **_kwargs):
        expected = pd.DataFrame(
            {
                "uf_code": [35],
                "year": [2020],
                "month": [1],
                "ref_month_yyyymm": [202001],
                "share_PH2M": [0.2],
                "share_WH2M": [0.3],
                "share_Ricardian": [0.5],
                "share_H2M": [0.5],
                "total_weight": [1.0],
                "n_obs": [1],
                "n_unmatched": [0],
                "strategy_marker": [htm.BIN_STRATEGY],
            }
        )
        coverage = pd.DataFrame({"unmatched_share": [0.0]})
        return expected, expected.copy(), coverage

    def fake_write(expected, *_args, suffix="", **_kwargs):
        calls["write"].append((suffix, expected["strategy_marker"].iloc[0]))
        return {
            "monthly_expected": tmp_path / f"state_month_htm_shares{suffix}.parquet",
            "monthly_mc": tmp_path / f"state_month_htm_shares_mc{suffix}.parquet",
            "coverage": tmp_path / f"monthly_htm_coverage{suffix}.csv",
        }

    def fake_trend(expected, *_args, suffix="", **_kwargs):
        calls["trend"].append((suffix, expected["strategy_marker"].iloc[0]))
        return tmp_path / f"national_htm_trend_yearly{suffix}.csv"

    def fake_selic(*_args, **_kwargs):
        calls["selic_strategy"].append(htm.BIN_STRATEGY)
        return tmp_path / "selic_sensitivity.csv"

    monkeypatch.setattr(htm, "build_pof_bin_shares", fake_build)
    monkeypatch.setattr(htm, "process_pnadc_parquet", fake_process)
    monkeypatch.setattr(htm, "_write_outputs", fake_write)
    monkeypatch.setattr(htm, "write_temporal_trend_summary", fake_trend)
    monkeypatch.setattr(htm, "write_selic_sensitivity", fake_selic)
    monkeypatch.setattr(htm, "_print_validation_summary", lambda *a, **k: None)

    assert htm.main([]) == 0

    assert ("", "A") in calls["write"]
    assert ("_A", "A") in calls["write"]
    assert ("_G", "G") in calls["write"]
    assert ("", "A") in calls["trend"]
    assert calls["selic_strategy"] == ["A"]


def test_root_htm_wrapper_aliases_implementation_globals():
    import htm_classification as root_htm

    old = htm.BIN_STRATEGY
    try:
        root_htm.BIN_STRATEGY = "G"
        assert htm.BIN_STRATEGY == "G"
    finally:
        root_htm.BIN_STRATEGY = old
