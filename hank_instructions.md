MPC Estimation and HANK Implementation for Brazil
From POF/PNADC data processing to solving the model in Python (SSJ) and Julia (EconPizza / custom), with state-level validation
The binding constraint: Brazil has no individual-level consumption panel. POF gives detailed expenditure as a repeated cross-section (~every 7 years). PNADC gives monthly income but zero consumption. Two strategies: (A) estimate MPCs from POF cross-sectional variation, or (B) exploit state-level variation in HtM shares interacted with your MP shocks at monthly frequency. The monthly PNADC is a major advantage — it gives you higher-frequency income dynamics and aligns naturally with monthly PMC retail sales and your MP shock series.
01 Two MPC Estimation Strategies
Strategy A
Cross-sectional income elasticities from POF (Palomo, Carvalho & Toneto 2022)
The only published MPC estimates for Brazil use exactly the data you have. The method: regress household consumption on income within POF, by income group, controlling for demographics. The income elasticity of consumption, scaled by the consumption-to-income ratio, gives you an approximate MPC.

MPC_g ≈ ε_g × (C̄_g / Ȳ_g)
where ε_g = ∂ln(C)/∂ln(Y) for income group g
Their estimates from POF 2017-18: Bottom 50%: 0.61, Middle 40%: 0.62, Next 9%: 0.48, Top 1%: 0.04 (not statistically different from zero). These map directly onto your three HANK agent types.

Limitation: This is a cross-sectional MPC — it captures how consumption varies with income across households, not how a given household adjusts consumption to an income shock. It conflates permanent and transitory income differences. For HANK calibration this is standard practice (KMV 2018 do the same with SCF/CEX), but worth flagging.

Strategy B
State-level panel: MP shocks × regional HtM exposure
This is where your identified MP shock series has real power. The idea (following Cloyne et al. 2020, Mendonça & Anjos 2026): states with higher HtM shares should respond more to monetary policy shocks. You estimate a state-level panel regression:

ΔC_{s,t} = α_s + γ_t + β₁ · MP_shock_t + β₂ · (MP_shock_t × HtM_share_s) + X'_{s,t}δ + ε_{s,t}
β₂ is your object of interest: the differential consumption response per unit of HtM concentration. Combined with a model, this pins down the MPC gap between constrained and unconstrained agents.

Advantage: Causally identified (exogenous MP shocks), exploits time variation, works with state-level consumption proxies. Limitation: Requires state-level consumption data (see below) and strong instrument relevance.

02 Complete Variable List by Source
A. From POF (cross-section, calibration)
Variable	POF File	Purpose
Household consumption expenditure	despesa_coletiva, despesa_individual	MPC estimation (Strategy A)
Household income (all sources)	rendimentos	Income distribution, MPC by group
Financial assets + liabilities	inventario, outras_despesas	Liquid wealth → HtM classification; NNP for Fisher channel
Illiquid assets (housing, vehicles)	inventario, despesas_veiculos	WH2M vs PH2M split
Demographics (age, education, race, UF)	morador	Controls + demographic bins for PNADC mapping
B. From PNADC (monthly, time-series dynamics)
Variable	Purpose
Labor income (VD4020 effective earnings)	Income process (ρ, σ²) + state-level aggregation
Employment status + formality	Extensive margin, income risk calibration
Demographics (age, education, sex, UF)	Demographic bins for POF→PNADC mapping
Panel identifier (rotating panel)	Within-person income transitions for AR(1)
With monthly PNADC you get higher-frequency income transitions than the quarterly rotation scheme alone. This means more precise AR(1) estimates and — critically — monthly state-level employment/income aggregates that align with your monthly PMC and MP shock series.

C. State-level data (monthly panel for Strategy B)
Variable	Source	Purpose
Retail sales index (PMC)	IBGE (monthly, by UF)	Consumption proxy (outcome variable)
HtM share by UF	Your POF classification	Key interaction variable
Employment by UF	PNADC monthly aggregation	Labor market channel control
Credit operations by UF	BCB / SGS	Credit channel control
IPCA by metro area	IBGE	Deflator for real retail sales
Five variables. PMC and HtM share are essential; the rest are controls. Housing prices, Bolsa Família, and industrial production can be added as robustness checks but aren't needed for the baseline specification.

D. Aggregate / MP shock data
Variable	Source	Purpose
Identified MP shock series	Your dataset	Exogenous monetary policy variation (monthly)
SELIC target rate	BCB	Taylor rule calibration
IPCA (headline)	IBGE	Inflation for Phillips curve + Fisher channel
Exchange rate, IBOVESPA, M1, and Focus expectations are useful for extensions (open-economy HANK, asset price channel) but not needed for the baseline closed-economy model.

