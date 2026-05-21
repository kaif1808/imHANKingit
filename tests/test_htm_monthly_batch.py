import numpy as np
import pandas as pd

from scripts.reporting import htm_classification as htm


POF_QUINTILE_EDGES = np.array([0, 500, 1000, 1500, 2000, 3000], dtype=float)


def _bin_shares():
    shares = pd.DataFrame(
        {
            "bin_key": [
                "Southeast|25-34|male|secondary|Q2|formal",
                "Southeast|35-44|female|tertiary|Q4|informal",
            ],
            "p_ph2m": [0.2, 0.5],
            "p_wh2m": [0.3, 0.1],
            "p_ric": [0.5, 0.4],
            "weighted_n": [100.0, 100.0],
        }
    )
    shares.attrs["pof_national"] = {"p_ph2m": 0.25, "p_wh2m": 0.25, "p_ric": 0.50}
    return shares


def _synthetic_pnadc():
    base = {
        "V2007": 1,
        "VD3004": 5,
        "V2001": 1,
        "formal": 1,
        "conta_propria": 0,
        "informal": 0,
        "ocupado": 0,
        "desocupado": 0,
        "fora_forca_trab": 0,
        "V1028": 999_999.0,
        "Habitual": 888_888.0,
        "UPA": "upa-1",
        "V1008": "dom-1",
        "V1014": "visit-1",
        "V2003": "person-1",
        "V2008": 1,
        "V20081": 1,
        "V20082": 1987,
    }
    rows = [
        {
            **base,
            "UF": 35,
            "V2009": 30,
            "rendimento_habitual_real": 750.0,
            "ref_month_yyyymm": 201701,
            "ref_month_in_year": 1,
            "weight_monthly": 1.0,
            "id_rs": "rs-1",
            "id_ind": "ind-1",
        },
        {
            **base,
            "UF": 35,
            "V2009": 30,
            "rendimento_habitual_real": 750.0,
            "ref_month_yyyymm": 201701,
            "ref_month_in_year": 1,
            "weight_monthly": 2.0,
            "id_rs": "rs-2",
            "id_ind": "ind-2",
        },
        {
            **base,
            "UF": 35,
            "V2009": 40,
            "V2007": 2,
            "VD3004": 7,
            "formal": 0,
            "informal": 1,
            "rendimento_habitual_real": 1700.0,
            "ref_month_yyyymm": 201701,
            "ref_month_in_year": 1,
            "weight_monthly": 3.0,
            "id_rs": None,
            "id_ind": "ind-fallback",
        },
        {
            **base,
            "UF": 11,
            "V2009": 70,
            "V2007": 2,
            "VD3004": 1,
            "formal": 0,
            "rendimento_habitual_real": 100.0,
            "ref_month_yyyymm": 201702,
            "ref_month_in_year": 2,
            "weight_monthly": 4.0,
            "id_rs": "rs-unmatched",
            "id_ind": "ind-unmatched",
        },
        {
            **base,
            "UF": 35,
            "V2009": 30,
            "rendimento_habitual_real": 750.0,
            "ref_month_yyyymm": None,
            "ref_month_in_year": None,
            "weight_monthly": 5.0,
            "id_rs": "rs-missing-month",
            "id_ind": "ind-missing-month",
        },
        {
            **base,
            "UF": 35,
            "V2009": 30,
            "rendimento_habitual_real": 750.0,
            "ref_month_yyyymm": 201702,
            "ref_month_in_year": 2,
            "weight_monthly": None,
            "id_rs": "rs-missing-weight",
            "id_ind": "ind-missing-weight",
        },
        {
            **base,
            "UF": 35,
            "V2009": 14,
            "rendimento_habitual_real": 750.0,
            "ref_month_yyyymm": 201702,
            "ref_month_in_year": 2,
            "weight_monthly": 6.0,
            "id_rs": "rs-underage",
            "id_ind": "ind-underage",
        },
    ]
    return pd.DataFrame(rows)


def _finalize_full_memory(df):
    prepared = htm.prepare_pnadc_batch(df, _bin_shares(), POF_QUINTILE_EDGES)
    partials = [
        {
            "expected": htm.aggregate_monthly_expected(prepared),
            "mc": htm.aggregate_monthly_mc(prepared),
            "diagnostics": prepared.attrs["diagnostics"],
        }
    ]
    return htm.finalize_monthly_outputs(partials)


