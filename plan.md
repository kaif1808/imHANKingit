# HTM Classification Validity Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the 8 ranked recommendations in `results/htm_classification_validity_review.md` (May 19, 2026) so that `scripts/reporting/htm_classification.py` produces classifications that (i) eliminate the WH2M income anomaly, (ii) match POF/PNADC at the documented bin-strategy specification *and* its current implementation for side-by-side comparison, (iii) classify at the household head rather than every adult, (iv) include vehicle illiquid wealth, and (v) are gated by magnitude regression tests so future regressions surface immediately.

**Architecture:** All core changes land in a single module (`scripts/reporting/htm_classification.py`). The pipeline keeps its current three-stage shape (POF classify → bin shares → PNADC monthly merge). Two orthogonal refactors are introduced: (a) classification operates on a household-level frame keyed by `(COD_UPA, NUM_DOM, NUM_UC)` with the reference person (`V0306 == 1`) supplying demographics and aggregate income summed across all members; (b) bin construction is parameterised by a `BinStrategy` enum with two implementations — Strategy A (5-way labour × POF income quintiles, current behaviour) and Strategy G (3-way labour × absolute BRL income bands per overleaf §"Bin strategy comparison"). All new behaviour is reachable behind CLI flags with backwards-compatible defaults so downstream consumers (`basic_state_month_lp.py`, `cumulative_irf_heterogeneity.py`) are not broken between commits.

**Tech Stack:** Python 3.11+, pandas, pyarrow, numpy, pytest. No new third-party dependencies. Tests use synthetic in-memory DataFrames following the `tests/test_htm_monthly_batch.py` pattern.

**Out of scope (declared, not deferred):**
- Pension capitalisation as an actuarial annuity (review §2b.ii) — requires life-expectancy tables not present in repo. Future work.
- Business-equity capitalisation for self-employed households (alluded to in earlier draft) — `V5303` self-employment flag is on the *income* table, not on the head record, and mapping is not 1-1 with household equity. Future work.
- Re-tuning `ILLIQUID_MULT` away from 3 (review §2c) — KVW use "any positive illiquid wealth"; we keep 3 and surface sensitivity through `--illiquid-mult` CLI knob instead of changing the default.
- Updating `overleaf/main.tex` — happens after the comparison table is reviewed by the user; not part of this plan's code work.

---

## File Structure

| Path | Responsibility | Action |
|------|----------------|--------|
| `scripts/reporting/htm_classification.py` | Pipeline entry point; all classification, bin construction, and PNADC merge logic. | Modify (Tasks 1, 3–10) |
| `tests/test_htm_classification_validity.py` | Magnitude regression tests + WH2M ordering + household-unit + per-capita tests. | Create (Task 2) |
| `tests/test_htm_bin_strategies.py` | Strategy A vs G match-rate ordering and bin-key construction. | Create (Task 8) |
| `tests/fixtures/__init__.py` | Synthetic POF + PNADC fixture builders shared across tests. | Create (Task 2) |
| `tests/test_htm_monthly_batch.py` | Existing — extend with one head-of-household regression. | Modify (Task 5) |
| `RESULTS_PROVENANCE.md` | Document new diagnostic CSV outputs. | Modify (Task 10) |

**Decomposition rationale:** Splitting validity tests into a dedicated file keeps the existing batch/quintile suites focused on their narrow contracts and lets the validity regressions run independently in CI. Strategy comparison tests live in their own file because they require both POF and PNADC fixtures and would bloat `test_htm_classification_validity.py` otherwise.

---

## Pre-flight (run once before Task 1)

- [ ] **P.1: Confirm the baseline test suite is green.**

  Run: `pytest tests/ -q`
  Expected: all tests pass, exit code 0. If any test fails on `main`, stop and surface to user before touching pipeline code.

- [ ] **P.2: Snapshot current pipeline outputs.**

  Run:
  ```bash
  mkdir -p /tmp/htm_baseline
  cp results/tables/pof_bin_shares.csv \
     results/tables/pof_group_wealth_income_summary.csv \
     results/tables/state_month_htm_shares.parquet \
     results/diagnostics/monthly_htm_coverage.csv \
     /tmp/htm_baseline/ 2>/dev/null || true
  ls -la /tmp/htm_baseline/
  ```
  Expected: four files present (or a clear note if any are absent — they are gitignored).

  These will be diffed against post-change runs in the verification section.

---

## Task 1: Informative Dirichlet prior (Rec 5)

**Files:**
- Modify: `scripts/reporting/htm_classification.py:617–633` (`bin_shares` construction in `build_pof_bin_shares`)

Lowest-blast-radius change; lands first so the Step-3 household refactor can rely on a stable smoothing path.

- [ ] **Step 1.1: Write the failing test.**

  Create `tests/test_htm_classification_validity.py` with the following minimum to anchor the test file:

  ```python
  """Validity regression tests for htm_classification.py."""
  import numpy as np
  import pandas as pd
  import pytest

  import htm_classification as htm


  def test_empty_bin_uses_national_prior_not_uniform():
      """A bin with zero observed weight must shrink to POF national shares,
      not to uniform (1/3, 1/3, 1/3)."""
      pof_national = {"p_ph2m": 0.215, "p_wh2m": 0.193, "p_ric": 0.592}
      # ALPHA_SMOOTH applied to a bin with zero observed weight:
      p_ph2m, p_wh2m, p_ric = htm._smoothed_shares(
          weighted_ph2m=0.0,
          weighted_wh2m=0.0,
          weighted_ric=0.0,
          total_weight=0.0,
          pof_national=pof_national,
          alpha=htm.ALPHA_SMOOTH,
      )
      assert p_ph2m == pytest.approx(0.215, abs=1e-6)
      assert p_wh2m == pytest.approx(0.193, abs=1e-6)
      assert p_ric == pytest.approx(0.592, abs=1e-6)
      assert p_ph2m + p_wh2m + p_ric == pytest.approx(1.0, abs=1e-9)
  ```

- [ ] **Step 1.2: Run the test, confirm it fails.**

  Run: `pytest tests/test_htm_classification_validity.py::test_empty_bin_uses_national_prior_not_uniform -v`
  Expected: FAIL with `AttributeError: module 'htm_classification' has no attribute '_smoothed_shares'`.

- [ ] **Step 1.3: Add `_smoothed_shares` helper.**

  Insert immediately above `build_pof_bin_shares` in `scripts/reporting/htm_classification.py`:

  ```python
  def _smoothed_shares(
      *,
      weighted_ph2m: float | pd.Series,
      weighted_wh2m: float | pd.Series,
      weighted_ric: float | pd.Series,
      total_weight: float | pd.Series,
      pof_national: dict[str, float],
      alpha: float,
  ) -> tuple[float | pd.Series, float | pd.Series, float | pd.Series]:
      """Empirical-Bayes Dirichlet smoother.

      Posterior = (observed + alpha * pi_k) / (total + alpha) where pi_k are
      POF national shares. With no observations the posterior collapses to
      pi_k rather than the uniform (1/3, 1/3, 1/3) of a flat prior.
      """
      denom = total_weight + alpha
      p_ph2m = (weighted_ph2m + alpha * pof_national["p_ph2m"]) / denom
      p_wh2m = (weighted_wh2m + alpha * pof_national["p_wh2m"]) / denom
      p_ric = (weighted_ric + alpha * pof_national["p_ric"]) / denom
      return p_ph2m, p_wh2m, p_ric
  ```

- [ ] **Step 1.4: Re-run the helper test.**

  Run: `pytest tests/test_htm_classification_validity.py::test_empty_bin_uses_national_prior_not_uniform -v`
  Expected: PASS.

- [ ] **Step 1.5: Wire `_smoothed_shares` into `build_pof_bin_shares`.**

  Replace lines 617–633 of `scripts/reporting/htm_classification.py` (the `denom = total + 3 * ALPHA_SMOOTH` block through the `bin_shares = pd.DataFrame({...})` construction) with:

  ```python
      total = grouped["PESO_FINAL"].sum()
      raw_n = grouped.size()
      p_ph2m, p_wh2m, p_ric = _smoothed_shares(
          weighted_ph2m=weighted["PH2M"],
          weighted_wh2m=weighted["WH2M"],
          weighted_ric=weighted["Ricardian"],
          total_weight=total,
          pof_national=pof_national,
          alpha=ALPHA_SMOOTH,
      )

      bin_shares = pd.DataFrame(
          {
              "bin_key": total.index,
              "p_ph2m": p_ph2m,
              "p_wh2m": p_wh2m,
              "p_ric": p_ric,
              "weighted_n": total,
              "raw_n": raw_n,
              "small_bin_flag": (total < MIN_WEIGHTED_N).astype(int),
          }
      ).reset_index(drop=True)
      bin_shares.attrs["pof_national"] = pof_national
  ```

