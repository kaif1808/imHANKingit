/****************************************************************************************
  NK_WANK_IRFs_pedagogical.mod

  Purpose:
  - A THREE-AGENT New Keynesian model extending the TANK framework to distinguish
    between POOR hand-to-mouth (PHtM), WEALTHY hand-to-mouth (WHtM), and
    RICARDIAN households, following Kaplan, Moll & Violante (2018) and
    Bilbiie (2020).
  - Computes and PLOTS impulse response functions (IRFs) in Dynare.
  - Focuses on ONE shock at a time (monetary policy, technology, preference).
  - After each experiment, a custom MATLAB figure overlays c_R, c_WHtM and
    c_PHtM on a single panel for easy comparison.

  Household types:
  -----------------------------------------------------------------------
  (1) RICARDIAN  (share: 1 - lambda_P - lambda_W)
      - Hold liquid AND illiquid assets.
      - Smooth consumption via the standard Euler equation.

  (2) WEALTHY HtM  (share: lambda_W)
      - Hold illiquid assets (housing, retirement accounts) but NO liquid assets.
      - Cannot smooth consumption period-to-period => consume current labor income,
        just like Poor HtM.
      - Key difference from PHtM: they receive ASSET INCOME (dividends / capital
        income) in addition to labor income, so their consumption is more sensitive
        to asset-price/dividend movements.
      - In a linearized model without explicit asset prices, we model this by
        making WHtM consumption respond to output gap PLUS a dividend/wealth
        premium term proxied by the natural rate gap.

  (3) POOR HtM  (share: lambda_P)
      - Hold NO assets (liquid or illiquid).
      - Consume exactly their current labor income: c_PHtM = y_gap.
      - Most sensitive to labor-market conditions; zero buffer stock.

  Identification:
  - 13 endogenous variables, 13 equations  =>  exactly identified.

  How to run (in MATLAB/Octave, with Dynare in the path):
      dynare NK_WANK_IRFs_pedagogical.mod

  Variable list:
    pi        - aggregate inflation
    y_gap     - aggregate output gap
    i         - nominal interest rate
    r_nat     - natural real interest rate
    c_R       - Ricardian consumption gap
    c_WHtM    - Wealthy HtM consumption gap
    c_PHtM    - Poor HtM consumption gap
    c         - aggregate consumption gap
    w_premium - wealth/dividend premium for WHtM (AR(1) auxiliary state)
    nu        - monetary policy shock  (AR(1))
    a         - technology shock       (AR(1))
    z         - preference shock       (AR(1))
    r_gap     - real rate gap: (i - pi(+1) - r_nat), auxiliary definition

  Shocks (i.i.d. innovations):
    eps_nu    - monetary policy shock innovation
    eps_a     - technology shock innovation
    eps_z     - preference shock innovation

  Parameters:
    betta          - discount factor
    siggma         - inverse IES
    varphi         - inverse Frisch elasticity
    phi_pi         - Taylor rule: inflation
    phi_y          - Taylor rule: output gap
    theta          - Calvo stickiness
    rho_nu         - persistence: monetary shock
    rho_a          - persistence: technology shock
    rho_z          - persistence: preference shock
    alppha         - capital share
    epsilon        - demand elasticity
    lambda_P       - share of Poor HtM households      [NEW vs TANK]
    lambda_W       - share of Wealthy HtM households   [NEW vs TANK]
    xi             - WHtM sensitivity to wealth premium (>0)
    rho_wp         - persistence of wealth premium process

  References:
  - Kaplan, G., Moll, B., & Violante, G. L. (2018). "Monetary Policy According
    to HANK." American Economic Review.
  - Bilbiie, F. O. (2020). "The New Keynesian Cross." Journal of Monetary Economics.
  - Galí, J. (2015). Monetary Policy, Inflation, and the Business Cycle, 2nd ed.
  - Galí, J., López-Salido, D., & Vallés, J. (2004). JMCB.

****************************************************************************************/


/*** 1) DECLARE ENDOGENOUS VARIABLES
     13 variables  =>  need exactly 13 equations in model block. ***/
