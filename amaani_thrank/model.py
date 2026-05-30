"""
model.py
--------
SSJ model blocks for the three-agent New Keynesian model
with informality channel.

Block structure:
    1. ricardian_hh    — Ricardian household (Euler + labor)
    2. wh2m_hh_case1   — WH2M household Case 1 (binding constraint)
    2. wh2m_hh_case2   — WH2M household Case 2 (slack constraint)
    3. ph2m_hh         — PH2M household (allocation + budget, static)
    4. capital_block   — Capital law of motion + arbitrage
    5. firms_block     — Production + marginal cost + NKPC
    6. monetary_block  — Taylor rule
    7. aggregation     — Consumption + labor aggregation
    8. mkt_clearing    — Goods market clearing

Usage:
    from steady_state import get_parameters, compute_steady_state
    from model import build_model, compute_irfs

    p   = get_parameters(case=1)
    ss  = compute_steady_state(p)
    irfs = compute_irfs(ss, T=300, shock_size=0.0025)
"""

import numpy as np
from sequence_jacobian import simple, create_model
from sequence_jacobian.classes import SteadyStateDict, JacobianDict
from sequence_jacobian.classes.sparse_jacobians import make_matrix


# ----------------------------------------------------------------
# 1. Ricardian Household Block
# ----------------------------------------------------------------

@simple
def ricardian_hh(C_R, N_R, w, ii, pi, beta, sigma, varphi, chi_R):
    # Euler: ii is contemporaneous (Gali convention; .mod uses ii(+1)).
    euler_R = C_R**(-sigma) - beta * (1 + ii) / (1 + pi(+1)) * C_R(+1)**(-sigma)
    labor_R = chi_R * N_R**varphi * C_R**sigma - w
    return euler_R, labor_R


# ----------------------------------------------------------------
# 2. WH2M Household Block — Case 1 (binding constraint)
# ----------------------------------------------------------------

@simple
def wh2m_hh_case1(C_W, N_W, w, ii, beta, sigma, varphi, theta_ltv, h_W, chi_W):
    # Case 1: binding collateral constraint. B_W = -theta_ltv*h_W fixed.
    # (B_W(-1) - Q*B_W) with Q=1/(1+ii)  ==  -theta_ltv*h_W*ii/(1+ii).
    debt_service = theta_ltv * h_W * ii / (1 + ii)
    budget_W = C_W - (w * N_W - debt_service)
    labor_W = chi_W * N_W**varphi * C_W**sigma - w
    # euler_W is dropped: in Case 1 it only pins the untracked multiplier mu.
    return labor_W, budget_W


# ----------------------------------------------------------------
# 2b. WH2M Household Block — Case 2 (slack constraint)
# ----------------------------------------------------------------

@simple
def wh2m_hh_case2(C_W, N_W, w, ii, pi, beta, sigma, varphi, chi_W):
    # Case 2: slack constraint (mu=0), standard Euler.
    euler_W = C_W**(-sigma) - beta * (1 + ii) / (1 + pi(+1)) * C_W(+1)**(-sigma)
    labor_W = chi_W * N_W**varphi * C_W**sigma - w
    return euler_W, labor_W


# ----------------------------------------------------------------
# 3. PH2M Household Block (purely static)
# ----------------------------------------------------------------

@simple
def ph2m_hh(C_P, N_Pf, N_Pi, w, w_bar_level, varphi):
    # Sectoral allocation: (N_Pf/N_Pi)^varphi = w/w_bar_level
    alloc_P  = (N_Pf / N_Pi)**varphi - w / w_bar_level

    # Time endowment: N_Pf + N_Pi = 1
    time_P   = N_Pf + N_Pi - 1

    # Budget constraint: C_P = w*N_Pf + w_bar_level*N_Pi
    budget_P = C_P - (w * N_Pf + w_bar_level * N_Pi)

    return alloc_P, time_P, budget_P


