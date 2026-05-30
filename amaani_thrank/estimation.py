"""
estimation.py
-------------
Minimum distance estimation for the three-agent NK model.

Finds w_bar, theta_ltv, h_W by minimizing the distance between
model-implied IRFs and empirical local projection estimates.

Empirical targets:
    - PH2M/Ricardian relative consumption IRF (near flat)
    - WH2M/Ricardian relative consumption IRF (amplified)

Usage:
    python estimation.py

After running, copy the printed parameter estimates into
steady_state.py (get_parameters function) and rerun model.py
for the final IRFs.
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize, differential_evolution
import warnings
warnings.filterwarnings('ignore')

from steady_state import get_parameters, compute_steady_state
from model import compute_irfs


# ----------------------------------------------------------------
# 1. Empirical moments
# ----------------------------------------------------------------

def get_empirical_moments(H=12):
    """
    Returns empirical IRF moments from local projections.

    IMPORTANT: Replace the placeholder arrays below with your
    actual LP estimates. Each entry corresponds to one quarter
    h = 0, 1, ..., H.

    Arrays should have length H+1.

    Parameters
    ----------
    H : int
        Number of horizons to match (default 12 quarters)

    Returns
    -------
    m_hat : np.ndarray, shape (2*(H+1),)
        Stacked vector of [delta_PH2M_R, delta_WH2M_R]
        Both expressed as log deviations (not percentages)

    W_mat : np.ndarray, shape (2*(H+1), 2*(H+1))
        Weighting matrix — identity for now,
        replace with inv(Sigma) from LP standard errors
    """

    # --------------------------------------------------------
    # FILL THESE IN FROM YOUR LOCAL PROJECTION ESTIMATES
    # Units: log deviations (divide percentages by 100)
    # Empirical source: results/tables/basic_state_month_lp/irf.csv
    #   columns: horizon, interaction (PH2M/WH2M), estimate, std_error
    # --------------------------------------------------------

    # PH2M consumption response relative to Ricardian
    # Your empirical finding: near flat (close to zero)
    delta_PH2M_R = np.array([
        0.000,   # h=0
        0.002,   # h=1
        0.001,   # h=2
        0.000,   # h=3
        -0.001,  # h=4
        0.000,   # h=5
        0.001,   # h=6
        0.000,   # h=7
        0.000,   # h=8
        -0.001,  # h=9
        0.000,   # h=10
        0.001,   # h=11
        0.000,   # h=12
    ])

    # WH2M consumption response relative to Ricardian
    # Your empirical finding: negative (WH2M more affected)
    delta_WH2M_R = np.array([
        -0.020,  # h=0
        -0.035,  # h=1
        -0.045,  # h=2
        -0.050,  # h=3
        -0.048,  # h=4
        -0.042,  # h=5
        -0.035,  # h=6
        -0.028,  # h=7
        -0.022,  # h=8
        -0.018,  # h=9
        -0.014,  # h=10
        -0.010,  # h=11
        -0.008,  # h=12
    ])

    # --------------------------------------------------------
    # Stack moments
    # --------------------------------------------------------
    assert len(delta_PH2M_R) == H + 1, \
        f"delta_PH2M_R must have {H+1} entries, got {len(delta_PH2M_R)}"
    assert len(delta_WH2M_R) == H + 1, \
        f"delta_WH2M_R must have {H+1} entries, got {len(delta_WH2M_R)}"

    m_hat = np.concatenate([delta_PH2M_R, delta_WH2M_R])

    # --------------------------------------------------------
    # Weighting matrix
    # Identity for now — replace with inv(Sigma) from LP SEs
    # --------------------------------------------------------
    # If you have LP standard errors se_PH2M and se_WH2M
    # (arrays of length H+1), use:
    #
    # se_PH2M  = np.array([...])   # standard errors from LP
    # se_WH2M  = np.array([...])
    # Sigma    = np.diag(np.concatenate([se_PH2M, se_WH2M])**2)
    # W_mat    = np.linalg.inv(Sigma)
    #
    # For now: identity (equal weighting across horizons)
    W_mat = np.eye(2 * (H + 1))

    return m_hat, W_mat


# ----------------------------------------------------------------
# 2. Model moments
# ----------------------------------------------------------------

def get_model_moments(theta, H=12, case=1, T=300):
    """
    Solves the model for given parameters and returns
    model-implied relative IRFs as a moment vector.

    Parameters
    ----------
    theta : array-like, length 3
        [w_bar_ratio, theta_ltv, h_W]
        w_bar_ratio = w_bar / w_ss (informal/formal wage ratio)
    H     : int   — number of horizons
    case  : int   — 1 or 2
    T     : int   — Jacobian computation periods

    Returns
    -------
    m_model : np.ndarray, shape (2*(H+1),)
        Stacked [delta_PH2M_R, delta_WH2M_R] from model
        Returns large penalty vector if model fails to solve
    """

    w_bar_ratio, theta_ltv, h_W = theta

    # Get base parameters and update with current theta
    p               = get_parameters(case=case)
    p['w_bar']      = w_bar_ratio   # ratio w_bar/w_ss
    p['theta_ltv']  = theta_ltv
    p['h_W']        = h_W

    try:
        # Compute steady state
        ss      = compute_steady_state(p)

        # Verify informality condition holds
        if ss['w_bar_level'] >= ss['w']:
            return np.ones(2 * (H + 1)) * 1e6

        # Compute IRFs
        irfs    = compute_irfs(ss, T=T, shock_size=p['sigma_m'])

        # Extract relative IRFs
        delta_PH2M_R = irfs.get('C_P_rel_R', np.zeros(T))[:H+1]
        delta_WH2M_R = irfs.get('C_W_rel_R', np.zeros(T))[:H+1]

        m_model = np.concatenate([delta_PH2M_R, delta_WH2M_R])

        # Check for NaN or Inf
        if not np.all(np.isfinite(m_model)):
            return np.ones(2 * (H + 1)) * 1e6

        return m_model

    except Exception as e:
        # Model failed to solve — return large penalty
        return np.ones(2 * (H + 1)) * 1e6


# ----------------------------------------------------------------
# 3. Objective function
# ----------------------------------------------------------------

def objective(theta, m_hat, W_mat, H=12, case=1, T=300):
    """
    Minimum distance objective function.

    J(theta) = [m_hat - m(theta)]' W [m_hat - m(theta)]

    Parameters
    ----------
    theta : array-like — [w_bar_ratio, theta_ltv, h_W]
    m_hat : np.ndarray — empirical moment vector
    W_mat : np.ndarray — weighting matrix
    H     : int        — number of horizons
    case  : int        — WH2M case
    T     : int        — Jacobian periods

    Returns
    -------
    distance : float — weighted moment distance
    """

    m_model  = get_model_moments(theta, H=H, case=case, T=T)
    diff     = m_hat - m_model
    distance = diff @ W_mat @ diff

    return distance


# ----------------------------------------------------------------
# 4. Main estimation routine
# ----------------------------------------------------------------

def run_estimation(case=1, H=12, T=300,
                   method='L-BFGS-B',
                   n_starts=5,
                   verbose=True):
    """
    Runs the minimum distance estimation.

    Two-step procedure:
        Step 1: Global search with differential evolution
                to find a good starting point
        Step 2: Local refinement with L-BFGS-B

    Parameters
    ----------
    case     : int  — WH2M case (1 or 2)
    H        : int  — horizons to match
    T        : int  — Jacobian periods
    method   : str  — local optimizer ('L-BFGS-B' or 'Nelder-Mead')
    n_starts : int  — number of random starting points for local search
    verbose  : bool — print progress

    Returns
    -------
    result : dict with keys:
        'theta_hat'  : estimated parameters [w_bar, theta_ltv, h_W]
        'w_bar'      : informal/formal wage ratio
        'theta_ltv'  : loan-to-value ratio
        'h_W'        : WH2M housing stock
        'fval'       : objective function value at optimum
        'm_hat'      : empirical moments
        'm_model'    : model moments at optimum
    """

    if verbose:
        print(f"\n{'='*60}")
        print(f"Minimum Distance Estimation — Case {case}")
        print(f"Matching {H+1} horizons of relative IRFs")
        print(f"{'='*60}\n")

    # Get empirical moments
    m_hat, W_mat = get_empirical_moments(H=H)

    # Parameter bounds
    # theta = [w_bar_ratio, theta_ltv, h_W]
    bounds = [
        (0.30, 0.95),   # w_bar_ratio: informal wage 30-95% of formal
        (0.10, 0.90),   # theta_ltv:   LTV ratio
        (0.50, 3.00),   # h_W:         housing stock (normalized units)
    ]

    obj = lambda theta: objective(theta, m_hat, W_mat, H=H, case=case, T=T)

    # --------------------------------------------------------
    # Step 1: Global search
    # --------------------------------------------------------
    if verbose:
        print("Step 1: Global search (differential evolution)...")

    de_result = differential_evolution(
        obj,
        bounds      = bounds,
        maxiter     = 200,
        tol         = 1e-6,
        seed        = 42,
        disp        = verbose,
        workers     = 1,        # set to -1 for parallel if available
        popsize     = 10,
    )

    theta_global = de_result.x
    fval_global  = de_result.fun

    if verbose:
        print(f"\nGlobal search result:")
        print(f"  w_bar_ratio = {theta_global[0]:.4f}")
        print(f"  theta_ltv   = {theta_global[1]:.4f}")
        print(f"  h_W         = {theta_global[2]:.4f}")
        print(f"  Objective   = {fval_global:.6f}")

    # --------------------------------------------------------
    # Step 2: Local refinement from multiple starting points
    # --------------------------------------------------------
    if verbose:
        print(f"\nStep 2: Local refinement ({n_starts} starting points)...")

    # Starting points: global optimum + random perturbations
    rng = np.random.default_rng(seed=123)

    starting_points = [theta_global]
    for _ in range(n_starts - 1):
        perturb = rng.uniform(-0.1, 0.1, size=3)
        start   = np.clip(
            theta_global + perturb,
            [b[0] for b in bounds],
            [b[1] for b in bounds]
        )
        starting_points.append(start)

    best_result = None
    best_fval   = np.inf

    for i, theta_0 in enumerate(starting_points):
        try:
            res = minimize(
                obj,
                x0      = theta_0,
                method  = method,
                bounds  = bounds,
                options = {
                    'maxiter': 1000,
                    'ftol':    1e-10,
                    'gtol':    1e-8,
                    'disp':    False,
                }
            )
            if res.fun < best_fval:
                best_fval   = res.fun
                best_result = res
                if verbose:
                    print(f"  Start {i+1}: fval = {res.fun:.6f}  "
                          f"[new best]  "
                          f"converged = {res.success}")
            else:
                if verbose:
                    print(f"  Start {i+1}: fval = {res.fun:.6f}  "
                          f"converged = {res.success}")
        except Exception as e:
            if verbose:
                print(f"  Start {i+1}: failed ({e})")

    theta_hat = best_result.x

    # --------------------------------------------------------
    # Report results
    # --------------------------------------------------------
    if verbose:
        print(f"\n{'='*60}")
        print(f"FINAL ESTIMATES")
        print(f"{'='*60}")
        print(f"  w_bar_ratio (w_bar/w_ss) = {theta_hat[0]:.4f}")
        print(f"  theta_ltv                = {theta_hat[1]:.4f}")
        print(f"  h_W                      = {theta_hat[2]:.4f}")
        print(f"  Objective value          = {best_fval:.8f}")
        print(f"  Converged                = {best_result.success}")
        print(f"\nUpdate steady_state.py with:")
        print(f"  p['w_bar']     = {theta_hat[0]:.4f}")
        print(f"  p['theta_ltv'] = {theta_hat[1]:.4f}")
        print(f"  p['h_W']       = {theta_hat[2]:.4f}")
        print(f"{'='*60}\n")

    # Model moments at optimum
    m_model = get_model_moments(theta_hat, H=H, case=case, T=T)

    return {
        'theta_hat'  : theta_hat,
        'w_bar'      : theta_hat[0],
        'theta_ltv'  : theta_hat[1],
        'h_W'        : theta_hat[2],
        'fval'       : best_fval,
        'm_hat'      : m_hat,
        'm_model'    : m_model,
    }


# ----------------------------------------------------------------
# 5. Plot fit
# ----------------------------------------------------------------

def plot_fit(result, H=12, case=1, save=True):
    """
    Plots empirical LP moments against model-implied IRFs.

    Parameters
    ----------
    result : dict — output from run_estimation()
    H      : int  — number of horizons
    case   : int  — WH2M case
    save   : bool — save figure to PDF
    """

    m_hat   = result['m_hat']
    m_model = result['m_model']
    horizons = np.arange(H + 1)

    # Split moment vector
    delta_PH2M_R_hat   = m_hat[:H+1]   * 100   # convert to %
    delta_WH2M_R_hat   = m_hat[H+1:]   * 100
    delta_PH2M_R_model = m_model[:H+1] * 100
    delta_WH2M_R_model = m_model[H+1:] * 100

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(
        f'Minimum Distance Fit — Case {case}\n'
        f'$\\bar{{w}}/w$ = {result["w_bar"]:.3f}, '
        f'$\\theta$ = {result["theta_ltv"]:.3f}, '
        f'$\\bar{{h}}_W$ = {result["h_W"]:.3f}',
        fontsize=12
    )

    # PH2M/Ricardian
    ax = axes[0]
    ax.plot(horizons, delta_PH2M_R_hat,   'b-o',  linewidth=2,
            label='Empirical LP', markersize=5)
    ax.plot(horizons, delta_PH2M_R_model, 'r--s', linewidth=2,
            label='Model', markersize=5)
    ax.axhline(0, color='k', linewidth=0.8, linestyle=':')
    ax.set_title('PH2M / Ricardian\nRelative Consumption Response')
    ax.set_xlabel('Quarters after shock')
    ax.set_ylabel('% deviation')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # WH2M/Ricardian
    ax = axes[1]
    ax.plot(horizons, delta_WH2M_R_hat,   'b-o',  linewidth=2,
            label='Empirical LP', markersize=5)
    ax.plot(horizons, delta_WH2M_R_model, 'r--s', linewidth=2,
            label='Model', markersize=5)
    ax.axhline(0, color='k', linewidth=0.8, linestyle=':')
    ax.set_title('WH2M / Ricardian\nRelative Consumption Response')
    ax.set_xlabel('Quarters after shock')
    ax.set_ylabel('% deviation')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    if save:
        fname = f'estimation_fit_case{case}.pdf'
        plt.savefig(fname, dpi=150, bbox_inches='tight')
        print(f"Fit plot saved to {fname}")

    plt.show()
    plt.close()


# ----------------------------------------------------------------
# 6. Sensitivity analysis
# ----------------------------------------------------------------

def sensitivity_analysis(result, H=12, case=1, T=300):
    """
    Checks how sensitive the estimated parameters are by
    re-estimating with perturbed empirical moments.

    Useful for checking identification strength.

    Parameters
    ----------
    result : dict — baseline estimation result
    H      : int
    case   : int
    T      : int
    """

    print(f"\n{'='*60}")
    print("Sensitivity Analysis")
    print(f"{'='*60}")

    theta_base = result['theta_hat']
    m_hat, W_mat = get_empirical_moments(H=H)

    # Perturb moments by +/- 10% and re-estimate
    perturbations = {
        'PH2M moments +10%':  np.concatenate([m_hat[:H+1]*1.10, m_hat[H+1:]]),
        'PH2M moments -10%':  np.concatenate([m_hat[:H+1]*0.90, m_hat[H+1:]]),
        'WH2M moments +10%':  np.concatenate([m_hat[:H+1], m_hat[H+1:]*1.10]),
        'WH2M moments -10%':  np.concatenate([m_hat[:H+1], m_hat[H+1:]*0.90]),
    }

    print(f"\n{'Perturbation':<25} {'w_bar':>8} {'theta_ltv':>12} {'h_W':>8}")
    print(f"{'Baseline':<25} {theta_base[0]:>8.4f} {theta_base[1]:>12.4f} "
          f"{theta_base[2]:>8.4f}")
    print("-" * 55)

    for name, m_perturbed in perturbations.items():
        obj = lambda theta: (
            (m_perturbed - get_model_moments(theta, H=H, case=case, T=T))
            @ W_mat
            @ (m_perturbed - get_model_moments(theta, H=H, case=case, T=T))
        )
        bounds = [(0.30, 0.95), (0.10, 0.90), (0.50, 3.00)]
        try:
            res = minimize(obj, x0=theta_base, method='L-BFGS-B',
                           bounds=bounds,
                           options={'maxiter': 500, 'ftol': 1e-8})
            print(f"{name:<25} {res.x[0]:>8.4f} {res.x[1]:>12.4f} "
                  f"{res.x[2]:>8.4f}")
        except Exception:
            print(f"{name:<25} {'FAILED':>8}")

    print(f"{'='*60}\n")


# ----------------------------------------------------------------
# 7. Main
# ----------------------------------------------------------------

if __name__ == '__main__':

    # --------------------------------------------------------
    # Step 1: Fill in your empirical moments in
    #         get_empirical_moments() above before running
    # --------------------------------------------------------

    # Run estimation for both cases
    for case in [1, 2]:

        print(f"\nRunning estimation for Case {case}...")

        result = run_estimation(
            case     = case,
            H        = 12,      # match 12 quarters
            T        = 300,     # Jacobian periods
            n_starts = 5,       # local refinement starting points
            verbose  = True,
        )

        # Plot fit
        plot_fit(result, H=12, case=case, save=True)

        # Sensitivity analysis
        sensitivity_analysis(result, H=12, case=case, T=300)

    print("\nEstimation complete.")
    print("Update p['w_bar'], p['theta_ltv'], p['h_W'] in")
    print("steady_state.py and rerun model.py for final IRFs.")
