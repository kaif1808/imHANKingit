import numpy as np
import pandas as pd

from scripts.reporting import basic_state_month_lp as lp


def _write_consumption(path, months, states=(11, 12, 13, 14), missing_last_state=False):
    header = "Sigla;Código;State;" + ";".join(months) + ";"
    rows = ["Synthetic metadata row", header]
    abbrevs = {11: "RO", 12: "AC", 13: "AM", 14: "RR"}
    for state_idx, uf_code in enumerate(states):
        values = []
        for month_idx, period in enumerate(months):
            value = 100 + state_idx * 3 + month_idx * 0.8
            if missing_last_state and uf_code == states[-1] and period == months[-1]:
                values.append("")
            else:
                values.append(f"{value:.2f}".replace(".", ","))
        rows.append(
            f"{abbrevs[uf_code]};{uf_code};State {uf_code};" + ";".join(values) + ";"
        )
    path.write_text("\n".join(rows), encoding="utf-8")


def _synthetic_inputs(tmp_path, n_months=8, n_states=4):
    states = [11, 12, 13, 14][:n_states]
    dates = pd.date_range("2024-01-01", periods=n_months, freq="MS")
    periods = [date.strftime("%Y.%m") for date in dates]

    consumption_path = tmp_path / "consumption.csv"
    _write_consumption(consumption_path, periods, states=states)

    htm_rows = []
    for state_idx, uf_code in enumerate(states):
        for month_idx, date in enumerate(dates):
            ph2m = 0.20 + 0.01 * state_idx + 0.001 * month_idx
            wh2m = 0.30 + 0.005 * state_idx - 0.001 * month_idx
            htm_rows.append(
                {
                    "uf_code": uf_code,
                    "year": date.year,
                    "month": date.month,
                    "share_PH2M": ph2m,
                    "share_WH2M": wh2m,
                    "share_Ricardian": 1 - ph2m - wh2m,
                }
            )
    htm_path = tmp_path / "htm.parquet"
    pd.DataFrame(htm_rows).to_parquet(htm_path, index=False)

    shock_path = tmp_path / "shocks.csv"
    pd.DataFrame(
        {
            "raw_date": dates + pd.offsets.MonthEnd(0),
            "year": dates.year,
            "month": dates.month,
            "quarter": dates.quarter,
            "di_surprise": np.linspace(-0.2, 0.2, n_months),
            "mp_shock_monthly": np.linspace(-0.2, 0.2, n_months),
        }
    ).to_csv(shock_path, index=False)
    return consumption_path, htm_path, shock_path


def test_consumption_parser_detects_all_year_month_columns_including_2024(tmp_path):
    path = tmp_path / "consumption.csv"
    _write_consumption(path, ["2020.04", "2024.01", "2024.12"], states=(11, 12))

    parsed = lp.read_consumption(path)

    assert parsed["date"].min() == pd.Timestamp("2020-04-01")
    assert parsed["date"].max() == pd.Timestamp("2024-12-01")
    assert len(parsed) == 6
    assert set(parsed.columns) == {
        "uf_code",
        "uf_abbrev",
        "state",
        "year",
        "month",
        "date",
        "consumption_index",
    }


def test_matched_panel_uses_inner_joins_and_required_fields(tmp_path):
    consumption_path, htm_path, shock_path = _synthetic_inputs(tmp_path, n_months=4)
    consumption = lp.read_consumption(consumption_path)
    htm = lp.read_htm_shares(htm_path)
    shocks = lp.read_shocks(shock_path)

    htm = htm.loc[~((htm["uf_code"] == 14) & (htm["month"] == 4))].copy()
    shocks = shocks.loc[shocks["month"] != 1].copy()

    panel, summary = lp.build_matched_panel(consumption, htm, shocks)

    assert pd.Timestamp("2024-01-01") not in set(panel["date"])
    assert not ((panel["uf_code"] == 14) & (panel["month"] == 4)).any()
    assert panel[lp.MATCH_REQUIRED_COLS].notna().all().all()
    assert set(lp.SHARE_COLS).issubset(panel.columns)
    assert summary.loc[summary["source"].eq("fully_matched"), "min_date"].iloc[0] == "2024-02"
    assert summary.loc[summary["source"].eq("fully_matched"), "max_date"].iloc[0] == "2024-04"


def test_validate_panel_checks_htm_shares_sum_to_one(tmp_path):
    consumption_path, htm_path, shock_path = _synthetic_inputs(tmp_path, n_months=5)
    panel, _ = lp.build_matched_panel(
        lp.read_consumption(consumption_path),
        lp.read_htm_shares(htm_path),
        lp.read_shocks(shock_path),
    )
    lp.validate_panel(panel)

    broken = panel.copy()
    broken.loc[broken.index[0], "share_Ricardian"] += 0.1
    try:
        lp.validate_panel(broken)
    except ValueError as exc:
        assert "shares do not sum to one" in str(exc)
    else:
        raise AssertionError("validate_panel should reject HtM shares that do not sum to one")