def test_parquet_batch_aggregation_matches_full_memory(tmp_path):
    df = _synthetic_pnadc()
    parquet_path = tmp_path / "pnadc_fixture.parquet"
    df.to_parquet(parquet_path, index=False, row_group_size=2)

    batch_expected, batch_mc, _ = htm.process_pnadc_parquet(
        parquet_path,
        _bin_shares(),
        POF_QUINTILE_EDGES,
        batch_size=2,
        verbose=False,
    )
    full_expected, full_mc, _ = _finalize_full_memory(df)

    pd.testing.assert_frame_equal(batch_expected, full_expected, check_dtype=False)
    pd.testing.assert_frame_equal(batch_mc, full_mc, check_dtype=False)


def test_monthly_expected_uses_weight_monthly_and_shares_sum_to_one(tmp_path):
    parquet_path = tmp_path / "pnadc_fixture.parquet"
    _synthetic_pnadc().to_parquet(parquet_path, index=False, row_group_size=3)

    expected, mc, _ = htm.process_pnadc_parquet(
        parquet_path,
        _bin_shares(),
        POF_QUINTILE_EDGES,
        batch_size=3,
        verbose=False,
    )

    assert np.isclose(expected["total_weight"].sum(), 10.0)
    assert np.allclose(
        expected[["share_PH2M", "share_WH2M", "share_Ricardian"]].sum(axis=1),
        1.0,
    )
    assert np.allclose(
        mc[["share_PH2M", "share_WH2M", "share_Ricardian"]].sum(axis=1),
        1.0,
    )


def test_missing_month_or_monthly_weight_are_excluded_and_counted(tmp_path):
    parquet_path = tmp_path / "pnadc_fixture.parquet"
    _synthetic_pnadc().to_parquet(parquet_path, index=False, row_group_size=2)

    expected, _, coverage = htm.process_pnadc_parquet(
        parquet_path,
        _bin_shares(),
        POF_QUINTILE_EDGES,
        batch_size=2,
        verbose=False,
    )

    assert expected["n_obs"].sum() == 4
    assert coverage["raw_rows_total"].iloc[0] == 7
    assert coverage["included_rows_total"].iloc[0] == 4
    assert coverage["missing_ref_month_total"].iloc[0] == 1
    assert coverage["missing_weight_monthly_total"].iloc[0] == 1
    assert coverage["excluded_monthly_total"].iloc[0] == 2
    assert coverage["under_15_or_missing_age_total"].iloc[0] == 1

    feb = coverage.loc[coverage["ref_month_yyyymm"] == 201702].iloc[0]
    assert feb["excluded_missing_weight"] == 1


def test_deterministic_mc_labels_are_stable_for_same_id_rs_and_seed():
    df = _synthetic_pnadc()
    first = htm.prepare_pnadc_batch(df, _bin_shares(), POF_QUINTILE_EDGES)
    shuffled = htm.prepare_pnadc_batch(
        df.sample(frac=1, random_state=123).reset_index(drop=True),
        _bin_shares(),
        POF_QUINTILE_EDGES,
    )

    first_ids = first["id_rs"].where(first["id_rs"].notna(), first["id_ind"])
    shuffled_ids = shuffled["id_rs"].where(shuffled["id_rs"].notna(), shuffled["id_ind"])
    first_labels = dict(zip(first_ids, first["agent_type"]))
    shuffled_labels = dict(zip(shuffled_ids, shuffled["agent_type"]))

    assert shuffled_labels == first_labels
    assert "ind-fallback" in first_labels


def test_missing_id_rs_and_id_ind_get_stable_field_fallback():
    df = _synthetic_pnadc()
    row = df.iloc[[0]].copy()
    row["id_rs"] = None
    row["id_ind"] = None
    row["UPA"] = "upa-missing-id"
    row["V1008"] = "dom-missing-id"
    row["V1014"] = "visit-missing-id"
    row["V2003"] = "person-missing-id"

    first = htm.prepare_pnadc_batch(row, _bin_shares(), POF_QUINTILE_EDGES)
    second = htm.prepare_pnadc_batch(row, _bin_shares(), POF_QUINTILE_EDGES)

    assert len(first) == 1
    assert first["agent_type"].iloc[0] == second["agent_type"].iloc[0]