03 Auclert Sufficient Statistics from POF
You can compute all three redistribution channels directly from POF microdata, without solving the full HANK. Each is a covariance between MPCs and an exposure measure:

POF-computable
The three sufficient statistics
Channel	Statistic	POF Variables Needed
Earnings heterogeneity	Cov(MPCi, dYi/dY)	MPC by income group (from Strategy A) + income elasticity to aggregate income (proxy from sector of employment × aggregate sector-level PNADC data)
Fisher channel	Cov(MPCi, NNPi)	MPC by group + Net Nominal Position: financial assets − financial liabilities, from inventario + outras_despesas
Interest rate exposure	Cov(MPCi, UREi)	MPC by group + Unhedged Interest Rate Exposure: maturing assets − maturing liabilities − income + consumption. Requires maturity structure of debt (hard in POF — proxy with total debt stock)
If all three covariances are positive (high-MPC agents are net debtors with procyclical income), MP redistribution amplifies the aggregate effect. The Palomo et al. estimates strongly suggest this for Brazil: top-1% MPCs are near zero while bottom-50% MPCs exceed 0.6.

04 Full Pipeline: POF → Model → Validation
The three-phase plan
Phase 1 — Calibrate from POF (cross-section)

Classify agents into PH2M / WH2M / Ricardian using KVW (2014) thresholds on liquid and illiquid wealth ← your imHANKingit pipeline
Estimate MPCs by group via income elasticities of consumption (Strategy A)
Compute Auclert sufficient statistics (NNP, URE by group)
Estimate income process parameters (ρ, σ²) from PNADC monthly rotating panel, by demographic bin
↓
Phase 2 — Solve the model

Feed calibrated targets into either analytical HANK (Bilbiie) or SSJ
Match steady-state wealth distribution, HtM shares, MPC distribution
Compute IRFs to a SELIC shock via sequence-space Jacobians or Dynare
Decompose into direct (intertemporal substitution) vs indirect (GE income) channels
↓
Phase 3 — Validate with state-level panel (Strategy B)

Build state × month panel: PMC retail sales as ΔC, your MP shock series, POF-derived HtM shares by UF
Estimate differential state-level consumption response to MP shocks by HtM concentration
Compare implied aggregate MPC from the regression with model-implied MPC
If they align, you have external validation. If they diverge, the gap tells you what the model misses.
Key insight
Why the state-level approach works despite no individual consumption data
You don't need individual consumption to test HANK predictions. The core testable implication is that regions with more hand-to-mouth agents should respond more to aggregate monetary shocks. POF gives you the cross-sectional HtM distribution by state. Your MP shock series gives you the time-series variation. PMC (retail sales by state) gives you the consumption outcome. The interaction of these three — in a standard Bartik/shift-share design — identifies the causal mechanism without any individual consumption panel.

05 Implementation: Phase 1 — Data Processing (Python/R)
Python
1a. Load and classify agents from POF microdata
Read the fixed-width POF files, compute liquid wealth, illiquid wealth, and classify each household into PH2M / WH2M / Ricardian using the Kaplan-Violante-Weidner (2014) paycheck threshold.

Python
import pandas as pd
import numpy as np

# Load POF microdata (pre-converted to parquet)
morador = pd.read_parquet("pof2017/morador.parquet")
rend    = pd.read_parquet("pof2017/rendimentos.parquet")
desp_i  = pd.read_parquet("pof2017/despesa_individual.parquet")
invent  = pd.read_parquet("pof2017/inventario.parquet")

# Aggregate to household level
hh_income = rend.groupby("COD_UPA")["VALOR_ANUAL_EXPANDIDO2"].sum()
hh_consumption = desp_i.groupby("COD_UPA")["VALOR_ANUAL_EXPANDIDO2"].sum()

# Liquid wealth: financial assets - short-term liabilities
# Illiquid wealth: housing + vehicles + retirement accounts
liquid_w  = compute_liquid_wealth(invent)     # your imHANKingit function
illiquid_w = compute_illiquid_wealth(invent)

# KVW classification: HtM if liquid wealth < half a paycheck
monthly_income = hh_income / 12
paycheck_threshold = monthly_income / 2

hh = pd.DataFrame({
    "income": hh_income, "consumption": hh_consumption,
    "liquid": liquid_w, "illiquid": illiquid_w
})

