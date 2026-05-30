"""
steady_state.py
---------------
Computes the deterministic steady state for the three-agent
New Keynesian model with informality channel.

Agents:
    R  : Ricardian households
    W  : WH2M households (case flag selects Case 1 or Case 2)
    P  : PH2M households (dual formal/informal labor market)

Returns a dictionary `ss` containing all steady state values,
which is passed directly to model.py for Jacobian computation.
"""

import numpy as np
from scipy.optimize import fsolve
import warnings


# ----------------------------------------------------------------
# 1. Parameters
# ----------------------------------------------------------------

def get_parameters(case=1):
    """
    Returns a dictionary of all model parameters.

    Parameters
    ----------
    case : int
        1 = WH2M net borrowers (binding constraint)
        2 = WH2M net savers (slack constraint)

    Notes
    -----
    w_bar, theta_ltv, h_W are placeholders.
    Update these after running estimation.py.
    """
    p = {}

    # --- Household preferences ---
    p['beta']       = 0.99      # discount factor
    p['sigma']      = 1.00      # inverse elasticity of intertemporal substitution
    p['varphi']     = 1.00      # inverse Frisch elasticity

    # --- Production ---
    p['alpha']      = 0.40      # capital share
    p['delta']      = 0.025     # depreciation rate
    p['epsilon_y']  = 6.00      # elasticity of substitution across varieties

    # --- Nominal rigidities ---
    p['theta_p']    = 0.75      # Calvo price stickiness

    # --- Monetary policy ---
    p['phi_pi']     = 1.50      # Taylor rule inflation coefficient
    p['phi_y']      = 0.125     # Taylor rule output coefficient
    p['rho_m']      = 0.50      # MP shock persistence
    p['sigma_m']    = 0.0025    # MP shock standard deviation

    # --- Population shares ---
    p['lambda_R']   = 0.30      # share of Ricardian households
    p['lambda_W']   = 0.35      # share of WH2M households
    p['lambda_P']   = 0.35      # share of PH2M households

    # --- Informality and credit (placeholders) ---
    # UPDATE AFTER RUNNING estimation.py
    p['w_bar']      = 0.70      # informal wage (fraction of steady state formal wage)
    p['theta_ltv']  = 0.50      # loan-to-value ratio
    p['h_W']        = 1.00      # WH2M housing stock (normalized)

    # --- Fiscal (Case 2 only) ---
    p['b_bar']      = 0.60      # target government debt-to-output ratio
    p['psi_b']      = 0.90      # debt mean reversion speed

    # --- Case flag ---
    p['case']       = case

    return p


# ----------------------------------------------------------------
# 2. Analytical steady state
# ----------------------------------------------------------------