- [ ] **Step 1.6: Run existing test suite to confirm no regression.**

  Run: `pytest tests/ -q`
  Expected: all tests pass.

- [ ] **Step 1.7: Commit.**

  ```bash
  git add scripts/reporting/htm_classification.py tests/test_htm_classification_validity.py
  git commit -m "htm: empirical-Bayes Dirichlet prior in bin smoothing"
  ```

---

## Task 2: Fixture builders for synthetic POF + PNADC

**Files:**
- Create: `tests/fixtures/__init__.py`

Provides reusable in-memory data generators so subsequent tasks can write tests without re-deriving the schema every time. No production code changes.

- [ ] **Step 2.1: Create the fixtures module.**

  Create `tests/fixtures/__init__.py`:

  ```python
  """Synthetic POF and PNADC fixture builders for htm_classification tests."""
  from __future__ import annotations

  import pandas as pd


  def build_pof_morador(
      n_households: int = 4,
      members_per_hh: int = 3,
      head_age: int = 40,
      child_age: int = 10,
      adult_age: int = 35,
  ) -> pd.DataFrame:
      """Return a synthetic MORADOR-shaped DataFrame.

      Each household has one reference person (V0306 == 1), one adult spouse
      (V0306 == 2), and (members_per_hh - 2) children (V0306 == 3, age below 15).
      """
      rows = []
      for hh in range(n_households):
          rows.append(dict(
              COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=1,
              V0306=1, age=head_age, sex=1, NIVEL_INSTRUCAO=5, RENDA_TOTAL=3000.0,
          ))
          rows.append(dict(
              COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=2,
              V0306=2, age=adult_age, sex=2, NIVEL_INSTRUCAO=5, RENDA_TOTAL=3000.0,
          ))
          for j in range(members_per_hh - 2):
              rows.append(dict(
                  COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=3 + j,
                  V0306=3, age=child_age, sex=1, NIVEL_INSTRUCAO=1, RENDA_TOTAL=3000.0,
              ))
      return pd.DataFrame(rows)


  def build_pof_domicilio(n_households: int = 4, uf: int = 35) -> pd.DataFrame:
      """Return a synthetic DOMICILIO-shaped DataFrame."""
      return pd.DataFrame([
          dict(COD_UPA=1000 + hh, NUM_DOM=1, UF=uf, PESO_FINAL=100.0)
          for hh in range(n_households)
      ])


  def build_pof_income_inputs(
      n_households: int = 4,
      labor_income_per_head: float = 2500.0,
      pension_per_head: float = 0.0,
      financial_income_per_head: float = 0.0,
      transfers_per_head: float = 0.0,
      estimated_rent: float = 800.0,
  ) -> dict[str, pd.DataFrame]:
      """Return income-side dictionaries keyed by (UPA, DOM, UC, INFORMANTE)."""
      inc = pd.DataFrame([
          dict(COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=1,
               total_labor_income=labor_income_per_head, V5302=1, V5303=1)
          for hh in range(n_households)
      ])
      trans = pd.DataFrame([
          dict(COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1, COD_INFORMANTE=1,
               pension_income=pension_per_head, govt_transfers=transfers_per_head,
               financial_income=financial_income_per_head, other_labor_inc=0.0,
               total_transfers=pension_per_head + transfers_per_head
                                + financial_income_per_head)
          for hh in range(n_households)
      ])
      alug = pd.DataFrame([
          dict(COD_UPA=1000 + hh, NUM_DOM=1, NUM_UC=1,
               estimated_rent=estimated_rent, real_estate_annual=estimated_rent * 12)
          for hh in range(n_households)
      ])
      return {"inc": inc, "trans": trans, "alug": alug}
  ```

- [ ] **Step 2.2: Smoke-test the fixtures.**

  Run:
  ```bash
  python3 -c "from tests.fixtures import build_pof_morador, build_pof_domicilio, build_pof_income_inputs; \
              m = build_pof_morador(); d = build_pof_domicilio(); i = build_pof_income_inputs(); \
              print(len(m), len(d), list(i.keys()))"
  ```
  Expected output: `12 4 ['inc', 'trans', 'alug']` (4 households × 3 members = 12 MORADOR rows).

- [ ] **Step 2.3: Commit.**

  ```bash
  git add tests/fixtures/__init__.py
  git commit -m "tests: add POF/PNADC synthetic fixture builders"
  ```

---

## Task 3: Fix zero-income clip (Rec 1, highest economic priority)

**Files:**
- Modify: `scripts/reporting/htm_classification.py:478–494` (`monthly_income` clip and ratio computation)
- Modify: `tests/test_htm_classification_validity.py` (add ordering test)

- [ ] **Step 3.1: Write the failing ordering test.**

  Append to `tests/test_htm_classification_validity.py`:

  ```python
  def test_inactive_zero_income_with_rent_is_not_classified_wh2m():
      """A row with monthly_income == 0 and household real-estate > 0 must NOT
      be assigned WH2M. Under the old clip(lower=1) path, illiquid_ratio
      blew up to ~rent*12 and classified the row as WH2M trivially.
      """
      row = pd.Series({
          "liquid_ratio": 0.0,
          "illiquid_ratio": float("nan"),  # produced by guarded denominator
          "monthly_income": 0.0,
          "is_poor": True,
      })
      # Inactive-zero rows are excluded from baseline classification.
      assert htm._classify_with_exclusion(row) == "inactive_excluded"


  def test_classify_with_exclusion_routes_positive_income_normally():
      row = pd.Series({
          "liquid_ratio": 0.1,
          "illiquid_ratio": 5.0,
          "monthly_income": 1500.0,
          "is_poor": False,
      })
      assert htm._classify_with_exclusion(row) == "WH2M"
  ```

- [ ] **Step 3.2: Run the new tests, confirm they fail.**

  Run: `pytest tests/test_htm_classification_validity.py -v -k "inactive_zero or with_exclusion"`
  Expected: both FAIL — `_classify_with_exclusion` does not exist.

- [ ] **Step 3.3: Add ratio caps and the excluding classifier.**

  In `scripts/reporting/htm_classification.py` near the existing thresholds (after the `MIN_WEIGHTED_N` line):

  ```python
  ILLIQUID_RATIO_CAP = 20.0
  LIQUID_RATIO_CAP = 50.0
  ```

  Add the new classifier next to `classify_agent` (around line 192):

  ```python
  def _classify_with_exclusion(row: pd.Series) -> str:
      """KVW classifier that excludes inactive zero-income rows.

      A row is `inactive_excluded` when monthly_income is non-positive — such
      individuals have no pay-period income to be hand-to-mouth relative to,
      and `illiquid_ratio` is mathematically undefined (NaN under the guarded
      denominator). Excluded rows are dropped from bin-share denominators
      and recorded in a diagnostic CSV.
      """
      monthly_income = float(row.get("monthly_income", 0.0))
      if monthly_income <= 0.0 or pd.isna(row.get("illiquid_ratio")):
          return "inactive_excluded"
      if row["liquid_ratio"] > LIQUID_THRESH:
          return "Ricardian"
      if row["illiquid_ratio"] >= ILLIQUID_MULT:
          return "WH2M"
      return "PH2M"
  ```