def test_local_projection_outputs_requested_horizons_for_both_specs(tmp_path):
    consumption_path, htm_path, shock_path = _synthetic_inputs(tmp_path, n_months=8)
    panel, _ = lp.build_matched_panel(
        lp.read_consumption(consumption_path),
        lp.read_htm_shares(htm_path),
        lp.read_shocks(shock_path),
    )
    lp.validate_panel(panel, max_horizon=2)

    irf, diagnostics = lp.run_local_projections(panel, max_horizon=2)

    assert {"lag1", "lag2", "lag1_time_fe", "lag2_time_fe"}.issubset(set(irf["spec"]))
    assert set(irf["response_type"]) == {"cumulative", "marginal"}
    assert set(irf["shock_variable"]) == {"mp_shock"}
    assert set(irf["shock_type"]) == {"Monthly monetary-policy shock from DI surprise"}
    assert set(irf["shock_direction"]) == {"negative signed shock"}
    assert set(irf["shock_unit"]) == {
        "one-unit decrease in mp_shock; source mp_shock values are sign-flipped for this reported IRF"
    }
    assert set(irf["shock_multiplier"]) == {-1.0}
    assert set(irf["horizon"]) == {0, 1, 2}
    assert set(irf["term"]) == {"mp_shock", "share_PH2M", "share_WH2M"}
    base_mp = irf.loc[
        irf["term"].eq("mp_shock") & irf["spec"].isin(["lag1", "lag2"])
    ]
    assert not base_mp["estimate"].isna().any()
    time_fe_mp = irf.loc[
        irf["term"].eq("mp_shock") & irf["spec"].str.endswith("_time_fe")
    ]
    assert time_fe_mp["estimate"].isna().all()
    assert not time_fe_mp["identified"].any()
    assert not diagnostics.empty
    assert not diagnostics["mp_shock_identified"].any()


def test_marginal_response_uses_horizon_to_horizon_log_change(tmp_path):
    consumption_path, htm_path, shock_path = _synthetic_inputs(tmp_path, n_months=5)
    panel, _ = lp.build_matched_panel(
        lp.read_consumption(consumption_path),
        lp.read_htm_shares(htm_path),
        lp.read_shocks(shock_path),
    )

    frame = lp.make_lp_frame(panel, horizon=2, response_type="marginal")
    sample_row = frame.dropna(subset=["y_resp"]).iloc[0]
    source = panel.loc[panel["uf_code"].eq(sample_row["uf_code"])].set_index("t_index")
    expected = (
        source.loc[sample_row["t_index"] + 2, "log_consumption"]
        - source.loc[sample_row["t_index"] + 1, "log_consumption"]
    )

    assert np.isclose(sample_row["y_resp"], expected)


def test_negative_shock_irf_sign_flips_positive_orientation(tmp_path):
    consumption_path, htm_path, shock_path = _synthetic_inputs(tmp_path, n_months=8)
    panel, _ = lp.build_matched_panel(
        lp.read_consumption(consumption_path),
        lp.read_htm_shares(htm_path),
        lp.read_shocks(shock_path),
    )

    positive, _ = lp.run_local_projections(
        panel,
        max_horizon=2,
        include_time_fe=False,
        shock_direction="positive",
    )
    negative, _ = lp.run_local_projections(
        panel,
        max_horizon=2,
        include_time_fe=False,
        shock_direction="negative",
    )
    pos_mp = positive.loc[positive["term"].eq("mp_shock"), "estimate"].to_numpy()
    neg_mp = negative.loc[negative["term"].eq("mp_shock"), "estimate"].to_numpy()

    assert np.allclose(neg_mp, -pos_mp)


def test_state_level_irfs_and_region_panels_are_written(tmp_path):
    consumption_path, htm_path, shock_path = _synthetic_inputs(
        tmp_path,
        n_months=8,
        n_states=4,
    )
    panel, _ = lp.build_matched_panel(
        lp.read_consumption(consumption_path),
        lp.read_htm_shares(htm_path),
        lp.read_shocks(shock_path),
    )

    state_irf = lp.run_state_local_projections(panel, max_horizon=2)
    paths = lp.plot_state_region_irfs(state_irf, tmp_path / "state_plots")

    assert set(state_irf["response_type"]) == {"cumulative"}
    assert set(state_irf["spec"]) == {"lag1", "lag2"}
    assert set(state_irf["horizon"]) == {0, 1, 2}
    assert set(state_irf["term"]) == {"mp_shock"}
    assert {"North"}.issubset(set(state_irf["macro_region"]))
    assert paths
    assert all(path.exists() and path.stat().st_size > 0 for path in paths)