def compute_steady_state(p):
    """
    Computes the deterministic steady state analytically
    where possible, numerically where needed.

    Strategy:
        1. Pin down nominal variables from Fisher equation
        2. Pin down factor prices from firm optimality
        3. Pin down capital-labor ratio from cost minimization
        4. Use goods market clearing + population shares
           to find individual allocations
        5. Verify bond market clearing

    Parameters
    ----------
    p : dict
        Parameter dictionary from get_parameters()

    Returns
    -------
    ss : dict
        Steady state dictionary with all model variables
    """

    ss = {}

    # Store parameters in ss for convenience
    ss.update(p)

    # --------------------------------------------------------
    # 2.1 Nominal steady state
    # --------------------------------------------------------

    # Zero inflation target
    ss['pi']    = 0.0

    # Fisher equation: (1+i) = (1+r)(1+pi) => i = r at pi=0
    # Real rate from Euler: 1 = beta*(1+r) => r = 1/beta - 1
    ss['r']     = 1/p['beta'] - 1
    ss['ii']    = ss['r']           # nominal = real at zero inflation
    ss['ii_ss'] = ss['ii']
    ss['Q']     = 1 / (1 + ss['ii'])

    # --------------------------------------------------------
    # 2.2 Firm steady state
    # --------------------------------------------------------

    # Desired markup = epsilon/(epsilon-1)
    # Marginal cost = (epsilon-1)/epsilon in steady state
    ss['mc']    = (p['epsilon_y'] - 1) / p['epsilon_y']

    # Rental rate of capital from capital arbitrage
    # 1 = beta*(rk + 1 - delta) => rk = 1/beta - (1-delta)
    ss['rk']    = 1/p['beta'] - (1 - p['delta'])

    # Real wage from marginal cost and factor prices
    # mc = (w/(1-alpha))^(1-alpha) * (rk/alpha)^alpha
    # => w = (1-alpha) * mc^{1/(1-alpha)} * (alpha/rk)^{alpha/(1-alpha)}
    ss['w']     = ((1 - p['alpha'])
                   * ss['mc']**(1 / (1 - p['alpha']))
                   * (p['alpha'] / ss['rk'])**(p['alpha'] / (1 - p['alpha'])))

    # Price dispersion = 1 at zero inflation steady state
    ss['Delta'] = 1.0
    ss['P_star']= 1.0

    # --------------------------------------------------------
    # 2.3 Labor and capital
    # --------------------------------------------------------

    # Normalize output Y = 1
    ss['Y']     = 1.0
    ss['Y_ss']  = ss['Y']

    # Capital-labor ratio from cost minimization
    # rk/w = (alpha/(1-alpha)) * (N_f/K)
    # => K/N_f = (alpha/(1-alpha)) * (w/rk)
    KN_ratio    = (p['alpha'] / (1 - p['alpha'])) * (ss['w'] / ss['rk'])

    # From production function Y = K^alpha * N_f^(1-alpha)
    # and K = KN_ratio * N_f:
    # Y = (KN_ratio * N_f)^alpha * N_f^(1-alpha)
    # Y = KN_ratio^alpha * N_f
    # => N_f = Y / KN_ratio^alpha
    ss['N_f']   = ss['Y'] / (KN_ratio**p['alpha'])
    ss['K']     = KN_ratio * ss['N_f']
    ss['I']     = p['delta'] * ss['K']

    # --------------------------------------------------------
    # 2.4 PH2M steady state
    # --------------------------------------------------------

    # Informal wage in levels (w_bar is fraction of formal wage)
    # Note: p['w_bar'] is treated as a ratio w_bar/w in estimation
    # In steady state: w_bar_level = p['w_bar'] * ss['w']
    # For clarity we store the level
    ss['w_bar_level'] = p['w_bar'] * ss['w']

    # Sectoral allocation condition:
    # (N_Pf/N_Pi)^varphi = w / w_bar_level
    # Let x = N_Pf/N_Pi => x = (w/w_bar_level)^(1/varphi)
    x           = (ss['w'] / ss['w_bar_level'])**(1 / p['varphi'])

    # Time endowment: N_Pf + N_Pi = 1
    # N_Pf = x * N_Pi => x*N_Pi + N_Pi = 1 => N_Pi = 1/(1+x)
    ss['N_Pi']  = 1 / (1 + x)
    ss['N_Pf']  = x * ss['N_Pi']

    # PH2M consumption from budget constraint (no assets, no transfers in baseline)
    ss['C_P']   = ss['w'] * ss['N_Pf'] + ss['w_bar_level'] * ss['N_Pi']

    # --------------------------------------------------------
    # 2.5 Formal-labor split (symmetric R/W hours)
    # --------------------------------------------------------
    N_formal_RW = ss['N_f'] - p['lambda_P'] * ss['N_Pf']
    N_RW        = N_formal_RW / (p['lambda_R'] + p['lambda_W'])
    ss['N_R']   = N_RW
    ss['N_W']   = N_RW

    # --------------------------------------------------------
    # 2.6 Consumption allocation (budget-consistent)
    # --------------------------------------------------------
    ss['D'] = ss['Y'] - ss['w'] * ss['N_f'] - ss['rk'] * ss['K']
    ss['C'] = ss['Y'] - ss['I']

    if p['case'] == 1:
        # WH2M consumption from binding-constraint budget (debt service).
        debt_service = p['theta_ltv'] * p['h_W'] * ss['ii'] / (1 + ss['ii'])
        ss['C_W']    = ss['w'] * ss['N_W'] - debt_service
    else:
        # WH2M consumption from net-saver budget (interest income + transfer).
        # Equal per-capita bond holdings (matches section 2.7).
        B_W_ss = p['b_bar'] * ss['Y'] / (p['lambda_R'] + p['lambda_W'])
        T_W_ss = ss['ii'] / (1 + ss['ii']) * (p['b_bar'] * ss['Y'])
        ss['C_W'] = ss['w'] * ss['N_W'] + T_W_ss + ss['ii'] / (1 + ss['ii']) * B_W_ss

    # Ricardian consumption is the residual of the aggregate identity
    # (Ricardian budget closes by Walras via dividends/bond/capital income).
    ss['C_R'] = (ss['C'] - p['lambda_W'] * ss['C_W']
                 - p['lambda_P'] * ss['C_P']) / p['lambda_R']

    # Labor-disutility weights chosen so each labor FOC holds at SS:
    #   chi * N^varphi * C^sigma = w
    ss['chi_R'] = ss['w'] / (ss['N_R']**p['varphi'] * ss['C_R']**p['sigma'])
    ss['chi_W'] = ss['w'] / (ss['N_W']**p['varphi'] * ss['C_W']**p['sigma'])

    # --------------------------------------------------------
    # 2.7 Bond holdings
    # --------------------------------------------------------

    if p['case'] == 1:
        # Case 1: WH2M net borrowers, constraint binds
        ss['B_W']   = -p['theta_ltv'] * p['h_W']
        ss['mu']    = _compute_mu_ss(ss, p)

        # Bond market clearing: lambda_R*B_R + lambda_W*B_W = 0
        ss['B_R']   = -p['lambda_W'] * ss['B_W'] / p['lambda_R']
        ss['B_gov'] = 0.0

        # Transfers (zero in baseline under Case 1)
        ss['T_R']   = 0.0
        ss['T_W']   = 0.0
        ss['T_P']   = 0.0

    else:
        # Case 2: WH2M net savers, constraint slack
        # Bond holdings determined by Euler equations
        # In steady state both R and W hold positive bonds
        # Government is net borrower: B_gov = b_bar * Y
        ss['B_gov'] = p['b_bar'] * ss['Y']

        # Equal per-capita bond holdings: lambda_R*B_R + lambda_W*B_W = B_gov
        ss['B_R']   = p['b_bar'] * ss['Y'] / (p['lambda_R'] + p['lambda_W'])
        ss['B_W']   = p['b_bar'] * ss['Y'] / (p['lambda_R'] + p['lambda_W'])
        ss['mu']    = 0.0

        # Equal transfers funded by debt service
        # T = (i/(1+i)) * B_gov / (lambda_R + lambda_W + lambda_P)
        T_total     = ss['ii'] / (1 + ss['ii']) * ss['B_gov']
        ss['T_R']   = T_total
        ss['T_W']   = T_total
        ss['T_P']   = T_total

    # --------------------------------------------------------
    # 2.8 Aggregate labor
    # --------------------------------------------------------

    ss['N_i']   = p['lambda_P'] * ss['N_Pi']
    ss['N']     = ss['N_f'] + ss['N_i']

    # --------------------------------------------------------
    # 2.9 Shock (zero in steady state)
    # --------------------------------------------------------

    ss['eps_m'] = 0.0

    return ss


