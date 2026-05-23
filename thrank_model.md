# THRANK-BR: Three-Agent Heterogeneous New Keynesian Model — Brazil

A DSGE model with three representative agent types — Ricardian (non-HtM), Wealthy Hand-to-Mouth (WHtM), and Poor Hand-to-Mouth (PHtM) — adapted for the Brazilian economy. The theoretical structure follows Eskelinen (2021), which itself draws on Iacoviello (2005) and Rubio (2011) for the housing/credit block, and Galí–López-Salido–Vallés (2007) for the rule-of-thumb block.

**Brazil-specific departures from Eskelinen (2021):**
1. PHtM budget constraint includes a Bolsa Família (conditional cash transfer) income term, modelled as exogenous to monetary policy.
2. Informality (formal/informal/self-employed labour split) is a first-order feature, not an optional extension. It applies to the PHtM block and is identified directly from PNADC labour status data.
3. Self-employed workers (*conta própria*) are treated as a distinct PHtM sub-type with a flexible income equation.
4. Labour shares (α_R, α_W, α_P) and agent-type shares are calibrated from the POF 2017/18 and PNADC-C pipeline outputs, not from Kaplan–Violante–Weidner (2014) US estimates.
5. Agent-type shares are **time-varying at state×month level** in the data. The model is solved at national steady-state shares but the empirical strategy exploits cross-state variation.
6. Housing collateral channel is only directly identified for 15 of 27 UFs (states with housing price indices). See §12.

**Setting that reduces to Eskelinen (2021):** Set `σ_i = 0` (no informal labour), `σ_k = 0` (no self-employment), `T_t^P = 0` (no transfers), use US calibration values.

---

## 0. Notation

### 0.1 Agent indices

| Index | Type | Key feature | Brazil mapping |
|---|---|---|---|
| `R` | Ricardian | Patient saver, owns firms, holds housing and bonds | Formal workers, high-income, positive liquid assets |
| `W` | Wealthy HtM | Collateral-constrained borrower, holds housing | Mortgaged homeowners with near-zero liquid assets |
| `P` | Poor HtM | No financial assets, lives on current income | Informal workers, self-employed, Bolsa Família recipients |

**Classification rule in the data (POF 2017/18, §8.2):**
- PHtM: liquid assets < 0.5 × monthly income **and** per-capita income < BRL 170/month
- WHtM: liquid assets < 0.5 × monthly income **and** illiquid assets ≥ 3 × monthly income
- Ricardian: otherwise

### 0.2 Endogenous variables

| Symbol | Description |
|---|---|
| `c_t^R, c_t^W, c_t^P` | Consumption by agent type |
| `h_t^R, h_t^W` | Housing stock (PHtM hold none) |
| `b_t^R, b_t^W` | Real bond (debt) positions; `b^W > 0` is debt, `b^R < 0` is savings |
| `L_t^R, L_t^W` | Labour supply (Ricardian, WHtM — both assumed formal sector) |
| `L_{f,t}^P` | PHtM formal-sector labour hours |
| `L_{i,t}^P` | PHtM informal-sector labour hours |
| `L_{k,t}^P` | PHtM self-employed (*conta própria*) hours |
| `w_t^R, w_t^W, w_{f,t}^P` | Formal-sector real wages by type |
| `w̄_{i,t}^P` | Informal-sector real wage (partially exogenous; see §3.3) |
| `w̄_{k,t}^P` | Self-employment real income rate (partially exogenous) |
| `q_t` | Real house price index |
| `Y_t` | Final-goods output |
| `X_t` | Gross markup of intermediate price over marginal cost |
| `Π_t` | Gross inflation rate `P_t / P_{t-1}` |
| `R_t` | Gross nominal interest rate (SELIC-equivalent) |
| `F_t` | Real profits paid to Ricardians |
| `μ_t` | Lagrange multiplier on WHtM collateral constraint |

### 0.3 Exogenous variables and shocks

| Symbol | Description | Data source |
|---|---|---|
| `A_t` | TFP (AR(1)) | Structural residual |
| `j_t` | Housing preference shifter (AR(1)) | Structural residual |
| `u_t` | Cost-push / inflation shock | Structural residual |
| `e_{R,t}` | Monetary policy shock | DI futures surprise (`mp_shock_monthly`), see §10 |
| `T_t^P` | Per-PHtM-household Bolsa Família transfer (real BRL) | State × month bolsa família receipts |
| `w̄_{i,t}^P` | Informal sector real wage | PNADC informal earnings (partially exogenous) |
| `w̄_{k,t}^P` | Self-employment real income | PNADC *conta própria* earnings (partially exogenous) |

### 0.4 Parameters

| Symbol | Description | Brazil note |
|---|---|---|
| `β_R, β_W` | Discount factors with `β_R > β_W` | Standard calibration, Brazilian context may warrant lower β_W given high-yield informal savings alternatives |
| `η` | Inverse Frisch elasticity (labour disutility exponent) | Calibrate from Brazilian labour supply elasticity estimates |
| `α_R, α_W, α_P` | Labour shares in formal production (`α_R + α_W + α_P = 1`) | Estimated from POF income tables; see §8 |
| `s_i` | Share of PHtM hours in informal sector | From PNADC `informal_share` conditional on PHtM |
| `s_k` | Share of PHtM hours in self-employment | From PNADC `conta_propria_share` conditional on PHtM |
| `ε` | CES substitution elasticity between varieties | Standard |
| `θ` | Calvo non-reset probability | May be lower for Brazil (more flexible prices) |
| `m` | Maximum LTV ratio | ~0.60–0.80 (Brazil mortgage market is less leveraged than US) |
| `φ` | Housing adjustment cost | Calibrate; Brazil's housing market has high transaction costs |
| `r_R, r_π, r_Y` | Taylor rule coefficients | Calibrate from COPOM reaction function |
| `H` | Aggregate fixed housing supply | Normalised |
| `ψ_T` | Sensitivity of Bolsa Família transfer to aggregate state (≈ 0 by design) | Near zero — PBF is set by federal government |

### 0.5 Empirical agent-share notation (state × month level)

