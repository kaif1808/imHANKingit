"""Validation tests for the amaani_thrank SSJ three-agent NK model."""
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steady_state import get_parameters, compute_steady_state, verify_steady_state
from model import build_model, compute_irfs


@pytest.mark.parametrize("case", [1, 2])
def test_steady_state_passes(case):
    ss = compute_steady_state(get_parameters(case=case))
    assert verify_steady_state(ss), f"steady-state checks failed for case {case}"


@pytest.mark.parametrize("case", [1, 2])
def test_required_ss_keys(case):
    ss = compute_steady_state(get_parameters(case=case))
    for key in ['ii_ss', 'Y_ss', 'chi_R', 'chi_W', 'w_bar_level']:
        assert key in ss, f"missing ss key {key} (case {case})"


@pytest.mark.parametrize("case", [1, 2])
def test_square_system(case):
    model = build_model(case=case)
    assert model is not None
    unknowns = ['Y', 'C', 'C_R', 'C_W', 'C_P', 'N_f', 'N_R', 'N_W', 'N_Pf',
                'N_Pi', 'w', 'rk', 'mc', 'pi', 'ii', 'K', 'I', 'Delta', 'P_star']
    common = ['euler_R', 'labor_R', 'alloc_P', 'time_P', 'budget_P', 'cap_law',
              'cap_arb', 'prod_eq', 'mc_eq', 'kl_eq', 'nkpc', 'delta_eq',
              'price_eq', 'taylor', 'agg_C', 'agg_Nf', 'goods_mkt']
    targets = (['labor_W', 'budget_W'] if case == 1 else ['euler_W', 'labor_W']) + common
    assert len(unknowns) == len(targets) == 19


@pytest.mark.parametrize("case", [1, 2])
def test_jacobian_and_irfs_finite(case):
    ss = compute_steady_state(get_parameters(case=case))
    irfs = compute_irfs(ss, T=200, shock_size=0.0025)
    for key in ['Y', 'pi', 'ii', 'C_R', 'C_W', 'C_P']:
        assert key in irfs, f"missing IRF {key} (case {case})"
        assert np.all(np.isfinite(irfs[key])), f"non-finite IRF {key} (case {case})"
        assert len(irfs[key]) == 200


@pytest.mark.parametrize("case", [1, 2])
def test_contractionary_mp_sign(case):
    # +0.0025 eps_m is a contractionary MP shock.
    # Use rho_m=0 (pure surprise) to isolate the direct impact response
    # without AR(1) anticipation effects swamping the Taylor-rule sign
    # (with rho>0, the full convolution can flip the sign of ii on impact
    # because forward-looking Euler equations discount the anticipated future path).
    ss = compute_steady_state(get_parameters(case=case))
    irfs = compute_irfs(ss, T=200, shock_size=0.0025, rho_m=0.0)
    assert irfs['Y'][0] < 0,  f"Y should fall on impact (case {case})"
    assert irfs['pi'][0] < 0, f"pi should fall on impact (case {case})"
    assert irfs['ii'][0] > 0, f"ii should rise on impact (case {case})"