var
    pi          // aggregate inflation
    y_gap       // aggregate output gap
    i           // nominal interest rate
    r_nat       // natural real interest rate
    c_R         // Ricardian consumption gap
    c_WHtM      // Wealthy HtM consumption gap
    c_PHtM      // Poor HtM consumption gap
    c           // aggregate consumption gap
    w_premium   // wealth/dividend premium process for WHtM  (AR(1))
    r_gap       // real rate gap: i - pi(+1) - r_nat  (auxiliary definition)
    nu          // monetary policy shock (AR(1) state)
    a           // technology shock     (AR(1) state)
    z           // preference shock     (AR(1) state)
;


/*** 2) DECLARE EXOGENOUS SHOCK INNOVATIONS ***/
varexo
    eps_nu      // innovation to monetary policy shock
    eps_a       // innovation to technology shock
    eps_z       // innovation to preference shock
;


/*** 3) DECLARE PARAMETERS ***/
parameters
    betta siggma varphi phi_pi phi_y theta
    rho_nu rho_a rho_z
    alppha epsilon
    lambda_P        // [3-AGENT] share of Poor HtM
    lambda_W        // [3-AGENT] share of Wealthy HtM
    xi              // [3-AGENT] WHtM wealth-premium sensitivity
    rho_wp          // [3-AGENT] persistence of wealth premium
;


/*** 4) CALIBRATION
     Shares follow Kaplan, Moll & Violante (2018) US estimates:
       ~30% Poor HtM, ~20% Wealthy HtM, ~50% Ricardian.
     All other parameters as in Galí (2015). ***/
siggma   = 1;         // inverse IES
varphi   = 5;         // inverse Frisch elasticity
phi_pi   = 1.5;       // Taylor rule: inflation coefficient
phi_y    = 0.125;     // Taylor rule: output gap coefficient
theta    = 3/4;       // Calvo price-stickiness
rho_nu   = 0.5;       // persistence: monetary policy shock
rho_a    = 0.9;       // persistence: technology shock
rho_z    = 0.5;       // persistence: preference shock
betta    = 0.99;      // discount factor
alppha   = 1/4;       // capital share in production
epsilon  = 9;         // elasticity of substitution across goods
lambda_P = 0.30;      // share of Poor HtM  (KMV 2018 US estimate)
lambda_W = 0.20;      // share of Wealthy HtM (KMV 2018 US estimate)
                      // => Ricardian share = 1 - 0.30 - 0.20 = 0.50
xi       = 0.25;      // WHtM sensitivity to wealth premium
                      //   > 0: WHtM consumption rises when asset income rises
                      //   Set to 0 to collapse WHtM => PHtM behaviour
rho_wp   = 0.70;      // persistence of wealth premium (illiquid assets slow to move)


/*** 5) MODEL BLOCK — LINEARIZED EQUILIBRIUM CONDITIONS
     model(linear): already in log-linear form around the steady state.
     Leads: x(+1)   Lags: x(-1)
     Total: 13 equations for 13 endogenous variables (exactly identified). ***/
