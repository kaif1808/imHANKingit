from __future__ import annotations

from sequence_jacobian import create_model, simple


UNKNOWNS = [
    "cR",
    "cW",
    "cP",
    "Y",
    "X",
    "pi",
    "R",
    "r",
    "bW",
    "hW",
    "q",
    "A",
    "j",
    "u",
    "TP",
    "dP",
    "dW",
]

TARGETS = [
    "y_res",
    "cR_euler_res",
    "cW_budget_res",
    "cP_res",
    "w_housing_res",
    "r_housing_res",
    "collateral_res",
    "production_res",
    "nkpc_res",
    "taylor_res",
    "real_rate_res",
    "A_res",
    "j_res",
    "u_res",
    "TP_res",
    "dP_res",
    "dW_res",
]

EXOGENOUS_SHOCKS = ["e_R", "e_R_neg", "e_A", "e_j", "e_u", "e_T"]

REPORT_OUTPUTS = [
    "Y",
    "cR",
    "cW",
    "cP",
    "pi",
    "R",
    "r",
    "X",
    "q",
    "hW",
    "bW",
    "A",
    "j",
    "u",
    "TP",
    "dP",
    "dW",
]


@simple
def thrank_linear_system(
    cR,
    cW,
    cP,
    Y,
    X,
    pi,
    R,
    r,
    bW,
    hW,
    q,
    A,
    j,
    u,
    TP,
    dP,
    dW,
    e_R,
    e_R_neg,
    e_A,
    e_j,
    e_u,
    e_T,
    beta_R,
    beta_W,
    beta_w,
    eta,
    phi,
    m_ltv,
    iota,
    kappa,
    r_R,
    r_pi,
    r_Y,
    rho_A,
    rho_j,
    rho_u,
    rho_T,
    alpha_R,
    alpha_W,
    alpha_P,
    alphaW_over_X,
    cR_share,
    cW_share,
    cP_share,
    bW_share,
    qhW_share,
    omega_labor_cP,
    omega_transfer_cP,
    formal_income_pass_through,
    R_bar,
    rho_dP,
    rho_dW,
    chi_dP_y,
    chi_dW_y,
    chi_dP_r,
    chi_dW_r,
    chi_dP_tp,
    chi_dW_tp,
    chi_R_neg,
):
    """Linearized THRANK system from `thrank_model.md` Section 6."""

    y_res = Y - (cR_share * cR + cW_share * cW + cP_share * cP)

    cR_euler_res = cR - cR(+1) + r

    cW_budget_res = cW_share * cW - (
        bW_share * bW
        - qhW_share * (hW - hW(-1))
        - R_bar * bW_share * (R(-1) + bW(-1) - pi)
        + alphaW_over_X * (Y - X)
    )

    cP_res = cP - (omega_labor_cP * (Y - X) + omega_transfer_cP * TP)

    w_housing_res = q + phi * (hW - hW(-1)) - (
        beta_w * q(+1)
        + (1.0 - beta_w) * (j - hW)
        - (1.0 - m_ltv) * beta_W * cW(+1)
        + (1.0 - m_ltv * beta_R) * cW
        - m_ltv * beta_R * r
        + beta_W * phi * (hW(+1) - hW)
    )

    r_housing_res = q + phi * iota * (hW(-1) - hW) - (
        beta_R * q(+1)
        + (1.0 - beta_R) * j
        + (1.0 - beta_R) * iota * hW
        + cR
        - beta_R * cR(+1)
        + beta_R * phi * iota * (hW - hW(+1))
    )

    collateral_res = bW - q(+1) - hW + r

    production_res = Y - (
        (eta * A - X - alpha_R * cR - alpha_W * cW - alpha_P * formal_income_pass_through * cP)
        / (eta - 1.0)
    )

    nkpc_res = pi - beta_R * pi(+1) + kappa * X - u

    taylor_res = R - (
        r_R * R(-1)
        + (1.0 - r_R) * ((1.0 + r_pi) * pi(-1) + r_Y * Y(-1))
        + e_R
        - chi_R_neg * e_R_neg
    )

    real_rate_res = r - (R - pi(+1))

    A_res = A - (rho_A * A(-1) + e_A)
    j_res = j - (rho_j * j(-1) + e_j)
    u_res = u - (rho_u * u(-1) + e_u)
    TP_res = TP - (rho_T * TP(-1) + e_T)

    # Reduced-form deposit observables to map model states to net-liquid LP outcomes.
    dP_res = dP - (rho_dP * dP(-1) + chi_dP_y * (Y - X) + chi_dP_r * r + chi_dP_tp * TP)
    dW_res = dW - (rho_dW * dW(-1) + chi_dW_y * (Y - X) + chi_dW_r * r + chi_dW_tp * TP)

    return y_res, cR_euler_res, cW_budget_res, cP_res, w_housing_res, r_housing_res, collateral_res, production_res, nkpc_res, taylor_res, real_rate_res, A_res, j_res, u_res, TP_res, dP_res, dW_res


def build_model():
    model = create_model([thrank_linear_system], name="THRANK-BR Linear SSJ")
    return model, UNKNOWNS, TARGETS, EXOGENOUS_SHOCKS, REPORT_OUTPUTS