| Symbol | Data column | Description |
|---|---|---|
| `λ_{R,s,t}` | `share_Ricardian` | Ricardian share, state s, period t |
| `λ_{W,s,t}` | `share_WH2M` | WHtM share |
| `λ_{P,s,t}` | `share_PH2M` | PHtM share |
| `f_{s,t}` | `formal_share` | Formal employment share among employed |
| `n_{s,t}` | `informal_share` | Informal employment share |
| `k_{s,t}` | `conta_propria_share` | Self-employment share |

---

## 1. Households

### 1.1 Non-HtM (Ricardian)

**Preferences:**
$$
\mathbb{E}_0 \sum_{t=0}^{\infty} \beta_R^{\,t}
\left[\ln c_t^R + j_t \ln h_t^R - \frac{(L_t^R)^{\eta}}{\eta}\right]
\tag{R.1}
$$

**Budget constraint** (with housing adjustment cost `φ`):
$$
c_t^R + q_t(h_t^R - h_{t-1}^R) + \frac{R_{t-1} b_{t-1}^R}{\Pi_t} + \frac{\phi q_t}{2}\!\left(\frac{h_t^R - h_{t-1}^R}{h_{t-1}^R}\right)^{\!2}\! h_{t-1}^R
= b_t^R + w_t^R L_t^R + F_t
\tag{R.2}
$$

> **Sign convention.** Following Eskelinen (2021): `b_t^R` here is the *savings* position of Ricardians (positive = they are lenders). In the loan market clearing condition `b_t^R - b_t^W = 0`, `b_t^W` is WHtM *debt* (positive). Use this convention consistently throughout the code. It differs from the bond-holdings convention used in some papers where both positions have the same sign.

**FOC: Consumption Euler:**
$$
\frac{1}{c_t^R} = \beta_R\, \mathbb{E}_t \!\left[\frac{R_t}{\Pi_{t+1}\, c_{t+1}^R}\right]
\tag{R.3}
$$

**FOC: Labour supply:**
$$
w_t^R = (L_t^R)^{\eta-1} c_t^R
\tag{R.4}
$$

**FOC: Housing:**
$$
\frac{1}{c_t^R}\!\left[q_t + \phi q_t \!\left(\frac{h_t^R - h_{t-1}^R}{h_{t-1}^R}\right)\!\right]
= \frac{j_t}{h_t^R}
+ \frac{\beta_R}{\mathbb{E}_t c_{t+1}^R}\!\left[\mathbb{E}_t q_{t+1} + \frac{\phi}{2} \mathbb{E}_t q_{t+1} \frac{(\mathbb{E}_t h_{t+1}^R)^2 - (h_t^R)^2}{(h_t^R)^2}\right]
\tag{R.5}
$$

---

### 1.2 Wealthy HtM

**Preferences** (same form, lower discount factor `β_W < β_R`):
$$
\mathbb{E}_0 \sum_{t=0}^{\infty} \beta_W^{\,t}
\left[\ln c_t^W + j_t \ln h_t^W - \frac{(L_t^W)^{\eta}}{\eta}\right]
\tag{W.1}
$$

**Budget constraint:**
$$
c_t^W + q_t(h_t^W - h_{t-1}^W) + \frac{R_{t-1} b_{t-1}^W}{\Pi_t} + \frac{\phi q_t}{2}\!\left(\frac{h_t^W - h_{t-1}^W}{h_{t-1}^W}\right)^{\!2}\! h_{t-1}^W
= b_t^W + w_t^W L_t^W
\tag{W.2}
$$

**Collateral constraint** (binding in a neighbourhood of steady state when `β_W < β_R`):
$$
b_t^W \leq m\, \mathbb{E}_t\!\left[\frac{q_{t+1} h_t^W \Pi_{t+1}}{R_t}\right]
\tag{W.3}
$$