model(linear);

    /***** Composite parameters (identical derivation to Galí 2015 Ch. 3) *****/
    #Omega    = (1-alppha)/(1-alppha+alppha*epsilon);
    #psi_n_ya = (1+varphi)/(siggma*(1-alppha)+varphi+alppha);
    #lambda_w_calvo = (1-theta)*(1-betta*theta)/theta*Omega;
    #kappa    = lambda_w_calvo*(siggma+(varphi+alppha)/(1-alppha));  // NKPC slope
    #lambda_R = 1 - lambda_P - lambda_W;                             // Ricardian share

    // -----------------------------------------------------------------------
    // [EQ 1] New Keynesian Phillips Curve
    // Unchanged: firm pricing is independent of household heterogeneity.
    // -----------------------------------------------------------------------
    pi = betta*pi(+1) + kappa*y_gap;

    // -----------------------------------------------------------------------
    // [EQ 2] Ricardian Euler equation
    // Ricardians smooth consumption: respond to the real rate gap r_gap.
    // -----------------------------------------------------------------------
    c_R = c_R(+1) - (1/siggma)*r_gap;

    // -----------------------------------------------------------------------
    // [EQ 3] Poor HtM consumption
    // No assets of any kind: consume current labor income only.
    // Their consumption gap = output gap (labor income proportional to output).
    // -----------------------------------------------------------------------
    c_PHtM = y_gap;

    // -----------------------------------------------------------------------
    // [EQ 4] Wealthy HtM consumption
    // Hold illiquid assets but no liquid assets => cannot smooth in short run.
    // Consume labor income PLUS a wealth/dividend premium term:
    //   c_WHtM = y_gap + xi * w_premium
    // When w_premium > 0 (asset values rise), WHtM can draw down illiquid
    // wealth slightly (e.g., via housing equity); parameter xi governs this.
    // Setting xi = 0 makes WHtM identical to PHtM.
    // -----------------------------------------------------------------------
    c_WHtM = y_gap + xi*w_premium;

    // -----------------------------------------------------------------------
    // [EQ 5] Aggregate consumption aggregator   [KEY 3-AGENT equation]
    // Weighted average over the three household types.
    // -----------------------------------------------------------------------
    c = lambda_R*c_R + lambda_W*c_WHtM + lambda_P*c_PHtM;

    // -----------------------------------------------------------------------
    // [EQ 6] Aggregate demand / market clearing
    // Closed economy, no investment or government: y_gap = c.
    // -----------------------------------------------------------------------
    y_gap = c;

    // -----------------------------------------------------------------------
    // [EQ 7] Monetary policy rule (Taylor rule)
    // -----------------------------------------------------------------------
    i = phi_pi*pi + phi_y*y_gap + nu;

    // -----------------------------------------------------------------------
    // [EQ 8] Natural real interest rate
    // -----------------------------------------------------------------------
    r_nat = -siggma*psi_n_ya*(1-rho_a)*a + (1-rho_z)*z;

    // -----------------------------------------------------------------------
    // [EQ 9] Auxiliary: real rate gap definition
    // Separating this out keeps EQ 2 clean and avoids forward-variable clutter.
    // r_gap = i - pi(+1) - r_nat
    // -----------------------------------------------------------------------
    r_gap = i - pi(+1) - r_nat;

    // -----------------------------------------------------------------------
    // [EQ 10] Wealth premium process (AR(1))
    // Driven by the real rate gap: a tighter monetary policy depresses
    // asset values, reducing the wealth premium available to WHtM households.
    // -----------------------------------------------------------------------
    
w_premium = rho_wp*w_premium(-1) - r_gap;

    // -----------------------------------------------------------------------
    // [EQ 11] Monetary policy shock (AR(1))
    // -----------------------------------------------------------------------
    nu = rho_nu*nu(-1) + eps_nu;

    // -----------------------------------------------------------------------
    // [EQ 12] Technology shock (AR(1))
    // -----------------------------------------------------------------------
    a = rho_a*a(-1) + eps_a;

    // -----------------------------------------------------------------------
    // [EQ 13] Preference / demand shock (AR(1))
    // -----------------------------------------------------------------------
z = rho_z*z(-1) + eps_z;

end;


/*** 6) COMPUTE IRFs: ONE SHOCK AT A TIME
     Workflow (identical to TANK file):
     A) Set the active shock's std dev > 0; set all others to 0.
     B) stoch_simul(order=1, irf=20) computes and plots standard Dynare IRFs.
     C) After each stoch_simul, a custom MATLAB figure overlays c_R, c_WHtM
        and c_PHtM on a SINGLE panel (the extra comparison graph requested).

     oo_.irfs fields used in the overlay plots (auto-named by Dynare):
       oo_.irfs.c_R_eps_nu     oo_.irfs.c_WHtM_eps_nu     oo_.irfs.c_PHtM_eps_nu
       oo_.irfs.c_R_eps_a      oo_.irfs.c_WHtM_eps_a      oo_.irfs.c_PHtM_eps_a
       oo_.irfs.c_R_eps_z      oo_.irfs.c_WHtM_eps_z      oo_.irfs.c_PHtM_eps_z
***/