hh["agent_type"] = np.where(
    hh["liquid"] < paycheck_threshold,
    np.where(hh["illiquid"] > 0, "WH2M", "PH2M"),
    "Ricardian"
)
Python
1b. Estimate MPCs by income group (Strategy A)
Regress log consumption on log income within income groups, weighted by survey weights. The income elasticity times the C/Y ratio gives the MPC.

Python
import statsmodels.api as sm

# Define income groups (Palomo et al. 2022 cutoffs)
hh["pctile"] = hh["income"].rank(pct=True)
hh["group"] = pd.cut(hh["pctile"],
    bins=[0, 0.50, 0.90, 0.99, 1.0],
    labels=["Bottom50", "Middle40", "Next9", "Top1"])

mpc_by_group = {}
for g, df in hh.groupby("group"):
    mask = (df["income"] > 0) & (df["consumption"] > 0)
    y = np.log(df.loc[mask, "consumption"])
    X = sm.add_constant(np.log(df.loc[mask, "income"]))

    model = sm.WLS(y, X, weights=df.loc[mask, "peso_final"]).fit()
    elasticity = model.params[1]

    # MPC = elasticity × (mean C / mean Y)
    c_over_y = df.loc[mask, "consumption"].mean() / df.loc[mask, "income"].mean()
    mpc_by_group[g] = elasticity * c_over_y

# Expected output ≈ {Bottom50: 0.61, Middle40: 0.62, Next9: 0.48, Top1: 0.04}
Python
1c. Estimate income process from monthly PNADC
With monthly PNADC you can estimate the AR(1) at monthly frequency, then convert to quarterly for the model. The rotating panel gives you consecutive monthly income observations for the same individual.

Python
# Load monthly PNADC (linked across months using household + person IDs)
pnadc = pd.read_parquet("pnadc_monthly_linked.parquet")

# Keep employed, positive earnings, ages 25-60
df = pnadc.query("VD4020 > 0 and V2009 >= 25 and V2009 <= 60").copy()
df["log_y"] = np.log(df["VD4020"])  # effective earnings

# Residualize: remove age, education, month FE
controls = pd.get_dummies(df[["V2009", "VD3004", "month"]], drop_first=True)
resid_model = sm.OLS(df["log_y"], sm.add_constant(controls)).fit()
df["log_y_resid"] = resid_model.resid

# AR(1) at monthly frequency: y_t = ρ_m * y_{t-1} + ε_t
panel = df.sort_values(["person_id", "month"])
panel["log_y_lag"] = panel.groupby("person_id")["log_y_resid"].shift(1)
panel = panel.dropna(subset=["log_y_lag"])

ar1 = sm.OLS(panel["log_y_resid"], sm.add_constant(panel["log_y_lag"])).fit()
rho_monthly = ar1.params[1]
sigma_eps_monthly = np.sqrt(ar1.mse_resid)

# Convert to quarterly for model: ρ_q = ρ_m^3, σ_q ≈ σ_m * sqrt((1+ρ+ρ²))
rho = rho_monthly ** 3
sigma_eps = sigma_eps_monthly * np.sqrt(1 + rho_monthly + rho_monthly**2)
06 Implementation: Phase 2 — Solve the HANK Model
SSJ · Python
2a. Sequence-Space Jacobian — the Python workhorse
The sequence_space_jacobian package by Auclert, Bardóczy, Rognlie & Straub is the standard tool. You define blocks (household, firm, government, monetary authority), compute Jacobians from steady state, then assemble the GE system.

Python · SSJ
import sequence_space_jacobian as ssj

# ─── Define the household block ───
# Endogenous grid method on (a, z) grid
def household_ss(r, w, beta, gamma, rho_z, sigma_z, amin, nA, nZ):
    """Solve HH problem in steady state, return policy + distribution."""
    # Discretize income process (Rouwenhorst)
    z_grid, Pi = ssj.grids.markov_rouwenhorst(rho_z, sigma_z, nZ)
    a_grid = ssj.grids.asset_grid(amin, 200, nA)  # max assets, n points

    # Backward iteration (EGM)
    Va = (1 + r) * (0.1 * a_grid[np.newaxis,:] + w * z_grid[:,np.newaxis]) ** (-gamma)

    for _ in range(5000):
        Va_old = Va.copy()
        # Expected marginal value
        EVa = Pi @ Va
        # FOC: c = (beta * (1+r) * EVa) ^ (-1/gamma)
        c_endog = (beta * (1+r) * EVa) ** (-1/gamma)
        # Endogenous grid for assets
        a_endog = (c_endog + a_grid[np.newaxis,:] - w * z_grid[:,np.newaxis]) / (1+r)
        # Interpolate back to fixed grid
        c, a_prime = ssj.grids.interpolate_policy(a_endog, c_endog, a_grid, amin)
        Va = (1 + r) * c ** (-gamma)
        if np.max(np.abs(Va - Va_old)) < 1e-10: break

    # Forward iteration for distribution D
    D = ssj.grids.forward_iterate(a_prime, Pi, a_grid, nA, nZ)

    # Aggregates
    C = np.sum(D * c)
    A = np.sum(D * a_prime)
    return {"C": C, "A": A, "c": c, "a_prime": a_prime, "D": D}