> **Brazil note on LTV.** The Brazilian mortgage market is structurally different from the US/Europe. CAIXA Econômica Federal dominates the mortgage market; typical LTVs for programmes like MCMV (*Minha Casa Minha Vida*) are 0.70–0.80. Private bank mortgages typically cap at 0.80. I am not certain what value is appropriate for `m` in Brazil — you should verify against BCB mortgage statistics. Using `m = 0.90` (Eskelinen's value) likely overstates Brazilian household leverage.

**FOC: Consumption Euler (with binding constraint multiplier `μ_t`):**
$$
\frac{1}{c_t^W} = \beta_W\, \mathbb{E}_t \!\left[\frac{R_t}{\Pi_{t+1}\, c_{t+1}^W}\right] + \mu_t R_t
\tag{W.4}
$$

**FOC: Labour supply:**
$$
w_t^W = (L_t^W)^{\eta-1} c_t^W
\tag{W.5}
$$

**FOC: Housing (with collateral value term):**
$$
\frac{1}{c_t^W}\!\left[q_t + \phi q_t \!\left(\frac{h_t^W - h_{t-1}^W}{h_{t-1}^W}\right)\!\right]
= \frac{j_t}{h_t^W}
+ \frac{\beta_W}{\mathbb{E}_t c_{t+1}^W}\!\left[\mathbb{E}_t q_{t+1} + \frac{\phi}{2} \mathbb{E}_t q_{t+1} \frac{(\mathbb{E}_t h_{t+1}^W)^2 - (h_t^W)^2}{(h_t^W)^2}\right]
+ \mu_t m\, \mathbb{E}_t [q_{t+1} \Pi_{t+1}]
\tag{W.6}
$$

**Complementary slackness:** `μ_t ≥ 0`, and `μ_t · (m E_t[q_{t+1} h_t^W Π_{t+1}/R_t] − b_t^W) = 0`. Imposed with equality for log-linearised dynamics given `β_W < β_R`.

---

### 1.3 Poor HtM (Brazil specification)

PHtM households in Brazil have three distinct income sources: (i) formal-sector labour, (ii) informal-sector labour, (iii) self-employment, plus (iv) Bolsa Família conditional cash transfers. They hold no financial assets and cannot borrow.

**Preferences:**
$$
\mathbb{E}_0 \sum_{t=0}^{\infty} \beta_P^{\,t}
\left[\ln c_t^P - \frac{(L_{f,t}^P)^{\eta}}{\eta} - \frac{(L_{i,t}^P)^{\eta}}{\eta} - \frac{(L_{k,t}^P)^{\eta}}{\eta}\right]
\tag{P.1}
$$

`β_P` does not appear in any FOC because PHtM cannot intertemporally substitute. It may be set equal to `β_R` without loss for steady-state purposes.

**Budget constraint (Brazil):**
$$
c_t^P = w_{f,t}^P L_{f,t}^P + \bar w_{i,t}^P L_{i,t}^P + \bar w_{k,t}^P L_{k,t}^P + T_t^P
\tag{P.2}
$$

where `T_t^P` is the real Bolsa Família transfer received per PHtM household, discussed in §1.4 below.

**FOC: Formal labour (market-determined wage):**
$$
w_{f,t}^P = (L_{f,t}^P)^{\eta-1} c_t^P
\tag{P.3}
$$

**FOC: Informal labour (taking `w̄_{i,t}^P` as given):**
$$
\bar w_{i,t}^P = (L_{i,t}^P)^{\eta-1} c_t^P
\tag{P.4}
$$

**FOC: Self-employment (taking `w̄_{k,t}^P` as given):**
$$
\bar w_{k,t}^P = (L_{k,t}^P)^{\eta-1} c_t^P
\tag{P.5}
$$

**Relative labour allocation.** From ratios of (P.3)–(P.5):
$$
\frac{L_{f,t}^P}{L_{i,t}^P} = \left(\frac{w_{f,t}^P}{\bar w_{i,t}^P}\right)^{1/(\eta-1)}, \qquad
\frac{L_{f,t}^P}{L_{k,t}^P} = \left(\frac{w_{f,t}^P}{\bar w_{k,t}^P}\right)^{1/(\eta-1)}
\tag{P.6}
$$

> **Modelling choice note.** Equations (P.4) and (P.5) treat `w̄_{i,t}^P` and `w̄_{k,t}^P` as **parametric** to the household — the informal and self-employment wages are not fully set by household optimisation. In the Brazilian context this is motivated by: (a) the minimum wage partially anchors informal wages even off the books; (b) self-employment income depends on local demand conditions and own-account productivity, which is sector-specific. These wages are therefore **partially exogenous** — they respond to aggregate conditions with lower elasticity than formal wages. In the data, `informal_share` and `conta_propria_share` from PNADC measure the employment shares corresponding to these margins. You may want to verify this modelling assumption against the labour supply literature on Brazil; I am not certain whether the semi-exogeneity assumption is empirically well-supported.

**Aggregate PHtM labour supply hours (calibrated shares):**

At any period, let `s_f`, `s_i`, `s_k` be the shares of total PHtM labour income from formal, informal, and self-employment respectively, with `s_f + s_i + s_k = 1`. These are estimated from PNADC conditional on PHtM classification:
$$
s_f = \frac{w_{f,t}^P L_{f,t}^P}{w_{f,t}^P L_{f,t}^P + \bar w_{i,t}^P L_{i,t}^P + \bar w_{k,t}^P L_{k,t}^P}
\tag{P.7}
$$

In steady state with constant wages, (P.3)–(P.5) and (P.7) pin the hours allocation and all three labour market margins.

**Attenuation from informality.** When formal wages fall after a monetary contraction, PHtM can shift hours to informal/self-employment activity at the more rigid wages `w̄_i^P` and `w̄_k^P`. This attenuates the PHtM consumption response relative to an all-formal-worker specification. The degree of attenuation is governed by the elasticity in (P.6) and by the income share weights `s_i, s_k`.

---

### 1.4 Bolsa Família Transfer Block

Bolsa Família (Programa Bolsa Família, PBF) is Brazil's primary conditional cash transfer. For the model:

**Transfer rule:**
$$
T_t^P = \bar T^P + \psi_T(Y_t - Y) + \varepsilon_t^T
\tag{BF.1}
$$

where `T̄^P` is the steady-state real per-PHtM-household transfer, `ψ_T ≈ 0` captures any automatic stabiliser response (close to zero by policy design — the federal government sets PBF at a fixed nominal value updated discretely), and `ε_t^T` captures PBF expansion/reform shocks.

In the baseline model, treat `T_t^P` as **fully exogenous**: `ψ_T = 0` and the transfer is an AR(1) around its trend:
$$
\hat T_t^P = \rho_T \hat T_{t-1}^P + \varepsilon_t^T
\tag{BF.2}
$$

**Automatic stabiliser logic.** Because `ψ_T ≈ 0`, the transfer does not move with the monetary policy cycle. This means:
- A contractionary shock reduces `w_{f,t}^P` (via reduced labour demand), which *does* reduce PHtM income.
- But `T_t^P` remains roughly stable, providing a partial floor.
- The effective income elasticity of PHtM consumption to monetary policy is **lower** than in a model without transfers, especially for the extreme poor (whose income is most transfer-intensive).

> **Calibration.** The dataset contains state × month average Bolsa Família receipts. Compute `T̄^P` as the time-mean of per-PHtM-household real Bolsa Família receipts. The transfer income share of PHtM consumption, `T̄^P / c̄^P`, is a key calibration target — I expect it to be substantial (possibly 20–40% of PHtM consumption for the poorest group, though I am not certain without seeing the POF data). This directly affects how strongly PHtM consumption responds to monetary shocks.

---

## 2. Firms

### 2.1 Intermediate goods (monopolistic, Calvo prices)

**Production function** over formal labour from all three types:
$$
Y_t = A_t (L_t^R)^{\alpha_R} (L_t^W)^{\alpha_W} (L_{f,t}^P)^{\alpha_P}, \qquad \alpha_R + \alpha_W + \alpha_P = 1
\tag{F.1}
$$

> **Informality and firm production.** Only **formal** PHtM labour enters the firm production function. Informal-sector and self-employment output are separate activities that go directly into PHtM household income (see (P.2)). This avoids double-counting and keeps the firm block tractable. The aggregate formal employment share (`formal_share` in the PNADC data) provides an empirical check on the share of labour income flowing through the formal sector.

TFP process:
$$
\log A_t = \rho_A \log A_{t-1} + \varepsilon_t^A, \quad \varepsilon_t^A \sim \mathcal N(0, \sigma_A^2)
\tag{F.2}
$$

**Labour demand** (from cost minimisation; `X_t` is the gross markup):
$$
w_t^R = \frac{\alpha_R Y_t}{X_t L_t^R}, \qquad
w_t^W = \frac{\alpha_W Y_t}{X_t L_t^W}, \qquad
w_{f,t}^P = \frac{\alpha_P Y_t}{X_t L_{f,t}^P}
\tag{F.3}
$$

Profits paid to Ricardians:
$$
F_t = \left(1 - \frac{1}{X_t}\right) Y_t
\tag{F.4}
$$

### 2.2 Final goods (perfect competition, CES)

$$
Y_t = \left[\int_0^1 Y_t(z)^{(\varepsilon-1)/\varepsilon}\, dz\right]^{\varepsilon/(\varepsilon-1)}, \qquad
Y_t(z) = \left(\frac{P_t(z)}{P_t}\right)^{-\varepsilon} Y_t
\tag{F.5}
$$

Price index:
$$
P_t = \left[\int_0^1 P_t(z)^{1-\varepsilon} dz\right]^{1/(1-\varepsilon)}
\tag{F.6}
$$

### 2.3 Calvo pricing and NKPC

Each firm may reset its price with probability `1 − θ` per period. Optimal reset price `P_t^*` solves:
$$
\sum_{k=0}^{\infty} (\beta_R \theta)^{k}\, \mathbb{E}_t\!\left\{
\Lambda_{t,k} \left[\frac{P_t^*(z)}{P_{t+k}} - \frac{\varepsilon/(\varepsilon-1)}{X_{t+k}}\right] Y_{t+k}^*(z)
\right\} = 0
\tag{F.7}
$$

with stochastic discount factor `Λ_{t,k} = β_R · c_t^R / c_{t+k}^R`. Price-level recursion:
$$
P_t^{1-\varepsilon} = \theta P_{t-1}^{1-\varepsilon} + (1-\theta)(P_t^*)^{1-\varepsilon}
\tag{F.8}
$$

**Log-linearised NKPC:**
$$
\hat\pi_t = \beta_R\, \mathbb{E}_t \hat\pi_{t+1} - \kappa \hat X_t + \hat u_t, \qquad
\kappa \equiv \frac{(1-\theta)(1-\beta_R\theta)}{\theta}
\tag{F.9}
$$

> **Brazil note on price stickiness.** Brazilian inflation has historically been high and volatile, and there is evidence that price adjustment is faster than in advanced economies. A Calvo parameter of `θ = 0.75` (one reset per year on average) may be too high for Brazil. Some estimates for Brazil suggest `θ ∈ [0.50, 0.65]` (roughly consistent with prices changing every 5–8 months). I am not certain about the correct value — you should calibrate this from Brazilian micro price data or the existing DSGE literature on Brazil (e.g. Araújo et al., BCB Working Papers). Flag this as a sensitivity parameter.

---

## 3. Monetary policy

**COPOM / SELIC rule.** The Brazilian central bank (BCB) sets the SELIC overnight rate via the COPOM committee (meetings every ~45 days, 8 per year). The model maps `R_t` to the monthly SELIC-equivalent rate. The Taylor rule is:
$$
R_t = R_{t-1}^{r_R} \left[\Pi_{t-1}^{1+r_\pi} \left(\frac{Y_{t-1}}{Y}\right)^{\!r_Y}\!\! \bar r\right]^{1-r_R}\! e_{R,t}
\tag{M.1}
$$

**Monetary shock identification.** In the empirical specification, `e_{R,t}` is identified from the **DI futures surprise** (`mp_shock_monthly` in the data), constructed as high-frequency changes in DI (interbank deposit) futures contracts in a tight window around COPOM announcements. Positive `mp_shock_monthly` = contractionary surprise. This is the standard Brazilian HFID approach (see Cloyne–Ferreira–Surico 2020 for the analogous UK identification; for Brazil the methodology should be verified against the specific construction in your shock data file `shock_transformation_log.csv`).

> **Important calibration note.** The SELIC rate in Brazil operates at very different levels than in advanced economies (SELIC ranged from 6.5% to 14.75% during 2012–2018 in the PNADC sample period). The steady-state real interest rate `r̄ = 1/β_R − 1` implied by a standard `β_R = 0.99` is approximately 1% per quarter, or about 4% per year. This is far below typical Brazilian ex-ante real rates (often 5–10% per year during this period). You may need to either (a) recalibrate `β_R` downward significantly, or (b) explicitly model the spread between the policy rate and the household borrowing/savings rate. I do not have a verified Brazil-specific value for `β_R` and flag this as a key calibration uncertainty.

---

## 4. Market clearing

**Housing:**
$$
h_t^R + h_t^W = H
\tag{MC.1}
$$

**Goods market** (including housing adjustment cost terms):
$$
c_t^R + c_t^W + c_t^P + \frac{\phi q_t}{2}\!\left(\frac{h_t^R - h_{t-1}^R}{h_{t-1}^R}\right)^{\!2}\! h_{t-1}^R + \frac{\phi q_t}{2}\!\left(\frac{h_t^W - h_{t-1}^W}{h_{t-1}^W}\right)^{\!2}\! h_{t-1}^W = Y_t
\tag{MC.2}
$$

**Loan market:**
$$
b_t^R = b_t^W
\tag{MC.3}
$$

(Using the convention where `b^R` is Ricardian savings and `b^W` is WHtM debt.)

**Labour markets** (household supply = firm demand for each formal type; informal and self-employment markets clear at the respective wage schedules):
- Ricardian labour: `L_t^R` equates (R.4) and first equation of (F.3).
- WHtM labour: `L_t^W` equates (W.5) and second equation of (F.3).
- PHtM formal labour: `L_{f,t}^P` equates (P.3) and third equation of (F.3).
- PHtM informal and self-employment: hours determined residually by (P.4)–(P.5) given exogenous `w̄` wages.

**Government budget (Bolsa Família):** The federal government funds PBF via general taxation. The transfer `T_t^P` does not appear in the private-sector goods market clearing (the tax falls on Ricardians, reducing their disposable income). In a complete model, add a Ricardian tax `τ_t^R = λ_P T_t^P / λ_R` to the right-hand side of (R.2). **For the baseline model, treat `T_t^P` as purely exogenous and check that goods-market clearing (MC.2) holds after accounting for any government spending not consumed by households.**

---

## 5. Steady state

Set `Π̄ = 1`, `R̄ = 1/β_R`. Steady-state markup `X̄ = ε/(ε−1)`.

The Eskelinen (2021) steady-state share formulas carry over with the relabelling `α → α_R`, `γ → α_W`, `1−α−γ → α_P`:

$$
\frac{q h^W}{Y} = \frac{j}{1 - \beta_W - m(\beta_R - \beta_W - j(1 - \beta_R))}\,\frac{\alpha_W}{X}
\tag{SS.1}
$$

$$
\frac{b^W}{Y} = \frac{j \beta_R m}{1 - \beta_W - m(\beta_R - \beta_W - j(1 - \beta_R))}\,\frac{\alpha_W}{X}
\tag{SS.2}
$$

$$
\frac{c^W}{Y} = \frac{1 - \beta_W - m(\beta_R - \beta_W)}{1 - \beta_W - m(\beta_R - \beta_W - j(1 - \beta_R))}\,\frac{\alpha_W}{X}
\tag{SS.3}
$$

$$
\frac{c^R}{Y} = \frac{1}{X}\!\left[X + \alpha_R - 1 + \frac{\alpha_W j m(1-\beta_R)}{1 - \beta_W - m(\beta_R - \beta_W - j(1-\beta_R))}\right]
\tag{SS.4}
$$

**PHtM consumption share (Brazil, with transfer):**
$$
\frac{c^P}{Y} = \frac{\alpha_P}{X} + \frac{T^P \lambda_P}{Y}
\tag{SS.5}
$$

where `λ_P` is the PHtM population share and `T^P / Y` is the aggregate transfer-to-output ratio. The second term is new relative to Eskelinen and should be calibrated from the Bolsa Família data.

**Housing ownership share:**
$$
\frac{h^W}{H} = \frac{\alpha_W (1 - \beta_R)}{\alpha_W (1 - \beta_R)(1 + j m) + (X + \alpha_R - 1)\,[1 - \beta_W - m(\beta_R - \beta_W - j(1 - \beta_R))]}
\tag{SS.6}
$$

**Steady-state WHtM constraint multiplier:** `μ̄ = (1/c̄^W)(1 − β_W/β_R) > 0` whenever `β_W < β_R`. ✓

---

## 6. Log-linearised system

Hats denote percentage deviations from steady state. Define real interest rate `r̂_t ≡ R̂_t − E_t π̂_{t+1}`. Use `β_w ≡ m β_R + (1 − m) β_W` and `ι ≡ (h^W/H)/(1 − h^W/H)`.

**Aggregate output:**
$$
\hat Y_t = \frac{c^R}{Y} \hat c_t^R + \frac{c^W}{Y} \hat c_t^W + \frac{c^P}{Y} \hat c_t^P
\tag{L.1}
$$

**Ricardian Euler:**
$$
\hat c_t^R = \mathbb{E}_t \hat c_{t+1}^R - \hat r_t
\tag{L.2}
$$

**WHtM budget constraint:**
$$
\frac{c^W}{Y} \hat c_t^W = \frac{b^W}{Y} \hat b_t^W - \frac{qh^W}{Y}(\hat h_t^W - \hat h_{t-1}^W) - \frac{Rb^W}{Y}(\hat R_{t-1} + \hat b_{t-1}^W - \hat\pi_t) + \frac{\alpha_W}{X}(\hat Y_t - \hat X_t)
\tag{L.3}
$$

**PHtM consumption (with transfer):**
$$
\hat c_t^P = \left(\frac{\alpha_P / X}{c^P / Y}\right)(\hat Y_t - \hat X_t) + \left(\frac{T^P \lambda_P / Y}{c^P / Y}\right)\hat T_t^P
\tag{L.4}
$$

The first term is the labour-income channel; the second is the Bolsa Família channel. Both share weights sum to 1. At `T^P = 0`, (L.4) reduces to `ĉ_t^P = Ŷ_t − X̂_t` (Eskelinen's (35)).

> **Key result from (L.4).** A monetary contraction reduces `Ŷ_t − X̂_t` (labour income falls as output drops and markup rises). But if `T^P > 0` and `T̂_t^P ≈ 0` (transfer unchanged), the PHtM consumption response is *attenuated* relative to the Eskelinen baseline. The attenuation is proportional to the transfer income share `(T^P λ_P / Y) / (c^P / Y)`. This is a structural reason why Brazil's PHtM consumption may be less cyclically sensitive to monetary policy than a standard model would predict.

**WHtM housing demand:**
$$
\hat q_t + \phi(\hat h_t^W - \hat h_{t-1}^W)
= \beta_w \mathbb{E}_t \hat q_{t+1} + (1 - \beta_w)(\hat j_t - \hat h_t^W) - (1 - m)\beta_W \mathbb{E}_t \hat c_{t+1}^W + (1 - m\beta_R)\hat c_t^W - m\beta_R \hat r_t + \beta_W \phi(\mathbb{E}_t \hat h_{t+1}^W - \hat h_t^W)
\tag{L.5}
$$

**Ricardian housing demand** (using `ĥ_t^R = −ι ĥ_t^W` from (MC.1)):
$$
\hat q_t + \phi\iota(\hat h_{t-1}^W - \hat h_t^W) = \beta_R \mathbb{E}_t \hat q_{t+1} + (1-\beta_R)\hat j_t + (1-\beta_R)\iota \hat h_t^W + \hat c_t^R - \beta_R \mathbb{E}_t \hat c_{t+1}^R + \beta_R \phi\iota(\hat h_t^W - \mathbb{E}_t \hat h_{t+1}^W)
\tag{L.6}
$$

**Collateral constraint (binding):**
$$
\hat b_t^W = \mathbb{E}_t \hat q_{t+1} + \hat h_t^W - \hat r_t
\tag{L.7}
$$

**Production / labour-market block:**
$$
\hat Y_t = \frac{1}{\eta - 1}\left[\eta \hat A_t - \hat X_t - \alpha_R \hat c_t^R - \alpha_W \hat c_t^W - \alpha_P \hat c_{f,t}^P\right]
\tag{L.8}
$$

where `ĉ_{f,t}^P` is the log-deviation of formal-sector PHtM labour income `w_{f,t}^P L_{f,t}^P / c_t^P` from its steady state. In the baseline (no informality attenuation), `ĉ_{f,t}^P = ĉ_t^P`.

**NKPC:**
$$
\hat\pi_t = \beta_R \mathbb{E}_t \hat\pi_{t+1} - \kappa \hat X_t + \hat u_t, \quad \kappa = \frac{(1-\theta)(1-\beta_R\theta)}{\theta}
\tag{L.9}
$$

**Taylor rule:**
$$
\hat R_t = r_R \hat R_{t-1} + (1 - r_R)\!\left[(1 + r_\pi)\hat\pi_{t-1} + r_Y \hat Y_{t-1}\right] + \hat e_{R,t}
\tag{L.10}
$$

**Exogenous processes:**
$$
\hat A_t = \rho_A \hat A_{t-1} + \varepsilon_t^A, \quad
\hat j_t = \rho_j \hat j_{t-1} + \varepsilon_t^j, \quad
\hat u_t = \rho_u \hat u_{t-1} + \varepsilon_t^u, \quad
\hat T_t^P = \rho_T \hat T_{t-1}^P + \varepsilon_t^T
\tag{L.11}
$$

---

## 7. Key transmission channels in the Brazilian context

| Channel | Mechanism | Brazil-specific note |
|---|---|---|
| Intertemporal substitution | Ricardians smooth via Euler equation | Standard; attenuated if β_R needs recalibration |
| Labour income | Wage and employment fall reduce all types' income | Formal employment most affected; informal partially buffers PHtM |
| Collateral / housing | WHtM borrowing limit tightens as `q_t` falls | Housing index limited to 15 UFs; collateral channel partially unidentified |
| Debt deflation | Rising real debt burdens WHtM via nominal debt + falling Π_t | Present; magnitude depends on LTV calibration |
| Bolsa Família buffer | `T_t^P` approximately constant despite shock | Attenuates PHtM response; unique to Brazil, not in Eskelinen |
| Informality buffer | PHtM shifts hours to informal sector at rigid wages | Attenuates PHtM formal-wage exposure; calibrated from PNADC |
| Self-employment buffer | Shift to *conta própria* further insulates some PHtM | Same logic; `conta_propria_share` measures this in data |
| Redistribution (Auclert) | Resources flow from high-MPC (HtM) to low-MPC (Ricardian) | Present; amplified by high HtM shares in poorer states |

---

## 8. Calibration — Brazil

### 8.1 Strategy

Two-stage calibration:
1. **Stage 1 (structural):** Fix parameters from Brazilian macro data and literature. Use steady-state ratios from §5 to recover model-consistent values.
2. **Stage 2 (empirical match):** Use POF and PNADC pipeline outputs to pin agent-share parameters and transfer moments.

### 8.2 Agent shares (from POF 2017/18 pipeline)

Read from `results/tables/pof_group_wealth_income_summary.csv`. The shares below should be treated as **approximate targets to verify against the pipeline output** — I am not presenting them as ground truth since I have not seen the pipeline's actual output values.

| Parameter | Source column | Description |
|---|---|---|
| `λ_P` (national) | `share_PH2M` (diagnostic national average) | PHtM population share |
| `λ_W` (national) | `share_WH2M` (diagnostic national average) | WHtM population share |
| `λ_R` (national) | `share_Ricardian` (diagnostic national average) | Ricardian population share |

Read from `results/tables/monthly_htm_coverage.csv` for national time-averages of `national_share_PH2M`, `national_share_WH2M`, `national_share_Ricardian`.

### 8.3 Labour income shares (α_R, α_W, α_P)

Compute from `pof_group_wealth_income_summary.csv`:
$$
\alpha_k = \frac{\lambda_k \cdot \text{mean\_total\_labor\_income}_k}{\sum_{j \in \{R,W,P\}} \lambda_j \cdot \text{mean\_total\_labor\_income}_j}
$$

for `k ∈ {R, W, P}`. This directly uses the POF income data and should replace the KVW-derived US values.

### 8.4 Transfer parameters

From the Bolsa Família state-month data:
$$
\frac{T^P \lambda_P}{Y} = \frac{\text{total Bolsa Família receipts (monthly, national)}}{\text{national monthly output (proxy)}}
$$

From `pof_group_wealth_income_summary.csv`, the ratio `mean_govt_transfers / mean_monthly_income` for PHtM gives the transfer income share for calibrating (L.4).

### 8.5 Informality shares

Compute conditional informality shares from PNADC (`state_month_labour_market.parquet`), restricted to PHtM-classified individuals:
- `s_i ≈` time-mean of `informal_share` conditional on PHtM classification
- `s_k ≈` time-mean of `conta_propria_share` conditional on PHtM classification
- `s_f = 1 − s_i − s_k`

In the absence of individual-level agent-type × labour-status joint data, you may approximate by conditioning on income quintile (Q1–Q2 ≈ PHtM-likely).

### 8.6 Parameter table (current values and uncertainties)

| Parameter | Baseline value | Source / confidence | Brazil note |
|---|---|---|---|
| `β_R` | 0.99 | Eskelinen / low confidence for Brazil | Real rates in Brazil are much higher; consider 0.96–0.98 |
| `β_W` | 0.98 | Eskelinen / low confidence for Brazil | Should remain below β_R |
| `α_R` | **From POF pipeline** | POF 2017/18 / high confidence | Replace 0.78 |
| `α_W` | **From POF pipeline** | POF 2017/18 / high confidence | Replace 0.18 |
| `α_P` | **From POF pipeline** | POF 2017/18 / high confidence | Replace 0.04 |
| `j̄` | 0.10 | Iacoviello (2005) / medium confidence | Brazil housing preference likely differs |
| `η` | 1.01 | Iacoviello / uncertain for Brazil | Brazil labour supply estimates vary widely |
| `X̄` | 1.10–1.15 | Mark-ups higher in Brazil due to market concentration | Eskelinen uses 1.05; Brazil competition weaker |
| `θ` | 0.55–0.65 | BCB pricing literature / medium confidence | Faster price adjustment than advanced economies |
| `m` | 0.70–0.80 | BCB mortgage market data / medium confidence | Lower than Eskelinen's 0.90 |
| `φ` | 0.05 | Iacoviello–Pavan (2013) / low confidence for Brazil | Transaction costs in Brazil are very high |
| `r_R` | 0.73 | Eskelinen / check against COPOM literature | |
| `r_π` | 0.50–1.00 | COPOM reaction function estimates / uncertain | Brazil's Taylor coefficient historically large |
| `r_Y` | 0.13 | Eskelinen / uncertain | |
| `T̄^P / ȳ^P` | **From Bolsa Família data** | State × month receipts / high confidence | Key Brazil-specific target |
| `ρ_T` | ≈ 0.95 | PBF is slowly varying / medium confidence | Discrete policy changes dominate |
| `s_i` | **From PNADC conditional** | PNADC informal_share / high confidence | Key Brazil parameter |
| `s_k` | **From PNADC conditional** | PNADC conta_propria_share / high confidence | Key Brazil parameter |
| `ρ_A, ρ_j, ρ_u` | Eskelinen as starting values | Re-estimate from Brazilian data | |

> **Parameters flagged as requiring recalibration for Brazil:** `β_R`, `β_W`, `θ`, `m`, `r_π`, `α_R`, `α_W`, `α_P`, `T̄^P`. The last five are directly identifiable from the pipeline data. The first four require either external Brazilian macro estimates or internal model-based calibration.

---

## 9. LP Regression — Model Bridge

The empirical specification is a **state × month heterogeneous-response local projection**. This section maps between the theoretical model and the LP estimates.

### 9.1 LP specification

For outcome `y_{s,t+h}` (income, consumption proxy) in state `s` at horizon `h`:
$$
\ln y_{s,t+h} - \ln y_{s,t-1} = \alpha_h \cdot \text{mp\_shock}_t + \beta_h \cdot \text{mp\_shock}_t \times \lambda_{W,s,t-1} + \gamma_h \cdot \text{mp\_shock}_t \times \lambda_{P,s,t-1} + \delta X_{s,t} + \text{FE}_{s} + \text{FE}_{t} + \varepsilon_{s,t+h}
$$

where the reference (omitted) category is `λ_{R,s,t}`, and `X_{s,t}` is the vector of state controls (unemployment, formal share, income trends, etc.).

### 9.2 Mapping to model parameters

| LP coefficient | Model interpretation | Relevant equation |
|---|---|---|
| `α_h` (baseline) | Ricardian-economy IRF — intertemporal substitution channel only | (L.2) |
| `β_h` (WHtM differential) | Additional response from collateral + debt deflation channels | (L.3), (L.5), (L.7) |
| `γ_h` (PHtM differential) | Additional response from labour income channel; attenuated by informality and BF | (L.4) |
| `β_h − γ_h` | WHtM vs PHtM differential — identifies relative importance of collateral channel | — |
| `α_h + β̄_h + γ̄_h` | Aggregate IRF at mean household composition (from `aggregate_irf.csv`) | (L.1)–(L.10) |

The LP gives **reduced-form** estimates of these quantities. The structural model provides a mapping from `{α_h, β_h, γ_h}` to structural parameters `{β_R, β_W, m, η, θ, α_R, α_W, α_P, T̄^P, s_i}`. This mapping can be used for:
1. **Over-identification tests:** Do the LP estimates at multiple horizons jointly fit the model's IRFs?
2. **Structural interpretation:** Which parameters drive the between-state heterogeneity in `β_h` vs `γ_h`?

### 9.3 What the state-level variation identifies

| Data feature | Structural parameter identified |
|---|---|
| Cross-state variation in `λ_{W,s}` | Magnitude of collateral channel (`m`, `φ`) |
| Cross-state variation in `λ_{P,s}` | PHtM labour income elasticity (attenuated by `s_i`, `s_k`, `T̄^P`) |
| Cross-state variation in `formal_share` | Degree of informality buffering (`s_i`, `s_k`) in PHtM response |
| Time variation in `mp_shock` | Aggregate monetary transmission (all channels) |
| Cross-state variation in `informal_share` | Interaction: does high informality dampen γ_h? |

### 9.4 Welfare / inequality output from IRFs

From the `irf.csv` schema (`term_role = differential_irf`, `household_exposure`):
- The differential IRFs at horizons h=0,…,H give the consumption inequality response profile
- Positive `β_h − γ_h` (WHtM respond more strongly than PHtM) means WHtM-concentrated states see larger consumption drops
- This maps to Auclert's (2019) **interest rate exposure channel**: WHtM have large negative UREs (unhedged interest rate exposures), PHtM have near-zero UREs
- The BF transfer attenuating `γ_h` but not `β_h` implies redistribution from BF partially offsets monetary contraction's regressive distributional effects

---

## 10. Monetary shock data

**Source:** `results/diagnostics/shock_transformation_log.csv`

- `di_surprise`: Raw DI futures surprise in percentage points, signed so positive = unexpected rate increase
- `mp_shock_monthly`: Transformed for use in regressions

**Interpretation in model:** `mp_shock_monthly` ↔ `ê_{R,t}` in (L.10). A one-standard-deviation positive shock is a contractionary surprise.

**Key features of DI-based identification:**
- Identified from COPOM announcement windows (approximately 30-minute window around decision release)
- Orthogonal to information about future macro conditions by construction (high-frequency)
- Captures only surprise component of monetary policy

> I am not certain of the exact construction methodology for `mp_shock_monthly`. Verify against the transformation log and the underlying COPOM surprise literature (e.g. Figueiredo–Marques, BCB literature) to confirm the shock variable is appropriately signed and scaled before interpreting structural magnitudes.

---

## 11. SSJ block structure

All three household types are **SimpleBlocks** (algebraic FOCs — no Krusell–Smith policy iteration). The block structure follows Auclert–Bardóczy–Rognlie–Straub (Econometrica 2021).

> **API caveat.** Exact function names in the `sequence-jacobian` package evolve. Treat the block names below as conceptual. Verify against current GitHub docs at `shade-econ/sequence-jacobian` before implementing.

### Block decomposition

| Block | Inputs | Outputs | Equations |
|---|---|---|---|
| **Ricardian** (Simple) | `r_t, w_t^R, q_t, F_t, j_t` | `c_t^R, h_t^R, b_t^R, L_t^R` | (R.2)–(R.5) |
| **WHtM** (Simple) | `r_t, R_t, Π_t, w_t^W, q_t, j_t` | `c_t^W, h_t^W, b_t^W, L_t^W, μ_t` | (W.2)–(W.6), (W.3) binding |
| **PHtM** (Simple) | `w_{f,t}^P, w̄_{i,t}^P, w̄_{k,t}^P, T_t^P` | `c_t^P, L_{f,t}^P, L_{i,t}^P, L_{k,t}^P` | (P.2)–(P.5) |
| **Firms** (Simple) | `Y_t, L_t^R, L_t^W, L_{f,t}^P, X_t, A_t` | `w_t^R, w_t^W, w_{f,t}^P, F_t` | (F.1)–(F.4) |
| **NKPC** (Simple, forward-looking) | `X_t, E_t π_{t+1}, u_t` | `π_t` | (F.9) |
| **Taylor** (Simple) | `π_{t-1}, Y_{t-1}, R_{t-1}, e_{R,t}` | `R_t` | (M.1) / (L.10) |
| **Clearing** (targets) | All outputs | Residuals for `h^R + h^W − H`, `b^R − b^W`, labour markets | (MC.1)–(MC.3) |
| **Transfer** (exogenous process) | `ε_t^T` | `T_t^P` | (BF.2) |

### Solution workflow

1. **Steady state** — Solve §5 closed-form ratios with Brazil calibration (§8). Recover `{c̄^R, c̄^W, c̄^P, h̄^R, h̄^W, b̄^W, q̄, ȳ^R, ȳ^W, ȳ^P, ...}`. Check `μ̄ > 0`.
2. **Verify** — `h̄^W/H ∈ (0,1)`, all consumption shares positive, `b̄^W/Ȳ` matches `state_month_htm_shares` aggregate moments.
3. **Jacobians** — Differentiate each block w.r.t. its inputs via automatic differentiation. For the NKPC (forward-looking), use the fake-news algorithm.
4. **GE Jacobian** — Compose block Jacobians along the DAG; impose clearing conditions.
5. **IRFs** — For each shock `{e_R, A, j, u, T^P}`, compute `dU = −H_U^{-1} H_Z dZ` and propagate.
6. **Comparison to LP** — Evaluate model IRFs at mean national `{λ_R, λ_W, λ_P}` and at the cross-state distribution; compare to `irf.csv` estimates (§9).

### Common bugs in the Brazilian implementation

- **SELIC vs DI rate**: The model uses a monthly gross rate `R_t`. The data uses SELIC (annualised) and DI futures (in basis points of the daily rate). Convert consistently.
- **BF transfer timing**: `T_t^P` is paid monthly but determined by federal policy set quarterly or annually. Use the `ρ_T ≈ 0.95` AR(1) as an approximation; flag discrete policy events (e.g. 2019 PBF reform) as structural breaks.
- **Missing housing states**: For 12 UFs without a housing index, `q_t` is unobserved in the LP. Either impute regionally, restrict the collateral channel regressions to the 15-state sample, or use an alternative housing proxy (e.g. credit volume from SCR/BCB data).
- **Informal wage endogeneity**: `w̄_{i,t}^P` and `w̄_{k,t}^P` are not fully exogenous — they respond to aggregate labour demand with some elasticity. If the informality buffer is estimated to be strong in the LP, this semi-exogeneity assumption needs robustness checks.

---

## 12. Data gaps and model limitations

| Gap | Consequence | Suggested mitigation |
|---|---|---|
| Housing index for only 15 of 27 UFs | Collateral channel (W.6), housing-market clearing (MC.1) unidentified for 12 states | Restrict collateral-channel regressions to 15-state sample; sensitivity analysis |
| No individual-level consumption data from PNADC (income only) | Cannot directly observe PHtM consumption response; rely on income as proxy | POF provides cross-sectional consumption by agent type; use LP on income |
| Monthly frequency but COPOM meets ~8×/year | Many months have no shock; DI surprise = 0 | Standard in HF identification; use as-is |
| State-level net liquid assets coverage | Needed to calibrate WHtM constraint; coverage varies | Use `state_month_htm_shares.parquet` net liquid assets where available |
| No panel consumption at individual level | Cannot track within-type heterogeneity | Acknowledged THRANK limitation vs full HANK; see Eskelinen §2 |
| Bolsa Família amounts lumped with other transfers in POF | Hard to isolate BF from other government transfers | Use `mean_govt_transfers` as upper bound; individual PBF administrative data if available |
| `conta_propria_share` may include some high-income self-employed | Could contaminate PHtM characterisation | Apply income quintile restriction (Q1–Q3 only) when computing conditional shares |

---

## 13. References

- Auclert, A. (2019). "Monetary Policy and the Redistribution Channel." *American Economic Review* 109(6): 2333–2367.
- Auclert, A., Bardóczy, B., Rognlie, M., Straub, L. (2021). "Using the Sequence-Space Jacobian to Solve and Estimate Heterogeneous-Agent Models." *Econometrica* 89(5): 2375–2408.
- Bilbiie, F. O. (2008). "Limited Asset Markets Participation, Monetary Policy and (Inverted) Aggregate Demand Logic." *Journal of Economic Theory* 140(1): 162–196.
- Cloyne, J., Ferreira, C., Surico, P. (2020). "Monetary Policy when Households have Debt: New Evidence on the Transmission Mechanism." *Review of Economic Studies* 87(1): 102–129.
- Eskelinen, M. (2021). "Monetary policy, agent heterogeneity and inequality: insights from a three-agent New Keynesian model." ECB Working Paper No. 2590.
- Galí, J., López-Salido, J. D., Vallés, J. (2007). "Understanding the Effects of Government Spending on Consumption." *JEEA* 5(1): 227–270.
- Iacoviello, M. (2005). "House Prices, Borrowing Constraints, and Monetary Policy in the Business Cycle." *AER* 95(3): 739–764.
- Kaplan, G., Moll, B., Violante, G. (2018). "Monetary Policy According to HANK." *AER* 108(3): 697–743.
- Kaplan, G., Violante, G., Weidner, J. (2014). "The Wealthy Hand-to-Mouth." *Brookings Papers on Economic Activity* (also NBER WP 20073).
- Rubio, M. (2011). "Fixed and Variable-Rate Mortgages, Business Cycles, and Monetary Policy." *Journal of Money, Credit and Banking* 43(4): 657–688.

---

*Last updated: Brazil adaptation incorporating POF 2017/18, PNADC-C, DI futures shock series, and state × month labour market data. Re-run calibration section after reading pipeline outputs from `results/tables/`.*