# ----------------------------------------------------------------
# 4. Capital Block
# ----------------------------------------------------------------

@simple
def capital_block(K, I, rk, C_R, beta, delta, sigma):
    # Capital is predetermined: K_t = (1-delta)*K_{t-1} + I_t
    cap_law = K - ((1 - delta) * K(-1) + I)

    # Capital Euler: 1 = beta * (C_R(+1)/C_R)^(-sigma) * (rk(+1) + 1 - delta)
    cap_arb = 1 - beta * (C_R(+1) / C_R)**(-sigma) * (rk(+1) + 1 - delta)

    return cap_law, cap_arb


# ----------------------------------------------------------------
# 5. Firms Block
# ----------------------------------------------------------------

@simple
def firms_block(Y, K, N_f, w, rk, mc, pi, Delta, P_star,
                alpha, epsilon_y, theta_p, beta):
    # Production: Y = K(-1)^alpha * N_f^(1-alpha) / Delta
    prod_eq  = Y - K(-1)**alpha * N_f**(1 - alpha) / Delta

    # Marginal cost: mc = (w/(1-alpha))^(1-alpha) * (rk/alpha)^alpha
    mc_eq    = mc - (w / (1 - alpha))**(1 - alpha) * (rk / alpha)**alpha

    # Optimal K/N ratio: rk/w = (alpha/(1-alpha)) * N_f/K(-1)
    kl_eq    = rk / w - (alpha / (1 - alpha)) * (N_f / K(-1))

    kappa    = (1 - theta_p) * (1 - beta * theta_p) / theta_p
    mc_ss    = (epsilon_y - 1) / epsilon_y
    # NKPC in marginal-cost deviation so the zero-inflation SS satisfies it.
    nkpc     = pi - beta * pi(+1) - kappa * (mc - mc_ss)

    # Price dispersion law of motion (faithful Dynare timing)
    delta_eq = (Delta
                - theta_p * Delta(-1) * ((1 + pi(-1)) / (1 + pi))**epsilon_y
                - (1 - theta_p) * P_star**(-epsilon_y))

    # Aggregate price index (Calvo)
    price_eq = (1
                - theta_p * (1 / (1 + pi))**(1 - epsilon_y)
                - (1 - theta_p) * P_star**(1 - epsilon_y))

    return prod_eq, mc_eq, kl_eq, nkpc, delta_eq, price_eq


# ----------------------------------------------------------------
# 6. Monetary Policy Block
# ----------------------------------------------------------------

@simple
def monetary_block(ii, pi, Y, eps_m, phi_pi, phi_y, ii_ss, Y_ss):
    # Taylor rule: ii = ii_ss + phi_pi*pi + phi_y*(Y - Y_ss) + eps_m
    taylor = ii - ii_ss - phi_pi * pi - phi_y * (Y - Y_ss) - eps_m

    return taylor


# ----------------------------------------------------------------
# 7. Aggregation Block (slim — bond market is Walras-redundant)
# ----------------------------------------------------------------

@simple
def aggregation_block(C, C_R, C_W, C_P, N_f, N_R, N_W, N_Pf,
                      lambda_R, lambda_W, lambda_P):
    agg_C  = C - (lambda_R * C_R + lambda_W * C_W + lambda_P * C_P)
    agg_Nf = N_f - (lambda_R * N_R + lambda_W * N_W + lambda_P * N_Pf)
    return agg_C, agg_Nf


# ----------------------------------------------------------------
# 8. Market Clearing Block
# ----------------------------------------------------------------

@simple
def mkt_clearing(Y, C, I):
    goods_mkt = Y - C - I
    return goods_mkt


# ----------------------------------------------------------------
# 9. Build model
# ----------------------------------------------------------------