# ─── Calibrate to match Brazil POF targets ───
ss = household_ss(
    r=0.01,         # quarterly real rate (SELIC - IPCA, annualized/4)
    w=1.0,          # normalize
    beta=0.986,     # discount factor (search to match A/Y)
    gamma=2.0,      # CRRA
    rho_z=rho,      # from PNADC AR(1)  ← Phase 1c
    sigma_z=sigma_eps,
    amin=0.0,       # borrowing limit (set to 0 or calibrate)
    nA=200, nZ=7
)
SSJ · Python
2b. Compute Jacobians and GE impulse responses
The key step: compute how aggregate consumption responds to perturbations in r, w, and transfers at each future date. Then close the model with a Phillips curve, Taylor rule, and fiscal rule to get the IRF to a SELIC shock.

Python · SSJ
# ─── Compute Jacobians of household block ───
T = 300  # horizon for IRFs

# J_r[t,s] = ∂C_t / ∂r_s (how C at t responds to r shock at s)
J = ssj.get_H_U(
    block_list=[household_block, firm_block, mp_block, fiscal_block],
    unknowns=["r", "w", "Y"],
    targets=["asset_mkt", "labor_mkt", "goods_mkt"],
    T=T, ss=ss
)

# ─── Define the MP shock ───
# Taylor rule: r_t = r* + φ_π·π_t + φ_y·y_t + ε_t
# Shock: 25bp surprise increase in SELIC
dr = np.zeros(T)
dr[0] = 0.0025  # 25bp quarterly

# ─── Solve for GE impulse responses ───
irf = ssj.impulse_linear(
    block_list, unknowns, targets,
    ss, {"r": dr}, T
)

# irf["C"]  → aggregate consumption IRF
# irf["Y"]  → output IRF
# irf["r"]  → interest rate path
Julia
2c. Alternative: solve in Julia with custom EGM
Julia is faster for the inner loop (EGM backward iteration). Use QuantEcon.jl for Markov chain discretization and write the EGM directly. For GE, either port the SSJ logic or use the lightweight EconPDEs.jl for continuous-time.

Julia
using QuantEcon, LinearAlgebra, Interpolations

# Discretize income process (Rouwenhorst)
mc = rouwenhorst(7, rho, sigma_eps)
z_grid = mc.state_values
Pi = mc.p

# Asset grid
a_min, a_max, nA = 0.0, 200.0, 200
a_grid = range(a_min, a_max, length=nA) .^ 2 ./ a_max  # denser near 0

# EGM backward iteration
function solve_hh(r, w, β, γ, a_grid, z_grid, Pi; tol=1e-10, maxiter=5000)
    nA, nZ = length(a_grid), length(z_grid)

    # Initial guess for marginal value
    Va = [(1+r) * (0.1*a_grid[ia] + w*z_grid[iz])^(-γ)
          for iz in 1:nZ, ia in 1:nA]

    c_pol = similar(Va)
    a_pol = similar(Va)

    for iter in 1:maxiter
        EVa = Pi * Va  # nZ × nA

        for iz in 1:nZ
            # FOC: c = (β(1+r) EVa)^(-1/γ)
            c_endog = (β * (1+r) .* EVa[iz,:]) .^ (-1/γ)
            # Endogenous asset grid
            a_endog = (c_endog .+ a_grid .- w*z_grid[iz]) ./ (1+r)

            # Interpolate back to fixed grid
            itp = linear_interpolation(a_endog, c_endog, extrapolation_bc=Flat())
            for ia in 1:nA
                c_pol[iz, ia] = max(itp(a_grid[ia]), 1e-10)
                a_pol[iz, ia] = max((1+r)*a_grid[ia] + w*z_grid[iz] - c_pol[iz,ia], a_min)
            end
        end

        Va_new = (1+r) .* c_pol .^ (-γ)
        if maximum(abs.(Va_new .- Va)) < tol
            println("Converged in $iter iterations")
            break
        end
        Va .= Va_new
    end
    return c_pol, a_pol