def _compute_mu_ss(ss, p):
    """
    Computes the steady state Lagrange multiplier mu
    on the WH2M collateral constraint (Case 1).

    From the modified Euler equation in steady state:
        C_W^(-sigma) = beta*(1+r)*C_W^(-sigma) + mu
        => mu = C_W^(-sigma) * (1 - beta*(1+r))
        => mu = C_W^(-sigma) * (1 - 1)  [since beta*(1+r)=1]
        => mu = 0 in steady state

    Note: mu = 0 in steady state but mu > 0 off steady state.
    The constraint binds (B_W = -theta*h_W) but the multiplier
    is zero in the non-stochastic steady state because
    beta*(1+r) = 1 exactly.
    """
    return 0.0


# ----------------------------------------------------------------
# 3. Steady state verification
# ----------------------------------------------------------------

def verify_steady_state(ss):
    """
    Checks all steady state conditions hold numerically.
    Prints a report of residuals.

    Parameters
    ----------
    ss : dict
        Steady state dictionary from compute_steady_state()
    """

    p       = ss
    tol     = 1e-6
    passed  = True

    checks  = {}

    # Ricardian Euler: beta*(1+r) = 1
    checks['Ricardian Euler']       = abs(p['beta'] * (1 + p['r']) - 1)

    # Marginal cost
    checks['Marginal cost']         = abs(
        ss['mc'] - (ss['w'] / (1 - p['alpha']))**(1 - p['alpha'])
                 * (ss['rk'] / p['alpha'])**p['alpha']
    )

    # Production function
    checks['Production function']   = abs(
        ss['Y'] - ss['K']**p['alpha'] * ss['N_f']**(1 - p['alpha'])
    )

    # Capital law of motion: I = delta*K
    checks['Capital law of motion'] = abs(ss['I'] - p['delta'] * ss['K'])

    # Goods market clearing: Y = C + I
    checks['Goods market']          = abs(ss['Y'] - ss['C'] - ss['I'])

    # Aggregate consumption
    C_agg = (p['lambda_R'] * ss['C_R']
             + p['lambda_W'] * ss['C_W']
             + p['lambda_P'] * ss['C_P'])
    checks['Aggregate consumption'] = abs(ss['C'] - C_agg)

    # PH2M allocation condition
    checks['PH2M allocation']       = abs(
        (ss['N_Pf'] / ss['N_Pi'])**p['varphi'] - ss['w'] / ss['w_bar_level']
    )

    # PH2M time endowment
    checks['PH2M time endowment']   = abs(ss['N_Pf'] + ss['N_Pi'] - 1)

    # Bond market clearing
    if p['case'] == 1:
        checks['Bond market (Case 1)'] = abs(
            p['lambda_R'] * ss['B_R'] + p['lambda_W'] * ss['B_W']
        )
    else:
        checks['Bond market (Case 2)'] = abs(
            p['lambda_R'] * ss['B_R']
            + p['lambda_W'] * ss['B_W']
            - ss['B_gov']
        )

    # Informality condition: w_bar < w
    checks['Informality condition (w_bar < w)'] = max(
        0, ss['w_bar_level'] - ss['w']
    )

    # Ricardian labor FOC: chi_R * N_R^varphi * C_R^sigma = w
    checks['Ricardian labor FOC'] = abs(
        ss['chi_R'] * ss['N_R']**p['varphi'] * ss['C_R']**p['sigma'] - ss['w']
    )

    # WH2M labor FOC: chi_W * N_W^varphi * C_W^sigma = w
    checks['WH2M labor FOC'] = abs(
        ss['chi_W'] * ss['N_W']**p['varphi'] * ss['C_W']**p['sigma'] - ss['w']
    )

    # WH2M budget (Case 1: binding-constraint debt service)
    if p['case'] == 1:
        ds = p['theta_ltv'] * p['h_W'] * ss['ii'] / (1 + ss['ii'])
        checks['WH2M budget (Case 1)'] = abs(
            ss['C_W'] - (ss['w'] * ss['N_W'] - ds)
        )

    # NKPC at zero inflation (mc deviation form): residual must be 0
    mc_ss_check = (p['epsilon_y'] - 1) / p['epsilon_y']
    checks['NKPC (mc deviation)'] = abs(
        ss['pi'] - p['beta'] * ss['pi']
        - (1 - p['theta_p']) * (1 - p['beta'] * p['theta_p']) / p['theta_p']
        * (ss['mc'] - mc_ss_check)
    )

    # Taylor rule at SS
    checks['Taylor rule'] = abs(
        ss['ii'] - ss['ii_ss'] - p['phi_pi'] * ss['pi']
        - p['phi_y'] * (ss['Y'] - ss['Y_ss'])
    )

    # Print report
    print(f"\n{'='*50}")
    print(f"Steady State Verification — Case {p['case']}")
    print(f"{'='*50}")
    for name, residual in checks.items():
        status = 'PASS' if residual < tol else 'FAIL'
        if status == 'FAIL':
            passed = False
        print(f"  {status}  {name:<35} residual = {residual:.2e}")
    print(f"{'='*50}")
    print(f"  Overall: {'ALL PASSED' if passed else 'SOME FAILED'}")
    print(f"{'='*50}\n")

    return passed