/* =============================================================================
   EXPERIMENT 1: MONETARY POLICY SHOCK (eps_nu)
   Surprise increase in the policy rate (~25 bps quarterly).

   3-AGENT PREDICTION:
   - Ricardians (c_R): smooth the shock; modest, gradual contraction.
   - Wealthy HtM (c_WHtM): cannot smooth, AND face a negative wealth premium
     (asset values fall with higher rates) => deepest consumption contraction.
   - Poor HtM (c_PHtM): cannot smooth, but no asset-income channel =>
     intermediate contraction, driven purely by the output/labor income fall.
============================================================================= */
shocks;
    var eps_nu; stderr 0.0025;   // ON:  monetary shock (~25 bps)
    var eps_a;  stderr 0;        // OFF: technology shock
    var eps_z;  stderr 0;        // OFF: preference shock
end;

stoch_simul(order=1, irf=20)
    pi y_gap i r_nat c c_R c_WHtM c_PHtM w_premium;

/* --- Custom overlay: consumption IRF for all three types (Shock 1) --- */
figure('Name','Consumption IRFs — Monetary Policy Shock','NumberTitle','off');
horizon = (1:20)';

irf_cR    = oo_.irfs.c_R_eps_nu(:);
irf_cW    = oo_.irfs.c_WHtM_eps_nu(:);
irf_cP    = oo_.irfs.c_PHtM_eps_nu(:);

plot(horizon, irf_cR,    'b-',  'LineWidth', 2); hold on;
plot(horizon, irf_cW,    'r--', 'LineWidth', 2);
plot(horizon, irf_cP,    'k:',  'LineWidth', 2);
yline(0, 'Color', [0.5 0.5 0.5], 'LineStyle', '-', 'LineWidth', 0.8);

legend('Ricardian (c\_R)', 'Wealthy HtM (c\_WHtM)', 'Poor HtM (c\_PHtM)', ...
       'Location', 'SouthEast');
xlabel('Quarters after shock');
ylabel('Deviation from steady state');
title({'Consumption IRFs: Monetary Policy Shock (eps\_nu)', ...
       sprintf('\\lambda_P=%.2f,  \\lambda_W=%.2f,  \\xi=%.2f', ...
               lambda_P, lambda_W, xi)});
grid on;
set(gca, 'FontSize', 11);


/* =============================================================================
   EXPERIMENT 2: TECHNOLOGY (TFP) SHOCK (eps_a)
   Positive productivity improvement (1%).

   3-AGENT PREDICTION:
   - Ricardians (c_R): gradual increase, smoother than HtM types.
   - Wealthy HtM (c_WHtM): sharp immediate consumption rise (labor income
     channel) PLUS a positive wealth premium (higher productivity raises
     asset values) => largest short-run consumption boom.
   - Poor HtM (c_PHtM): immediate rise tracking labor income only,
     no asset-income amplification; less than WHtM but more front-loaded
     than Ricardian.
============================================================================= */
shocks;
    var eps_nu; stderr 0;        // OFF: monetary shock
    var eps_a;  stderr 0.01;     // ON:  technology shock (1%)
    var eps_z;  stderr 0;        // OFF: preference shock
end;

stoch_simul(order=1, irf=20)
    pi y_gap i r_nat a c c_R c_WHtM c_PHtM w_premium;

/* --- Custom overlay: consumption IRF for all three types (Shock 2) --- */
figure('Name','Consumption IRFs — Technology Shock','NumberTitle','off');
horizon = (1:20)';

irf_cR    = oo_.irfs.c_R_eps_a(:);
irf_cW    = oo_.irfs.c_WHtM_eps_a(:);
irf_cP    = oo_.irfs.c_PHtM_eps_a(:);

plot(horizon, irf_cR,    'b-',  'LineWidth', 2); hold on;
plot(horizon, irf_cW,    'r--', 'LineWidth', 2);
plot(horizon, irf_cP,    'k:',  'LineWidth', 2);
yline(0, 'Color', [0.5 0.5 0.5], 'LineStyle', '-', 'LineWidth', 0.8);

legend('Ricardian (c\_R)', 'Wealthy HtM (c\_WHtM)', 'Poor HtM (c\_PHtM)', ...
       'Location', 'SouthEast');
xlabel('Quarters after shock');
ylabel('Deviation from steady state');
title({'Consumption IRFs: Technology Shock (eps\_a)', ...
       sprintf('\\lambda_P=%.2f,  \\lambda_W=%.2f,  \\xi=%.2f', ...
               lambda_P, lambda_W, xi)});