end

c_ss, a_ss = solve_hh(0.01, 1.0, 0.986, 2.0, a_grid, z_grid, Pi)
07 Implementation: Phase 3 — State-Level Validation (Python/R)
Python
3a. Build the state × month panel and estimate
With monthly PNADC + monthly PMC + monthly MP shocks, you can run this at monthly frequency — no need to aggregate to quarters. This triples your time-series observations.

Python
import linearmodels.panel as lp

# ─── Assemble monthly panel ───
pmc = pd.read_csv("ibge_pmc_retail_by_uf.csv")   # state × month retail index
shocks = pd.read_csv("mp_shocks_brazil.csv")      # your identified MP shocks (monthly)
htm = pd.read_csv("htm_shares_by_uf.csv")         # from imHANKingit / POF

# Log difference → ΔC proxy
pmc = pmc.sort_values(["uf", "month"])
pmc["dlog_retail"] = pmc.groupby("uf")["retail_index"].transform(
    lambda x: np.log(x).diff()
)

# Merge
panel = pmc.merge(shocks, on="month").merge(htm, on="uf")
panel["shock_x_htm"] = panel["mp_shock"] * panel["htm_share"]

# ─── Estimate with state + month FE ───
panel = panel.set_index(["uf", "month"])
mod = lp.PanelOLS(
    panel["dlog_retail"],
    panel[["shock_x_htm"]],  # mp_shock level absorbed by time FE
    entity_effects=True,       # state FE (α_s)
    time_effects=True,         # month FE (γ_t)
)
res = mod.fit(cov_type="clustered", cluster_entity=True)
print(res.summary)

# β on shock_x_htm: if negative → states with more HtM
# contract more after a rate hike. This validates HANK.
Note: With month FE, the level of mp_shock is absorbed — you only need the interaction. Cluster SEs at the state level. For local projections at multiple horizons h, run this regression for ΔCs,t+h for h = 0, 1, ..., 24 months.

08 Package and Tooling Summary
Task	Python	Julia	R (alternative)
POF/PNADC data wrangling	pandas, pyarrow	DataFrames.jl	survey, PNADcIBGE
MPC estimation (OLS/WLS)	statsmodels	GLM.jl	fixest
Income process (AR1)	statsmodels	QuantEcon.jl	plm
Markov chain discretization	sequence_space_jacobian	QuantEcon.jl	—
Household problem (EGM)	sequence_space_jacobian	Custom (above) or EconPDEs.jl	—
GE Jacobians + IRFs	sequence_space_jacobian	Port SSJ logic or EconPizza.jl	—
State panel regression	linearmodels	FixedEffectModels.jl	fixest
Local projections (IRFs)	linearmodels in a loop	FixedEffectModels.jl	lpirfs
SVAR with external instrument	statsmodels / custom	VARs.jl	vars
Recommendation for your project
Python for the HANK model — the SSJ package is mature, documented, and exactly designed for this. No reason to rewrite it.

R or Python for the data pipeline — R has the PNADcIBGE package that reads PNADC microdata directly from IBGE FTP. Python requires pre-conversion to parquet.

Julia if you need speed — the EGM inner loop runs 5-10x faster in Julia. Worth it only if you're doing estimation (re-solving the model hundreds of times). For a single calibration exercise, Python is fine.

R/Python for the state-level validation — fixest (R) is fastest for high-dimensional FE regressions. linearmodels (Python) works too. This is the empirical contribution — keep it in whatever you're most fluent in.

Key references: Palomo, Carvalho & Toneto, "MPC Heterogeneity and Redistributive Policies: The Brazilian Case," Made/USP WP 10, 2022. Auclert, "Monetary Policy and the Redistribution Channel," AER 2019. Auclert, Bardóczy, Rognlie & Straub, "Using the Sequence-Space Jacobian," Econometrica 2021. Mendonça & Anjos, "Household Consumption Intentions by Income Group During MP Easing and Tightening," IJFE 2026. Aragon, Medeiros, Mendes & Abreu, "Measuring MP Shocks in Brazil," Empirical Economics 2026. Kaplan, Violante & Weidner, "The Wealthy Hand-to-Mouth," BPEA 2014. Bilbiie, "The New Keynesian Cross," JME 2020.

Code sources: SSJ package: pip install sequence-space-jacobian (Auclert et al.). QuantEcon.jl: Pkg.add("QuantEcon"). PNADcIBGE: install.packages("PNADcIBGE"). Palomo et al. (2022) replication: Made/USP WP 10.
Made with Dia