def print_steady_state(ss):
    """
    Prints a formatted table of steady state values.
    """
    p = ss
    print(f"\n{'='*50}")
    print(f"Steady State Values — Case {p['case']}")
    print(f"{'='*50}")
    print(f"  {'Output Y':<30} {ss['Y']:.4f}")
    print(f"  {'Consumption C':<30} {ss['C']:.4f}")
    print(f"  {'Investment I':<30} {ss['I']:.4f}")
    print(f"  {'Capital K':<30} {ss['K']:.4f}")
    print(f"  {'Formal labor N_f':<30} {ss['N_f']:.4f}")
    print(f"  {'Informal labor N_i':<30} {ss['N_i']:.4f}")
    print(f"  {'Real wage w':<30} {ss['w']:.4f}")
    print(f"  {'Rental rate rk':<30} {ss['rk']:.4f}")
    print(f"  {'Marginal cost mc':<30} {ss['mc']:.4f}")
    print(f"  {'Nominal rate ii':<30} {ss['ii']:.4f}")
    print(f"  {'Inflation pi':<30} {ss['pi']:.4f}")
    print(f"  ---")
    print(f"  {'C_R (Ricardian)':<30} {ss['C_R']:.4f}")
    print(f"  {'C_W (WH2M)':<30} {ss['C_W']:.4f}")
    print(f"  {'C_P (PH2M)':<30} {ss['C_P']:.4f}")
    print(f"  {'N_R (Ricardian)':<30} {ss['N_R']:.4f}")
    print(f"  {'N_W (WH2M)':<30} {ss['N_W']:.4f}")
    print(f"  {'N_Pf (PH2M formal)':<30} {ss['N_Pf']:.4f}")
    print(f"  {'N_Pi (PH2M informal)':<30} {ss['N_Pi']:.4f}")
    print(f"  {'B_R (Ricardian bonds)':<30} {ss['B_R']:.4f}")
    print(f"  {'B_W (WH2M bonds)':<30} {ss['B_W']:.4f}")
    print(f"  {'w_bar_level':<30} {ss['w_bar_level']:.4f}")
    print(f"  {'Informal share (N_Pi)':<30} {ss['N_Pi']:.4f}")
    print(f"  {'I/Y ratio':<30} {ss['I']/ss['Y']:.4f}  (target: 0.20)")
    print(f"  {'C/Y ratio':<30} {ss['C']/ss['Y']:.4f}  (target: 0.65)")
    print(f"{'='*50}\n")


# ----------------------------------------------------------------
# 4. Main — run directly to inspect steady state
# ----------------------------------------------------------------

if __name__ == '__main__':

    for case in [1, 2]:
        print(f"\nComputing steady state for Case {case}...")
        p   = get_parameters(case=case)
        ss  = compute_steady_state(p)
        print_steady_state(ss)
        verify_steady_state(ss)
