"""
validate.py
-----------
Continuous run-and-validate harness for the amaani_thrank SSJ model.

Runs both cases end-to-end (steady state -> Jacobian -> IRFs), asserts the
SSJ steady-state residuals are ~0, the system is square, and IRFs are finite
with the expected contractionary-MP signs. Exits non-zero on any failure so
it can be wired into CI or a pre-run check.

Note on sign test: uses rho_m=0 (pure surprise shock) to isolate the direct
impact response. With rho_m>0, AR(1) anticipation effects in the forward-looking
Euler equations can flip the sign of ii on impact (forward-guidance puzzle).
The direct J[0,0] for ii is always positive for a well-specified model.

Usage:
    python validate.py
"""
import sys
import numpy as np

from steady_state import get_parameters, compute_steady_state, verify_steady_state, print_steady_state
from model import compute_irfs


def validate_case(case):
    print(f"\n{'#'*60}\n# VALIDATING CASE {case}\n{'#'*60}")
    ss = compute_steady_state(get_parameters(case=case))
    print_steady_state(ss)

    ok = verify_steady_state(ss)
    if not ok:
        print(f"[FAIL] steady-state checks failed (case {case})")
        return False

    for key in ['ii_ss', 'Y_ss', 'chi_R', 'chi_W']:
        if key not in ss:
            print(f"[FAIL] missing ss key {key} (case {case})")
            return False

    # Pure-surprise shock for sign test (see module docstring)
    irfs = compute_irfs(ss, T=300, shock_size=ss['sigma_m'], rho_m=0.0)

    for key in ['Y', 'pi', 'ii', 'C_R', 'C_W', 'C_P']:
        if key not in irfs or not np.all(np.isfinite(irfs[key])):
            print(f"[FAIL] IRF {key} missing or non-finite (case {case})")
            return False

    checks = {
        'Y falls on impact':  irfs['Y'][0] < 0,
        'pi falls on impact': irfs['pi'][0] < 0,
        'ii rises on impact': irfs['ii'][0] > 0,
    }
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    if not all(checks.values()):
        return False

    print(f"\n[OK] Case {case} validated. "
          f"Y(0)={irfs['Y'][0]*100:.3f}%, pi(0)={irfs['pi'][0]*100:.3f}%, "
          f"ii(0)={irfs['ii'][0]*100:.3f}pp")
    return True


def main():
    results = {case: validate_case(case) for case in (1, 2)}
    print(f"\n{'='*60}")
    for case, ok in results.items():
        print(f"  Case {case}: {'PASS' if ok else 'FAIL'}")
    print(f"{'='*60}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == '__main__':
    main()