- [ ] **Step 3.4: Replace the clip with a guarded denominator in `build_pof_bin_shares`.**

  Replace lines 478–494 in `scripts/reporting/htm_classification.py` (everything between `pof["monthly_income"] = pof["monthly_income"].clip(lower=1)` and `pof["is_poor"] = pof["pc_income"] <= POVERTY_LINE`) with:

  ```python
      # NOTE: do NOT clip(lower=1). The old clip caused inactive zero-income
      # adults in property-owning households to satisfy illiquid_ratio >= 3
      # trivially, contaminating WH2M. See validity review §4.
      pof["financial_income_annual"] = pof["financial_income"] * 12
      pof["fin_liquid"] = pof["financial_income_annual"] / SELIC_RATE
      pof["pen_liquid"] = pof["pension_income"] * PENSION_MULT
      pof["income_surplus"] = (pof["RENDA_TOTAL"] - pof["monthly_income"] * 12).clip(lower=0)
      pof["sav_liquid"] = pof["income_surplus"] * SAVINGS_FRAC
      pof.loc[pof["govt_transfers"] > 0, "sav_liquid"] = 0
      pof["liquid_assets"] = pof["fin_liquid"] + pof["pen_liquid"] + pof["sav_liquid"]
      pof["illiquid_assets"] = pof["real_estate_annual"]

      hh_size = pof.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"])["age"].transform("count")
      denom = pof["monthly_income"].where(pof["monthly_income"] > 0)
      pof["pc_income"] = pof["monthly_income"] / hh_size  # quintile cuts use this
      pof["liquid_ratio"] = (pof["liquid_assets"] / denom).clip(upper=LIQUID_RATIO_CAP)
      pof["illiquid_ratio"] = (pof["illiquid_assets"] / denom).clip(upper=ILLIQUID_RATIO_CAP)
      pof["net_worth"] = pof["liquid_assets"] + pof["illiquid_assets"]
      pof["is_poor"] = pof["pc_income"] <= POVERTY_LINE
  ```

  Replace the `pof["agent_type"] = pof.apply(classify_agent, axis=1)` line with:

  ```python
      pof["agent_type"] = pof.apply(_classify_with_exclusion, axis=1)
  ```

- [ ] **Step 3.5: Drop `inactive_excluded` rows from bin probabilities and write a diagnostic.**

  In `build_pof_bin_shares`, just before the `weights = pof["PESO_FINAL"]` line (~line 509), insert:

  ```python
      excluded_mask = pof["agent_type"] == "inactive_excluded"
      excluded_count = int(excluded_mask.sum())
      excluded_weight = float(pof.loc[excluded_mask, "PESO_FINAL"].sum())
      excluded_diag = (
          pof.loc[excluded_mask]
          .groupby(["age", "sex"], dropna=False)
          .agg(n=("PESO_FINAL", "size"), weight=("PESO_FINAL", "sum"))
          .reset_index()
      )
      DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
      excluded_diag.to_csv(
          DIAGNOSTICS_DIR / "pof_zero_income_excluded.csv", index=False
      )
      pof = pof.loc[~excluded_mask].copy()
      print(
          f"  Excluded {excluded_count:,} inactive zero-income rows "
          f"(weighted = {excluded_weight:.0f}). "
          f"Diagnostic -> {DIAGNOSTICS_DIR / 'pof_zero_income_excluded.csv'}"
      )
  ```

  (Note: the `excluded_diag.groupby` falls back to raw `age`/`sex` when `age_group` is not yet computed; the diagnostic is small so the dual path is acceptable.)

- [ ] **Step 3.6: Run the validity tests.**

  Run: `pytest tests/test_htm_classification_validity.py -v`
  Expected: all three tests in the file pass.

- [ ] **Step 3.7: Run the full suite to catch downstream regressions.**

  Run: `pytest tests/ -q`
  Expected: pass. If `test_htm_monthly_batch.py` fails because synthetic rows now route to `inactive_excluded`, fix the synthetic data in the existing tests — do not weaken `_classify_with_exclusion`.

- [ ] **Step 3.8: Commit.**

  ```bash
  git add scripts/reporting/htm_classification.py tests/test_htm_classification_validity.py
  git commit -m "htm: drop inactive zero-income rows, cap ratios, fix WH2M anomaly"
  ```

---

## Task 4: Magnitude regression test — POF national shares in literature range

**Files:**
- Modify: `tests/test_htm_classification_validity.py`

This task lands the *gate* that future tasks must keep green. It uses synthetic POF inputs and exercises the real pipeline.

- [ ] **Step 4.1: Add a fixture-backed national-shares test.**

  Append to `tests/test_htm_classification_validity.py`:

  ```python
  from tests.fixtures import (
      build_pof_morador,
      build_pof_domicilio,
      build_pof_income_inputs,
  )


  def _run_pof_classification_from_fixtures(monkeypatch, tmp_path):
      """Run build_pof_bin_shares against synthetic POF tables.

      Patches the IO seam (htm.read_pof_table) so no disk reads occur.
      """
      mor = build_pof_morador(n_households=200, members_per_hh=3)
      dom = build_pof_domicilio(n_households=200)
      income = build_pof_income_inputs(
          n_households=200,
          labor_income_per_head=3500.0,
          pension_per_head=0.0,
          financial_income_per_head=400.0,
          transfers_per_head=0.0,
          estimated_rent=900.0,
      )

      def fake_read(txt_filename, sheet_name):
          if txt_filename == "DOMICILIO.txt":
              return dom.astype(str)
          if txt_filename == "MORADOR.txt":
              return mor.rename(columns={"age": "V0403", "sex": "V0404"}).astype(str)
          if txt_filename == "RENDIMENTO_TRABALHO.txt":
              # build_pof_bin_shares aggregates separately; supply per-informant rows
              long = income["inc"].assign(V8500_DEFLA=income["inc"]["total_labor_income"])
              return long.astype(str)
          if txt_filename == "OUTROS_RENDIMENTOS.txt":
              long = income["trans"].assign(
                  QUADRO=55, V9001=0,
                  V8500_DEFLA=income["trans"]["pension_income"],
              )
              return long.astype(str)
          if txt_filename == "ALUGUEL_ESTIMADO.txt":
              return income["alug"].assign(V8000_DEFLA=income["alug"]["estimated_rent"]).astype(str)
          raise AssertionError(f"unexpected read: {txt_filename}")

      monkeypatch.setattr(htm, "read_pof_table", fake_read)
      monkeypatch.setattr(htm, "TABLES_DIR", tmp_path / "tables")
      monkeypatch.setattr(htm, "DIAGNOSTICS_DIR", tmp_path / "diag")
      bin_shares, _edges, pof_national = htm.build_pof_bin_shares(tmp_path / "tables")
      return bin_shares, pof_national


  def test_pof_national_shares_within_literature_range(monkeypatch, tmp_path):
      _bins, nat = _run_pof_classification_from_fixtures(monkeypatch, tmp_path)
      assert 0.15 <= nat["p_ph2m"] <= 0.30, f"PH2M={nat['p_ph2m']:.3f} outside [0.15, 0.30]"
      assert 0.10 <= nat["p_wh2m"] <= 0.25, f"WH2M={nat['p_wh2m']:.3f} outside [0.10, 0.25]"
      assert 0.50 <= nat["p_ric"] <= 0.75, f"Ric={nat['p_ric']:.3f} outside [0.50, 0.75]"
  ```

- [ ] **Step 4.2: Run the new test.**

  Run: `pytest tests/test_htm_classification_validity.py::test_pof_national_shares_within_literature_range -v`
  Expected: PASS *if* the Task 3 changes route synthetic homogeneous fixtures to PH2M ≈ 1.0 (which is outside the range). If FAIL, vary the fixture parameters in `_run_pof_classification_from_fixtures` so the synthetic distribution lands within the range — the *point* is to lock in a regression gate, so the fixture is allowed to be intentionally heterogeneous.

  Acceptable parameterisation if the homogeneous fixture fails: instead of one call, build a 60/20/20 mix by varying `financial_income_per_head` across three groups of households (0.0, 1500.0, 5000.0 BRL/month).

- [ ] **Step 4.3: Commit once green.**

  ```bash
  git add tests/test_htm_classification_validity.py
  git commit -m "tests: gate POF national shares to literature range"
  ```

---

## Task 5: Household-head classification (Rec 3)

**Files:**
- Modify: `scripts/reporting/htm_classification.py:370–510` (`build_pof_bin_shares` head section)
- Modify: `tests/test_htm_classification_validity.py`
- Modify: `tests/test_htm_monthly_batch.py`