grid on;
set(gca, 'FontSize', 11);


/* =============================================================================
   EXPERIMENT 3: PREFERENCE / DEMAND SHOCK (eps_z)
   Positive shift in desired spending / demand (1%).

   3-AGENT PREDICTION:
   - Ricardians (c_R): modest expansion, partially offset by higher real rates.
   - Wealthy HtM (c_WHtM): larger initial expansion (higher labor income)
     further amplified by positive wealth premium from the demand boom.
   - Poor HtM (c_PHtM): expansion proportional to output gap only,
     no wealth-premium channel; larger than Ricardian but smaller than WHtM.
============================================================================= */
shocks;
    var eps_nu; stderr 0;        // OFF: monetary shock
    var eps_a;  stderr 0;        // OFF: technology shock
    var eps_z;  stderr 0.01;     // ON:  preference shock (1%)
end;

stoch_simul(order=1, irf=20)
    pi y_gap i r_nat z c c_R c_WHtM c_PHtM w_premium;

/* --- Custom overlay: consumption IRF for all three types (Shock 3) --- */
figure('Name','Consumption IRFs — Preference Shock','NumberTitle','off');
horizon = (1:20)';

irf_cR    = oo_.irfs.c_R_eps_z(:);
irf_cW    = oo_.irfs.c_WHtM_eps_z(:);
irf_cP    = oo_.irfs.c_PHtM_eps_z(:);

plot(horizon, irf_cR,    'b-',  'LineWidth', 2); hold on;
plot(horizon, irf_cW,    'r--', 'LineWidth', 2);
plot(horizon, irf_cP,    'k:',  'LineWidth', 2);
yline(0, 'Color', [0.5 0.5 0.5], 'LineStyle', '-', 'LineWidth', 0.8);

legend('Ricardian (c\_R)', 'Wealthy HtM (c\_WHtM)', 'Poor HtM (c\_PHtM)', ...
       'Location', 'SouthEast');
xlabel('Quarters after shock');
ylabel('Deviation from steady state');
title({'Consumption IRFs: Preference/Demand Shock (eps\_z)', ...
       sprintf('\\lambda_P=%.2f,  \\lambda_W=%.2f,  \\xi=%.2f', ...
               lambda_P, lambda_W, xi)});
grid on;
set(gca, 'FontSize', 11);


/****************************************************************************************
  VARIABLE COUNT CHECK (must be exactly identified):
    Endogenous vars : pi, y_gap, i, r_nat, c_R, c_WHtM, c_PHtM, c,
                      w_premium, r_gap, nu, a, z              => 13 variables
    Equations       : EQ1–EQ13 in model block                 => 13 equations  ✓

  NESTING / SPECIAL CASES:
    lambda_W = 0, xi = 0  =>  collapses to TANK (PHtM + Ricardian only)
    lambda_W = 0, lambda_P = 0  =>  collapses to RA-NK (Galí 2015 Ch. 3)
    xi = 0  =>  WHtM behaves identically to PHtM

  IRF STORAGE (oo_.irfs auto-naming convention):
    oo_.irfs.c_R_eps_nu      oo_.irfs.c_WHtM_eps_nu     oo_.irfs.c_PHtM_eps_nu
    oo_.irfs.c_R_eps_a       oo_.irfs.c_WHtM_eps_a      oo_.irfs.c_PHtM_eps_a
    oo_.irfs.c_R_eps_z       oo_.irfs.c_WHtM_eps_z      oo_.irfs.c_PHtM_eps_z
    oo_.irfs.y_gap_eps_nu    oo_.irfs.pi_eps_nu          etc.

  REFERENCES:
  - Kaplan, G., Moll, B., & Violante, G. L. (2018). "Monetary Policy According
    to HANK." American Economic Review, 108(3), 697–743.
  - Bilbiie, F. O. (2020). "The New Keynesian Cross." Journal of Monetary Economics.
  - Galí, J. (2015). Monetary Policy, Inflation, and the Business Cycle, 2nd ed.
  - Galí, J., López-Salido, D., & Vallés, J. (2004). JMCB.
  - Campbell, J. Y., & Mankiw, N. G. (1989). NBER Macroeconomics Annual.
****************************************************************************************/