def build_model(case=1):
    """
    Assembles all blocks into a complete model.

    Parameters
    ----------
    case : int
        1 = WH2M net borrowers (Case 1, binding constraint)
        2 = WH2M net savers   (Case 2, slack constraint)

    Returns
    -------
    model : sequence_jacobian Model object
    """

    if case == 1:
        wh2m_block = wh2m_hh_case1
    else:
        wh2m_block = wh2m_hh_case2

    blocks = [
        ricardian_hh,
        wh2m_block,
        ph2m_hh,
        capital_block,
        firms_block,
        monetary_block,
        aggregation_block,
        mkt_clearing,
    ]

    model = create_model(blocks, name=f'three_agent_nk_case{case}')

    return model


# ----------------------------------------------------------------
# 10. Compute IRFs
# ----------------------------------------------------------------

def compute_irfs(ss, T=300, shock_size=None, rho_m=None):
    """
    Computes impulse response functions to a monetary policy shock.

    Parameters
    ----------
    ss         : dict — steady state from compute_steady_state()
    T          : int  — number of periods for Jacobian (default 300)
    shock_size : float — size of MP shock (default: ss['sigma_m'])
    rho_m      : float — shock persistence (default: ss['rho_m'])

    Returns
    -------
    irfs : dict
        Keys are variable names, values are arrays of length T
        giving the impulse response to a one-unit shock scaled
        by shock_size.
    """

    if shock_size is None:
        shock_size = ss['sigma_m']
    if rho_m is None:
        rho_m = ss['rho_m']

    case  = ss['case']
    model = build_model(case=case)

    # 19 unknowns
    unknowns = ['Y', 'C', 'C_R', 'C_W', 'C_P',
                'N_f', 'N_R', 'N_W', 'N_Pf', 'N_Pi',
                'w', 'rk', 'mc', 'pi', 'ii', 'K', 'I',
                'Delta', 'P_star']

    # 19 targets, square with 19 unknowns. Dropped (intentionally):
    #   bond_mkt (Walras-redundant), agg_Ni/N (accounting identities).
    common = ['euler_R', 'labor_R',
              'alloc_P', 'time_P', 'budget_P',
              'cap_law', 'cap_arb',
              'prod_eq', 'mc_eq', 'kl_eq', 'nkpc', 'delta_eq', 'price_eq',
              'taylor', 'agg_C', 'agg_Nf', 'goods_mkt']
    if case == 1:
        # Case 1: WH2M Euler pins untracked multiplier -> use budget_W instead.
        targets = ['labor_W', 'budget_W'] + common
    else:
        # Case 2: slack constraint -> standard WH2M Euler.
        targets = ['euler_W', 'labor_W'] + common

    assert len(unknowns) == len(targets), \
        f"non-square system: {len(unknowns)} unknowns vs {len(targets)} targets"

    exogenous = ['eps_m']

    # solve_jacobian requires SteadyStateDict (not plain dict)
    ss_ssd = SteadyStateDict(ss) if not isinstance(ss, SteadyStateDict) else ss

    print(f"Computing Jacobian for Case {case} (T={T})...")

    # Pre-compute partial Jacobians for all blocks
    Js_pre = model.partial_jacobians(ss_ssd, exogenous + unknowns, targets, T)

    # H_U = partial Jacobian of targets w.r.t. unknowns (n_tgts*T, n_unks*T)
    H_U = model.jacobian(ss_ssd, unknowns, targets, T, Js_pre).pack(T)

    # H_Z = partial Jacobian of targets w.r.t. exogenous (n_tgts*T, n_shocks*T).
    # SSJ's jacobian returns only non-zero-response outputs; we need all targets,
    # so build the full matrix explicitly.
    H_Z_partial = model.jacobian(ss_ssd, exogenous, targets, T, Js_pre)
    n_tgts   = len(targets)
    n_shocks = len(exogenous)
    H_Z_full = np.zeros((n_tgts * T, n_shocks * T))
    for i_tgt, tgt in enumerate(targets):
        if tgt not in H_Z_partial.outputs:
            continue
        for i_sh, sh in enumerate(exogenous):
            J_block = H_Z_partial[tgt].get(sh)
            if J_block is not None:
                H_Z_full[i_tgt*T:(i_tgt+1)*T, i_sh*T:(i_sh+1)*T] = make_matrix(J_block, T)

    # GE Jacobian: U_Z = -H_U^{-1} H_Z  (how unknowns respond to shocks)
    U_Z_packed = -np.linalg.solve(H_U, H_Z_full)
    print("Jacobian computed successfully.")

    # AR(1) shock process: eps_m_t = rho_m^t * shock_size
    shock_path = shock_size * rho_m**np.arange(T)

    # IRFs = U_Z rows × shock_path; skip overflow silently (accounting vars)
    irfs = {}
    import warnings as _warnings
    for i_var, var in enumerate(unknowns):
        U_row = U_Z_packed[i_var*T:(i_var+1)*T, :n_shocks*T]
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore', RuntimeWarning)
            irf_val = U_row @ shock_path
        if np.all(np.isfinite(irf_val)):
            irfs[var] = irf_val

    # Add relative IRFs (key objects for estimation)
    if 'C_P' in irfs and 'C_R' in irfs:
        irfs['C_P_rel_R'] = irfs['C_P'] - irfs['C_R']

    if 'C_W' in irfs and 'C_R' in irfs:
        irfs['C_W_rel_R'] = irfs['C_W'] - irfs['C_R']

    return irfs