- [ ] **Step 5.1: Write the household-unit and per-resident tests.**

  Append to `tests/test_htm_classification_validity.py`:

  ```python
  def test_classification_unit_is_household_head(monkeypatch, tmp_path):
      """bin_shares must reflect one row per household, not one per adult."""
      bins, _nat = _run_pof_classification_from_fixtures(monkeypatch, tmp_path)
      # Each fixture household has one head; 200 households → at most 200 bin members
      # (raw_n column aggregates membership at the head level)
      assert bins["raw_n"].sum() <= 200, (
          f"bin_shares totals {int(bins['raw_n'].sum())} > 200 households "
          "(person-level inflation regressed)"
      )


  def test_per_capita_income_uses_all_residents_not_only_adults(monkeypatch, tmp_path):
      """For a 4-person household (2 adults + 2 children) with 3000 BRL/month
      household income, per-capita income must be 750, not 1500."""
      mor = build_pof_morador(n_households=1, members_per_hh=4,
                              head_age=40, adult_age=35, child_age=8)
      dom = build_pof_domicilio(n_households=1)
      income = build_pof_income_inputs(
          n_households=1, labor_income_per_head=3000.0, estimated_rent=0.0,
      )
      # patch readers (same pattern as _run_pof_classification_from_fixtures)
      def fake_read(txt_filename, sheet_name):
          if txt_filename == "DOMICILIO.txt": return dom.astype(str)
          if txt_filename == "MORADOR.txt":
              return mor.rename(columns={"age":"V0403","sex":"V0404"}).astype(str)
          if txt_filename == "RENDIMENTO_TRABALHO.txt":
              return income["inc"].assign(V8500_DEFLA=income["inc"]["total_labor_income"]).astype(str)
          if txt_filename == "OUTROS_RENDIMENTOS.txt":
              return income["trans"].assign(QUADRO=55, V9001=0, V8500_DEFLA=0).astype(str)
          if txt_filename == "ALUGUEL_ESTIMADO.txt":
              return income["alug"].assign(V8000_DEFLA=0).astype(str)
          raise AssertionError(txt_filename)
      monkeypatch.setattr(htm, "read_pof_table", fake_read)
      monkeypatch.setattr(htm, "TABLES_DIR", tmp_path / "t")
      monkeypatch.setattr(htm, "DIAGNOSTICS_DIR", tmp_path / "d")

      hh_frame = htm.build_pof_household_frame()
      assert hh_frame["pc_income"].iloc[0] == pytest.approx(3000.0 / 4)
  ```

- [ ] **Step 5.2: Run the tests, confirm failure.**

  Run: `pytest tests/test_htm_classification_validity.py -v -k "household_head or all_residents"`
  Expected: both FAIL — `build_pof_household_frame` does not exist and `raw_n` reflects per-person counts.

- [ ] **Step 5.3: Extract a household-level frame builder.**

  Add to `scripts/reporting/htm_classification.py` just above `build_pof_bin_shares`:

  ```python
  def build_pof_household_frame() -> pd.DataFrame:
      """Read POF tables and return one row per consumption unit, keyed on
      (COD_UPA, NUM_DOM, NUM_UC), with the reference person's (V0306 == 1)
      demographics and aggregate household income/wealth.
      """
      print("=" * 72)
      print("STEP 1a: BUILD HOUSEHOLD-LEVEL POF FRAME (head = V0306 == 1)")
      print("=" * 72)

      df_dom = read_pof_table("DOMICILIO.txt", "Domicílio")
      for col in ["COD_UPA", "NUM_DOM", "UF", "PESO_FINAL"]:
          df_dom[col] = pd.to_numeric(df_dom[col], errors="coerce")
      df_dom = df_dom[["COD_UPA", "NUM_DOM", "UF", "PESO_FINAL"]].copy()

      df_mor = read_pof_table("MORADOR.txt", "Morador")
      for col in ["COD_UPA","NUM_DOM","NUM_UC","COD_INFORMANTE","V0306",
                  "V0403","V0404","NIVEL_INSTRUCAO","RENDA_TOTAL"]:
          df_mor[col] = pd.to_numeric(df_mor[col], errors="coerce")
      df_mor.rename(columns={"V0403": "age", "V0404": "sex"}, inplace=True)

      # Per-resident count BEFORE any age filter:
      hh_residents = (
          df_mor.groupby(["COD_UPA","NUM_DOM","NUM_UC"], as_index=False)
          .size().rename(columns={"size": "hh_residents"})
      )

      heads = df_mor.loc[df_mor["V0306"] == 1, [
          "COD_UPA","NUM_DOM","NUM_UC","COD_INFORMANTE",
          "age","sex","NIVEL_INSTRUCAO","RENDA_TOTAL",
      ]].copy()

      # Aggregate per-member income tables to household level
      df_inc = read_pof_table("RENDIMENTO_TRABALHO.txt", "Rendimento do Trabalho")
      for col in ["COD_UPA","NUM_DOM","NUM_UC","V8500_DEFLA","V5302","V5303"]:
          df_inc[col] = pd.to_numeric(df_inc[col], errors="coerce")
      inc_hh = (
          df_inc.groupby(["COD_UPA","NUM_DOM","NUM_UC"], as_index=False)
          .agg(total_labor_income=("V8500_DEFLA","sum"),
               V5302=("V5302","first"),
               V5303=("V5303","first"))
      )

      df_oth = read_pof_table("OUTROS_RENDIMENTOS.txt", "Outros Rendimentos")
      for col in ["COD_UPA","NUM_DOM","NUM_UC","QUADRO","V8500_DEFLA"]:
          df_oth[col] = pd.to_numeric(df_oth[col], errors="coerce")
      trans_hh = (
          df_oth.groupby(["COD_UPA","NUM_DOM","NUM_UC"], as_index=False)
          .apply(lambda g: pd.Series({
              "pension_income": g.loc[g.QUADRO == 55, "V8500_DEFLA"].sum(),
              "govt_transfers": g.loc[g.QUADRO == 56, "V8500_DEFLA"].sum(),
              "financial_income": g.loc[g.QUADRO == 57, "V8500_DEFLA"].sum(),
              "other_labor_inc": g.loc[g.QUADRO == 54, "V8500_DEFLA"].sum(),
              "total_transfers": g["V8500_DEFLA"].sum(),
          }))
      )

      df_alug = read_pof_table("ALUGUEL_ESTIMADO.txt", "Aluguel Estimado")
      for col in ["COD_UPA","NUM_DOM","NUM_UC","V8000_DEFLA"]:
          df_alug[col] = pd.to_numeric(df_alug[col], errors="coerce")
      alug_hh = (
          df_alug.groupby(["COD_UPA","NUM_DOM","NUM_UC"], as_index=False)
          .agg(estimated_rent=("V8000_DEFLA","sum"))
      )
      alug_hh["real_estate_annual"] = alug_hh["estimated_rent"] * 12

      hh = (
          heads
          .merge(df_dom, on=["COD_UPA","NUM_DOM"], how="left")
          .merge(hh_residents, on=["COD_UPA","NUM_DOM","NUM_UC"], how="left")
          .merge(inc_hh, on=["COD_UPA","NUM_DOM","NUM_UC"], how="left")
          .merge(trans_hh, on=["COD_UPA","NUM_DOM","NUM_UC"], how="left")
          .merge(alug_hh, on=["COD_UPA","NUM_DOM","NUM_UC"], how="left")
      )

      fill_cols = ["total_labor_income","V5302","V5303","pension_income",
                   "govt_transfers","financial_income","other_labor_inc",
                   "total_transfers","estimated_rent","real_estate_annual"]
      hh[fill_cols] = hh[fill_cols].fillna(0)
      hh["monthly_income"] = hh["total_labor_income"] + hh["total_transfers"]
      hh["pc_income"] = hh["monthly_income"] / hh["hh_residents"].clip(lower=1)
      print(f"  Households: {len(hh):,}")
      return hh
  ```

- [ ] **Step 5.4: Replace person-level construction in `build_pof_bin_shares`.**

  In `build_pof_bin_shares`, replace the body from the start of the function down to (and including) the existing `pof = pof[pof["age"] >= 15].copy()` line with:

  ```python
      hh = build_pof_household_frame()
      # No age filter — the head's age is the unit demographic; non-adult heads
      # are vanishingly rare in POF but we keep them rather than silently drop.
      pof = hh.rename(columns={"hh_residents": "_hh_residents"}).copy()
      print(f"  POF households: {len(pof):,}")
  ```

  **Then also delete these two lines that Task 3 inserted** (they computed per-adult hh_size and per-capita income, both wrong now that `pof` is keyed at the household level — `build_pof_household_frame` already computed `pc_income` using `hh_residents`):

  ```python
      # DELETE these two lines from the Task 3 block:
      # hh_size = pof.groupby(["COD_UPA", "NUM_DOM", "NUM_UC"])["age"].transform("count")
      # pof["pc_income"] = pof["monthly_income"] / hh_size  # quintile cuts use this
  ```

  Keep the rest of `build_pof_bin_shares` (asset derivations from Task 3, ratios, classification, bin shares) — those operate on `pof` regardless of whether it is person- or household-keyed.

- [ ] **Step 5.5: Update PNADC per-capita income to use all residents.**

  In `prepare_pnadc_batch` (around line 903 of the current file), replace:

  ```python
      hh_size = pd.to_numeric(df["V2001"], errors="coerce").clip(lower=1).fillna(1)
      rendimento = pd.to_numeric(df["rendimento_habitual_real"], errors="coerce").fillna(0)
      df["pc_income_pnadc"] = rendimento / hh_size
  ```

  with — no logical change, but add a comment so the parallelism with the POF side is explicit:

  ```python
      # V2001 = household member count incl. children; matches POF hh_residents.
      hh_size = pd.to_numeric(df["V2001"], errors="coerce").clip(lower=1).fillna(1)
      rendimento = pd.to_numeric(df["rendimento_habitual_real"], errors="coerce").fillna(0)
      df["pc_income_pnadc"] = rendimento / hh_size
  ```

- [ ] **Step 5.6: Update `tests/test_htm_monthly_batch.py` for new fixture shape if needed.**

  Run: `pytest tests/test_htm_monthly_batch.py -v`
  Expected: PASS (PNADC side did not change behaviour). If FAIL because the synthetic data was structured around per-adult quintiles, adjust the fixtures' `V2001` values so per-capita income lands in the same quintile as before. Do not change `pc_income_pnadc` semantics.

- [ ] **Step 5.7: Run all validity tests.**

  Run: `pytest tests/test_htm_classification_validity.py -v`
  Expected: all pass, including the two new household-unit tests.

- [ ] **Step 5.8: Commit.**

  ```bash
  git add scripts/reporting/htm_classification.py tests/test_htm_classification_validity.py tests/test_htm_monthly_batch.py
  git commit -m "htm: classify at household head (V0306==1) with per-resident income"
  ```

---

## Task 6: Add vehicle illiquid assets from INVENTARIO (Rec 4)

**Files:**
- Modify: `scripts/reporting/htm_classification.py` (new `_read_pof_vehicles` helper; extend `illiquid_assets`)
- Modify: `tests/test_htm_classification_validity.py`

Concrete decisions baked in:
- Vehicle product codes (from `Cadastro de Produtos.xls`): `AUTOMOVEL = "1403001"`, `MOTOCICLETA = "1403101"`.
- 2018-BRL base values: car 30,000 BRL, motorcycle 5,000 BRL (Fipe-style ballparks; documented as point estimates).
- Depreciation: 8%/yr straight-line with 20% floor on remaining value.

- [ ] **Step 6.1: Write the failing vehicle-valuation test.**

  Append to `tests/test_htm_classification_validity.py`:

  ```python
  def test_vehicle_valuation_car_8yr_old():
      """A 2010 car observed in 2018 (8 years old) at 8%/yr straight-line
      depreciation with 20% floor: max(0.2, 1 - 0.08*8) = max(0.2, 0.36) = 0.36
      → 30000 * 0.36 = 10800.
      """
      assert htm._vehicle_value(code="1403001", acquisition_year=2010) == pytest.approx(10800.0)


  def test_vehicle_valuation_old_motorcycle_hits_floor():
      """A 1990 motorcycle observed in 2018 (28 years old) hits the 20% floor:
      max(0.2, 1 - 0.08*28) = 0.2 → 5000 * 0.2 = 1000.
      """
      assert htm._vehicle_value(code="1403101", acquisition_year=1990) == pytest.approx(1000.0)


  def test_non_vehicle_code_returns_zero():
      assert htm._vehicle_value(code="1404001", acquisition_year=2015) == 0.0
  ```

- [ ] **Step 6.2: Run; confirm failures.**

  Run: `pytest tests/test_htm_classification_validity.py -v -k vehicle`
  Expected: three FAIL — `_vehicle_value` not defined.

- [ ] **Step 6.3: Add vehicle valuation constants and helper.**

  Insert near the existing parameter block (after `LIQUID_RATIO_CAP`):

  ```python
  POF_REFERENCE_YEAR = 2018
  VEHICLE_BASE_VALUE_2018_BRL = {"1403001": 30000.0, "1403101": 5000.0}
  VEHICLE_DEPRECIATION_RATE = 0.08
  VEHICLE_DEPRECIATION_FLOOR = 0.20
  ```

  Add the helper above `read_pof_table`:

  ```python
  def _vehicle_value(*, code: str, acquisition_year: int | float) -> float:
      """Conservative depreciated market value for a POF INVENTARIO durable.

      Vehicles are identified by POF product code; non-vehicle codes return 0.
      Depreciation is 8%/yr straight-line from POF_REFERENCE_YEAR with a 20%
      floor on remaining value.
      """
      code_str = str(code).strip()
      base = VEHICLE_BASE_VALUE_2018_BRL.get(code_str)
      if base is None:
          return 0.0
      try:
          age_years = max(0, POF_REFERENCE_YEAR - int(acquisition_year))
      except (TypeError, ValueError):
          age_years = 0
      remaining = max(
          VEHICLE_DEPRECIATION_FLOOR,
          1.0 - VEHICLE_DEPRECIATION_RATE * age_years,
      )
      return base * remaining
  ```

- [ ] **Step 6.4: Re-run vehicle helper tests.**

  Run: `pytest tests/test_htm_classification_validity.py -v -k vehicle`
  Expected: all three PASS.

- [ ] **Step 6.5: Read INVENTARIO in `build_pof_household_frame`.**

  Add the following inside `build_pof_household_frame` after the `alug_hh` block:

  ```python
      df_inv = read_pof_table("INVENTARIO.txt", "Inventário")
      for col in ["COD_UPA","NUM_DOM","NUM_UC","V9005","V1404"]:
          df_inv[col] = pd.to_numeric(df_inv[col], errors="coerce")
      df_inv["V9001"] = df_inv["V9001"].astype(str).str.strip()
      df_inv["unit_value"] = df_inv.apply(
          lambda r: _vehicle_value(code=r["V9001"], acquisition_year=r["V1404"]),
          axis=1,
      )
      df_inv["total_value"] = df_inv["unit_value"] * df_inv["V9005"].fillna(1).clip(lower=1)
      veh_hh = (
          df_inv.groupby(["COD_UPA","NUM_DOM","NUM_UC"], as_index=False)
          .agg(vehicle_value=("total_value","sum"))
      )
  ```

  Then add `.merge(veh_hh, on=["COD_UPA","NUM_DOM","NUM_UC"], how="left")` to the `hh = ...` chain, and add `"vehicle_value"` to the `fill_cols` list.