# ----------------------------------------------------------------
# 11. Main — run directly to inspect IRFs
# ----------------------------------------------------------------

if __name__ == '__main__':

    import matplotlib.pyplot as plt
    from steady_state import get_parameters, compute_steady_state, verify_steady_state

    for case in [1, 2]:

        print(f"\n{'='*50}")
        print(f"Running Case {case}")
        print(f"{'='*50}")

        # Steady state
        p   = get_parameters(case=case)
        ss  = compute_steady_state(p)
        ok  = verify_steady_state(ss)

        if not ok:
            print(f"Steady state verification failed for Case {case}. Skipping IRFs.")
            continue

        # IRFs
        irfs = compute_irfs(ss, T=300, shock_size=0.0025)

        # Plot
        H        = 20
        horizons = np.arange(H)
        fig, axes = plt.subplots(2, 3, figsize=(14, 8))
        fig.suptitle(f'IRFs to Monetary Policy Shock — Case {case}', fontsize=14)

        plot_vars = [
            ('Y',         'Output'),
            ('pi',        'Inflation'),
            ('ii',        'Nominal Rate'),
            ('C_R',       'Consumption — Ricardian'),
            ('C_W',       'Consumption — WH2M'),
            ('C_P',       'Consumption — PH2M'),
        ]

        for ax, (var, label) in zip(axes.flat, plot_vars):
            if var in irfs:
                ax.plot(horizons, irfs[var][:H] * 100, 'b-', linewidth=2)
                ax.axhline(0, color='k', linewidth=0.8, linestyle='--')
                ax.set_title(label)
                ax.set_xlabel('Quarters')
                ax.set_ylabel('% deviation from SS')
                ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(f'irfs_case{case}.pdf', dpi=150, bbox_inches='tight')
        print(f"IRFs saved to irfs_case{case}.pdf")
        plt.close()

        # Print relative IRFs (key empirical targets)
        print(f"\nRelative IRFs at horizons 0-8:")
        print(f"{'Horizon':<10} {'C_P/C_R':<15} {'C_W/C_R':<15}")
        for h in range(9):
            cp_rel = irfs.get('C_P_rel_R', np.zeros(H))[h] * 100
            cw_rel = irfs.get('C_W_rel_R', np.zeros(H))[h] * 100
            print(f"{h:<10} {cp_rel:<15.4f} {cw_rel:<15.4f}")