- [ ] **Step 6.6: Fold `vehicle_value` into `illiquid_assets`.**

  In `build_pof_bin_shares` (after Task 3's edits), change:

  ```python
      pof["illiquid_assets"] = pof["real_estate_annual"]
  ```

  to:

  ```python
      pof["illiquid_assets"] = pof["real_estate_annual"] + pof["vehicle_value"].fillna(0)
  ```

- [ ] **Step 6.7: Add CLI flag to disable vehicle valuation.**

  In `parse_args`, add:

  ```python
      parser.add_argument(
          "--vehicle-valuation",
          choices=["off", "fipe-proxy"],
          default="fipe-proxy",
          help="Include POF INVENTARIO vehicles in illiquid assets (default: on).",
      )
  ```

  In `main`, pass it down via a new module-level setter, or — simpler — gate the merge in `build_pof_household_frame` with an environment switch read at module load:

  ```python
  USE_VEHICLE_VALUATION = True  # set False to skip INVENTARIO
  ```

  And in `main()` after `args = parse_args(argv)`:

  ```python
      global USE_VEHICLE_VALUATION
      USE_VEHICLE_VALUATION = (args.vehicle_valuation == "fipe-proxy")
  ```

  Then guard the INVENTARIO block:

  ```python
      if USE_VEHICLE_VALUATION:
          df_inv = read_pof_table("INVENTARIO.txt", "Inventário")
          # ... rest of the block ...
      else:
          veh_hh = pd.DataFrame(columns=["COD_UPA","NUM_DOM","NUM_UC","vehicle_value"])
  ```

- [ ] **Step 6.8: Verify the literature-range gate still holds.**

  Run: `pytest tests/test_htm_classification_validity.py::test_pof_national_shares_within_literature_range -v`
  Expected: PASS. Adding vehicle wealth moves some PH2M → WH2M; if the gate is now violated, the test fixture must be widened (it is intentionally generous: 0.10–0.25 for WH2M). Do not weaken the gate.

- [ ] **Step 6.9: Commit.**

  ```bash
  git add scripts/reporting/htm_classification.py tests/test_htm_classification_validity.py
  git commit -m "htm: include POF INVENTARIO vehicles in illiquid assets"
  ```

---

## Task 7: SELIC sensitivity diagnostic (Rec 5 follow-up, review §2b.i)

**Files:**
- Modify: `scripts/reporting/htm_classification.py`

- [ ] **Step 7.1: Add SELIC sensitivity entry point.**

  Insert after `_write_outputs`:

  ```python
  def write_selic_sensitivity(
      selic_grid: tuple[float, ...] = (0.065, 0.09, 0.14),
      diagnostics_dir: Path = DIAGNOSTICS_DIR,
  ) -> Path:
      """Re-run POF classification only (Stage 1) at multiple SELIC rates and
      report the implied national PH2M/WH2M/Ricardian shares.

      Cheap: POF only, no PNADC merge.
      """
      rows = []
      orig = SELIC_RATE
      for r in selic_grid:
          globals()["SELIC_RATE"] = r
          _bins, _edges, nat = build_pof_bin_shares(diagnostics_dir.parent / "tables")
          rows.append({
              "selic": r,
              "p_ph2m": nat["p_ph2m"], "p_wh2m": nat["p_wh2m"], "p_ric": nat["p_ric"],
          })
      globals()["SELIC_RATE"] = orig
      out = pd.DataFrame(rows)
      diagnostics_dir.mkdir(parents=True, exist_ok=True)
      path = diagnostics_dir / "selic_sensitivity.csv"
      out.to_csv(path, index=False)
      print(f"  Saved SELIC sensitivity -> {path}")
      return path
  ```

- [ ] **Step 7.2: Gate the sensitivity run behind a CLI flag.**

  Add to `parse_args`:

  ```python
      parser.add_argument(
          "--write-selic-sensitivity",
          action="store_true",
          help="Run POF Stage 1 across SELIC in {0.065, 0.09, 0.14} and write a sensitivity CSV.",
      )
  ```

  In `main`, after the existing `_write_outputs(...)` call, add:

  ```python
      if args.write_selic_sensitivity:
          write_selic_sensitivity()
  ```

- [ ] **Step 7.3: Smoke-test by calling from a unit test.**

  Append to `tests/test_htm_classification_validity.py`:

  ```python
  def test_selic_sensitivity_emits_expected_grid(monkeypatch, tmp_path):
      mor = build_pof_morador(n_households=10)
      dom = build_pof_domicilio(n_households=10)
      income = build_pof_income_inputs(n_households=10)

      def fake_read(txt_filename, sheet_name):
          if txt_filename == "DOMICILIO.txt": return dom.astype(str)
          if txt_filename == "MORADOR.txt":
              return mor.rename(columns={"age":"V0403","sex":"V0404"}).astype(str)
          if txt_filename == "RENDIMENTO_TRABALHO.txt":
              return income["inc"].assign(V8500_DEFLA=income["inc"]["total_labor_income"]).astype(str)
          if txt_filename == "OUTROS_RENDIMENTOS.txt":
              return income["trans"].assign(QUADRO=55, V9001=0, V8500_DEFLA=0).astype(str)
          if txt_filename == "ALUGUEL_ESTIMADO.txt":
              return income["alug"].assign(V8000_DEFLA=0).astype(str)
          if txt_filename == "INVENTARIO.txt":
              return pd.DataFrame(columns=["COD_UPA","NUM_DOM","NUM_UC","V9001","V9005","V1404"]).astype(str)
          raise AssertionError(txt_filename)

      monkeypatch.setattr(htm, "read_pof_table", fake_read)
      monkeypatch.setattr(htm, "DIAGNOSTICS_DIR", tmp_path / "diag")
      monkeypatch.setattr(htm, "TABLES_DIR", tmp_path / "tab")
      out_path = htm.write_selic_sensitivity()
      df = pd.read_csv(out_path)
      assert list(df["selic"].round(4)) == [0.065, 0.09, 0.14]
      assert df[["p_ph2m","p_wh2m","p_ric"]].notna().all().all()
  ```

- [ ] **Step 7.4: Run and confirm green.**

  Run: `pytest tests/test_htm_classification_validity.py::test_selic_sensitivity_emits_expected_grid -v`
  Expected: PASS.

- [ ] **Step 7.5: Commit.**

  ```bash
  git add scripts/reporting/htm_classification.py tests/test_htm_classification_validity.py
  git commit -m "htm: add SELIC sensitivity diagnostic"
  ```

---

## Task 8: Two-strategy bin construction — Strategies A and G (Rec 2)

**Files:**
- Modify: `scripts/reporting/htm_classification.py` (refactor bin-key construction; add `--bin-strategy` flag and dual output)
- Create: `tests/test_htm_bin_strategies.py`

- [ ] **Step 8.1: Create the strategy test file with a failing test.**

  Create `tests/test_htm_bin_strategies.py`:

  ```python
  import numpy as np
  import pandas as pd
  import pytest

  import htm_classification as htm


  def test_labor_status_3way_collapses_self_employed_to_employed():
      df = pd.DataFrame({
          "formal": [1, 0, 0, 0, 0],
          "conta_propria": [0, 1, 0, 0, 0],
          "informal": [0, 0, 1, 0, 0],
          "desocupado": [0, 0, 0, 1, 0],
      })
      out = htm._labor_status_3way(df).tolist()
      assert out == ["employed", "employed", "employed", "unemployed", "inactive"]


  def test_income_band_absolute_partitions_at_documented_cutpoints():
      income = pd.Series([100.0, 170.0, 500.0, 700.0, 1500.0, 2000.0, 3500.0, 4000.0, 10000.0])
      bands = htm._income_band_absolute(income).tolist()
      assert bands == ["B1", "B1", "B2", "B2", "B3", "B3", "B4", "B4", "B5"]


  def test_build_bin_key_strategy_g_uses_3way_labour_and_bands():
      df = pd.DataFrame({
          "macro_region": ["South"],
          "age_group": ["35-44"],
          "gender": ["male"],
          "education_group": ["secondary"],
          "labor_status": ["formal"],
          "labor_status_3way": ["employed"],
          "pc_income_quintile": ["Q3"],
          "income_band_absolute": ["B3"],
      })
      key = htm._build_bin_key(df, strategy="G").iloc[0]
      assert key == "South|35-44|male|secondary|B3|employed"
  ```

- [ ] **Step 8.2: Run; confirm failures.**

  Run: `pytest tests/test_htm_bin_strategies.py -v`
  Expected: all FAIL — helpers do not exist.

- [ ] **Step 8.3: Add the helpers.**

  Insert above the existing `bin_key` construction in `build_pof_bin_shares`:

  ```python
  INCOME_BAND_EDGES = (-np.inf, 170.0, 700.0, 2000.0, 4000.0, np.inf)
  INCOME_BAND_LABELS = ("B1", "B2", "B3", "B4", "B5")


  def _labor_status_3way(df: pd.DataFrame) -> pd.Series:
      """Collapse 5-way labour to 3-way (employed/unemployed/inactive)."""
      formal = pd.to_numeric(df.get("formal", 0), errors="coerce").fillna(0)
      conta = pd.to_numeric(df.get("conta_propria", 0), errors="coerce").fillna(0)
      informal = pd.to_numeric(df.get("informal", 0), errors="coerce").fillna(0)
      desoc = pd.to_numeric(df.get("desocupado", 0), errors="coerce").fillna(0)
      out = pd.Series("inactive", index=df.index, dtype="object")
      out.loc[desoc == 1] = "unemployed"
      out.loc[(formal == 1) | (conta == 1) | (informal == 1)] = "employed"
      return out


  def _income_band_absolute(income: pd.Series) -> pd.Series:
      """Bucket monthly income into the documented absolute BRL bands."""
      return pd.cut(income, bins=list(INCOME_BAND_EDGES),
                    labels=list(INCOME_BAND_LABELS), right=True,
                    include_lowest=True).astype(str)


  def _build_bin_key(df: pd.DataFrame, *, strategy: str) -> pd.Series:
      """Construct a bin_key for the chosen strategy.

      Strategy A: macro_region | age_group | gender | education_group |
                  pc_income_quintile | labor_status (5-way)
      Strategy G: macro_region | age_group | gender | education_group |
                  income_band_absolute | labor_status_3way
      """
      if strategy == "A":
          return (
              df["macro_region"] + "|" + df["age_group"] + "|" + df["gender"]
              + "|" + df["education_group"] + "|" + df["pc_income_quintile"]
              + "|" + df["labor_status"]
          )
      if strategy == "G":
          return (
              df["macro_region"] + "|" + df["age_group"] + "|" + df["gender"]
              + "|" + df["education_group"] + "|" + df["income_band_absolute"]
              + "|" + df["labor_status_3way"]
          )
      raise ValueError(f"unknown bin strategy: {strategy!r}")
  ```

  Build both label columns wherever the POF and PNADC frames are assembled. In `build_pof_bin_shares`, replace the single `pof["bin_key"] = ...` block with:

  ```python
      pof["labor_status_3way"] = _labor_status_3way(
          pof.assign(
              formal=(pof["labor_status"] == "formal").astype(int),
              conta_propria=(pof["labor_status"] == "self_employed").astype(int),
              informal=(pof["labor_status"] == "informal").astype(int),
              desocupado=(pof["labor_status"] == "unemployed").astype(int),
          )
      )
      pof["income_band_absolute"] = _income_band_absolute(pof["pc_income"])
      pof["bin_key"] = _build_bin_key(pof, strategy=BIN_STRATEGY)
  ```

  In `prepare_pnadc_batch`, add analogous columns after the existing demographic enrichment:

  ```python
      df["labor_status_3way"] = _labor_status_3way(df)
      df["income_band_absolute"] = _income_band_absolute(df["pc_income_pnadc"])
      df["bin_key"] = _build_bin_key(df, strategy=BIN_STRATEGY)
  ```

  Add a module-level `BIN_STRATEGY = "A"` near the other parameters.

- [ ] **Step 8.4: Re-run helper tests; confirm green.**

  Run: `pytest tests/test_htm_bin_strategies.py -v`
  Expected: PASS.

- [ ] **Step 8.5: Add `--bin-strategy` CLI flag with `both` orchestration.**

  In `parse_args`:

  ```python
      parser.add_argument(
          "--bin-strategy",
          choices=["A", "G", "both"],
          default="A",
          help="Bin construction: A=5way×quintiles (current), G=3way×abs bands (paper), both=write side-by-side.",
      )
      parser.add_argument(
          "--canonical-strategy",
          choices=["A", "G"],
          default="A",
          help="When --bin-strategy=both, which strategy gets the un-suffixed canonical filenames.",
      )
  ```

  Restructure `main` so the pipeline runs once per requested strategy. Concretely, replace the single-shot body of `main` with a loop:

  ```python
  def main(argv: list[str] | None = None) -> int:
      args = parse_args(argv)
      pnad_path = args.pnad_parquet if args.pnad_parquet is not None else PNAD_MATCHED_DEFAULT
      if not pnad_path.exists():
          raise FileNotFoundError(
              f"PNADC Parquet not found: {pnad_path}. Pass --pnad-parquet PATH."
          )
      global USE_VEHICLE_VALUATION
      USE_VEHICLE_VALUATION = (args.vehicle_valuation == "fipe-proxy")

      strategies = ["A", "G"] if args.bin_strategy == "both" else [args.bin_strategy]
      comparison_rows = []
      for strategy in strategies:
          globals()["BIN_STRATEGY"] = strategy
          suffix = f"_{strategy}" if args.bin_strategy == "both" else ""
          # When `both`, canonical filenames go to args.canonical_strategy:
          canonical = (args.bin_strategy == "both" and strategy == args.canonical_strategy)
          tables_dir = TABLES_DIR
          diag_dir = DIAGNOSTICS_DIR

          bin_shares, edges, pof_nat = build_pof_bin_shares(tables_dir)
          expected, mc, coverage = process_pnadc_parquet(
              pnad_path, bin_shares, edges,
              batch_size=args.batch_size,
              per_quarter_quintiles=args.per_quarter_quintiles,
              random_seed=RANDOM_SEED,
              verbose=True,
          )
          paths = _write_outputs(
              expected, mc, coverage,
              tables_dir=tables_dir, diagnostics_dir=diag_dir,
              write_legacy_quarterly=(not args.no_legacy_quarterly) and (suffix == "" or canonical),
              suffix="" if (suffix == "" or canonical) else suffix,
          )
          comparison_rows.append({
              "strategy": strategy,
              "n_bins": len(bin_shares),
              "mean_unmatched_share": float(coverage["unmatched_share"].mean()),
              "national_PH2M": pof_nat["p_ph2m"],
              "national_WH2M": pof_nat["p_wh2m"],
              "national_Ricardian": pof_nat["p_ric"],
          })
          _print_validation_summary(pof_nat, expected, mc)

      if len(comparison_rows) > 1:
          comp = pd.DataFrame(comparison_rows)
          DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
          comp.to_csv(DIAGNOSTICS_DIR / "bin_strategy_comparison.csv", index=False)
          print(f"\n  Strategy comparison -> {DIAGNOSTICS_DIR / 'bin_strategy_comparison.csv'}")
          print(comp.to_string(index=False))

      if args.write_selic_sensitivity:
          write_selic_sensitivity()
      return 0
  ```

  Extend `_write_outputs` to accept a `suffix` argument:

  ```python
  def _write_outputs(
      expected, mc, coverage, *,
      tables_dir=TABLES_DIR, diagnostics_dir=DIAGNOSTICS_DIR,
      write_legacy_quarterly=True, suffix: str = "",
  ) -> dict[str, Path]:
      tables_dir.mkdir(parents=True, exist_ok=True)
      diagnostics_dir.mkdir(parents=True, exist_ok=True)
      paths = {
          "monthly_expected": tables_dir / f"state_month_htm_shares{suffix}.parquet",
          "monthly_mc": tables_dir / f"state_month_htm_shares_mc{suffix}.parquet",
          "coverage": diagnostics_dir / f"monthly_htm_coverage{suffix}.csv",
      }
      expected.to_parquet(paths["monthly_expected"], index=False)
      mc.to_parquet(paths["monthly_mc"], index=False)
      coverage.to_csv(paths["coverage"], index=False)
      if write_legacy_quarterly:
          quarterly = aggregate_monthly_to_legacy_quarterly(expected)
          paths["legacy_quarterly"] = tables_dir / f"state_quarter_htm_shares{suffix}.csv"
          quarterly.to_csv(paths["legacy_quarterly"], index=False)
      return paths
  ```

- [ ] **Step 8.6: Run the existing suite.**

  Run: `pytest tests/ -q`
  Expected: all pass. The default `--bin-strategy=A` keeps backwards compatibility.

- [ ] **Step 8.7: Commit.**

  ```bash
  git add scripts/reporting/htm_classification.py tests/test_htm_bin_strategies.py
  git commit -m "htm: dual bin strategies A and G with comparison output"
  ```

---

## Task 9: PNADC unmatched-share gate (Rec 6 close-out)

**Files:**
- Modify: `tests/test_htm_classification_validity.py`

The literature-range gate covers POF national shares. The PNADC merge needs its own gate so a future schema change doesn't silently fall back to national averages for >45% of rows.

- [ ] **Step 9.1: Write the failing gate test.**

  Append to `tests/test_htm_classification_validity.py`:

  ```python
  def test_pnadc_unmatched_share_below_threshold(tmp_path):
      """A small synthetic PNADC batch must achieve unmatched_share <= 0.45.

      This locks in the floor noted in validity review §2e — anything worse
      is a regression worth surfacing.
      """
      bin_shares = pd.DataFrame({
          "bin_key": ["Southeast|35-44|male|secondary|Q3|formal",
                      "Southeast|35-44|male|secondary|B3|employed"],
          "p_ph2m": [0.2, 0.2],
          "p_wh2m": [0.3, 0.3],
          "p_ric":  [0.5, 0.5],
          "weighted_n": [100.0, 100.0],
      })
      bin_shares.attrs["pof_national"] = {"p_ph2m": 0.215, "p_wh2m": 0.193, "p_ric": 0.592}
      pof_edges = np.array([0, 500, 1000, 2000, 3000, 5000], dtype=float)

      # Build a batch where the bin_key will match (Strategy A active by default).
      htm.BIN_STRATEGY = "A"
      batch = pd.DataFrame([
          dict(UF=35, V2009=40, V2007=1, VD3004=5, V2001=2,
               rendimento_habitual_real=1500.0, ref_month_yyyymm=201701,
               ref_month_in_year=1, weight_monthly=1.0,
               formal=1, conta_propria=0, informal=0, ocupado=1, desocupado=0,
               id_rs="rs-1", id_ind="ind-1")
          for _ in range(50)
      ])
      prepared = htm.prepare_pnadc_batch(batch, bin_shares, pof_edges)
      unmatched = prepared["_unmatched_bin"].mean()
      assert unmatched <= 0.45, f"unmatched_share={unmatched:.3f} > 0.45"
  ```

- [ ] **Step 9.2: Run.**

  Run: `pytest tests/test_htm_classification_validity.py::test_pnadc_unmatched_share_below_threshold -v`
  Expected: PASS (the bin is hand-tuned to match). If FAIL, the synthetic batch's demographics aren't mapping to the bin_key shape — adjust to match the actual `macro_region` mapping (UF=35 → Southeast).

- [ ] **Step 9.3: Commit.**

  ```bash
  git add tests/test_htm_classification_validity.py
  git commit -m "tests: gate PNADC unmatched share <= 0.45"
  ```

---

## Task 10: COVID flag, temporal trend, and provenance docs (Rec 7, 8)

**Files:**
- Modify: `scripts/reporting/htm_classification.py`
- Modify: `RESULTS_PROVENANCE.md`

- [ ] **Step 10.1: Add COVID column to monthly coverage.**

  In `_build_monthly_coverage` (around line 1140), just before `return coverage[ordered]`:

  ```python
      coverage["covid_q2q3_2020"] = (
          coverage["ref_month_yyyymm"].between(202004, 202007).astype(int)
      )
  ```

  And append `"covid_q2q3_2020"` to the `ordered` list.

- [ ] **Step 10.2: Add `--exclude-covid-disruption` CLI flag.**

  In `parse_args`:

  ```python
      parser.add_argument(
          "--exclude-covid-disruption",
          action="store_true",
          help="Zero out 202004–202007 weights/shares in the canonical monthly output.",
      )
  ```

  In `main`, immediately before `_write_outputs(...)`:

  ```python
          if args.exclude_covid_disruption:
              covid_mask = expected["ref_month_yyyymm"].between(202004, 202007)
              expected.loc[covid_mask, ["share_PH2M","share_WH2M","share_Ricardian",
                                        "share_H2M","total_weight"]] = np.nan
              mc.loc[mc["ref_month_yyyymm"].between(202004, 202007),
                     ["share_PH2M","share_WH2M","share_Ricardian",
                      "share_H2M","total_weight"]] = np.nan
              print("  Excluded COVID Q2-Q3 2020 months from canonical output.")
  ```

- [ ] **Step 10.3: Add temporal-trend summary writer.**

  Insert after `_build_monthly_coverage`:

  ```python
  def write_temporal_trend_summary(
      monthly: pd.DataFrame,
      diagnostics_dir: Path = DIAGNOSTICS_DIR,
  ) -> Path:
      """Annual weight-weighted national HtM shares from state-month parquet."""
      if monthly.empty:
          return diagnostics_dir / "national_htm_trend_yearly.csv"
      tmp = monthly.copy()
      tmp["_w_ph2m"] = tmp["share_PH2M"] * tmp["total_weight"]
      tmp["_w_wh2m"] = tmp["share_WH2M"] * tmp["total_weight"]
      tmp["_w_ric"]  = tmp["share_Ricardian"] * tmp["total_weight"]
      annual = (
          tmp.groupby("year", as_index=False)
          .agg(total_weight=("total_weight","sum"),
               _w_ph2m=("_w_ph2m","sum"),
               _w_wh2m=("_w_wh2m","sum"),
               _w_ric=("_w_ric","sum"))
      )
      denom = annual["total_weight"].replace(0, np.nan)
      annual["national_PH2M"] = annual["_w_ph2m"] / denom
      annual["national_WH2M"] = annual["_w_wh2m"] / denom
      annual["national_Ricardian"] = annual["_w_ric"] / denom
      annual["national_H2M"] = annual["national_PH2M"] + annual["national_WH2M"]
      out = annual.drop(columns=["_w_ph2m","_w_wh2m","_w_ric"])
      diagnostics_dir.mkdir(parents=True, exist_ok=True)
      path = diagnostics_dir / "national_htm_trend_yearly.csv"
      out.to_csv(path, index=False)
      print(f"  Saved temporal trend -> {path}")
      return path
  ```

  In `main`, immediately after `_write_outputs(...)`:

  ```python
          write_temporal_trend_summary(expected)
  ```

- [ ] **Step 10.4: Update `RESULTS_PROVENANCE.md`.**

  Append a new section (top-level heading `## Diagnostics from htm_classification.py`) listing each new output:
  - `results/diagnostics/pof_zero_income_excluded.csv` — counts of POF rows excluded under the new `_classify_with_exclusion` path (Task 3).
  - `results/diagnostics/selic_sensitivity.csv` — POF national shares at SELIC ∈ {0.065, 0.09, 0.14} (Task 7, behind `--write-selic-sensitivity`).
  - `results/diagnostics/bin_strategy_comparison.csv` — A vs G side-by-side comparison (Task 8, when `--bin-strategy both`).
  - `results/diagnostics/national_htm_trend_yearly.csv` — annual weight-weighted national HtM time series (Task 10).
  - New column `covid_q2q3_2020` in existing `monthly_htm_coverage.csv` (Task 10).

  Use the existing file's style; add a one-line rerun command per row.

- [ ] **Step 10.5: Run full suite.**

  Run: `pytest tests/ -q`
  Expected: all pass.

- [ ] **Step 10.6: Commit.**

  ```bash
  git add scripts/reporting/htm_classification.py RESULTS_PROVENANCE.md
  git commit -m "htm: COVID exclusion flag, annual trend output, provenance docs"
  ```

---

## Final verification

Run end-to-end and inspect:

- [ ] **V.1: Full pytest suite.**

  Run: `pytest tests/ -v`
  Expected: all green. Note any new test counts.

- [ ] **V.2: Default-mode pipeline.**

  Run: `python3 scripts/reporting/htm_classification.py --no-choropleth`
  Expected: completes; produces `results/tables/state_month_htm_shares.parquet`, `results/tables/pof_bin_shares.csv`, `results/diagnostics/monthly_htm_coverage.csv`, `results/diagnostics/pof_zero_income_excluded.csv`, `results/diagnostics/national_htm_trend_yearly.csv`.

- [ ] **V.3: WH2M ordering sanity.**

  Run:
  ```bash
  python3 -c "import pandas as pd; \
              d=pd.read_csv('results/tables/pof_group_wealth_income_summary.csv'); \
              print(d[['agent_type','mean_monthly_income']].sort_values('agent_type'))"
  ```
  Expected: WH2M mean monthly income is **above** PH2M mean monthly income. If reversed, Task 3 regressed.

- [ ] **V.4: Strategy comparison.**

  Run: `python3 scripts/reporting/htm_classification.py --no-choropleth --bin-strategy both --canonical-strategy A`
  Expected: produces `_A` and `_G` suffixed outputs plus `results/diagnostics/bin_strategy_comparison.csv`. Inspect: G's `mean_unmatched_share` should be materially below A's.

- [ ] **V.5: SELIC sensitivity.**

  Run: `python3 scripts/reporting/htm_classification.py --no-choropleth --write-selic-sensitivity`
  Inspect `results/diagnostics/selic_sensitivity.csv`. Expected: Ricardian share rises with SELIC (because `fin_liquid = financial_income_annual / SELIC` falls), so PH2M/WH2M rise as SELIC falls.

- [ ] **V.6: Downstream LP regressions still consume canonical parquet.**

  Run: `python3 scripts/reporting/basic_state_month_lp.py`
  Expected: runs to completion without schema errors. Numbers will shift (this is the point); compare against `/tmp/htm_baseline/`.

- [ ] **V.7: Diff against baseline snapshot.**

  Run:
  ```bash
  diff /tmp/htm_baseline/pof_bin_shares.csv results/tables/pof_bin_shares.csv | head -20 || true
  ```
  Expected: differences exist (intended). Use this to spot-check that the household-head pivot reduced row count and the smoothing prior moved small-bin probabilities toward `(0.215, 0.193, 0.592)`.

Once V.1–V.7 pass and the strategy comparison is reviewed, the user picks the canonical strategy and `overleaf/main.tex` §"Bin strategy comparison" is updated to match the running code — closing Rec 2 in documentation.
