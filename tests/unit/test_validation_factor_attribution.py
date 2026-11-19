"""Factor attribution: known answers, an independent recomputation, K = 1 equality, coverage.

Oracles here are the test's own code (``numpy.linalg.lstsq`` and a hand-written Newey and West
(1987) loop), never the module's helpers. They live in ``tests/unit`` because no oracle file may
be added to the protected ``tests/oracles`` folder without the owner.
"""

import math
from typing import Any

import numpy as np
import pytest
from scipy import stats

from alpha_core import DataError
from alpha_validation import factor_attribution as fa
from alpha_validation.attribution import market_attribution
from alpha_validation.factor_attribution import (
    MAX_CONDITION_NUMBER,
    factor_attribution,
    min_observations,
)

PPY = 252
Z95 = 1.959963984540054


def _ar1(rng: np.random.Generator, n: int, phi: float) -> np.ndarray:
    shocks = rng.normal(0.0, 1.0, n + 50)
    out = np.zeros(n + 50)
    for t in range(1, n + 50):
        out[t] = phi * out[t - 1] + shocks[t]
    return out[50:]


def _data(n: int, k: int, seed: int, phi: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    if phi > 0.0:
        x = np.column_stack([_ar1(rng, n, phi) for _ in range(k)]) * 0.01
        e = _ar1(rng, n, phi) * 0.004
    else:
        x = rng.normal(0.0004, 0.01, (n, k))
        e = rng.normal(0.0, 0.004, n)
    beta = np.linspace(0.8, -0.3, k)
    return 0.0002 + x @ beta + e, x


def _names(k: int) -> list[str]:
    return [f"f{i}" for i in range(k)]


def _oracle(y: np.ndarray, x: np.ndarray, lags: int) -> dict[str, Any]:
    """Plain lstsq plus a hand-written Bartlett-kernel Newey-West covariance, from the formula."""
    n, k = x.shape
    design = np.column_stack([np.ones(n), x])
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ coef
    xtx_inv = np.linalg.inv(design.T @ design)
    meat = np.zeros((k + 1, k + 1))
    for lag in range(lags + 1):
        for t in range(lag, n):
            term = resid[t] * resid[t - lag] * np.outer(design[t], design[t - lag])
            if lag == 0:
                meat += term
            else:
                meat += (1.0 - lag / (lags + 1.0)) * (term + term.T)
    cov = xtx_inv @ meat @ xtx_inv * n / (n - (k + 1))
    ssr = float(resid @ resid)
    tss = float(np.sum((y - y.mean()) ** 2))
    return {
        "coef": coef,
        "se": np.sqrt(np.diag(cov)),
        "r2": 1.0 - ssr / tss,
        "adj": 1.0 - (1.0 - (1.0 - ssr / tss)) * (n - 1) / (n - k - 1),
        "resid_sd": math.sqrt(ssr / (n - k - 1)),
        "cond": float(np.linalg.cond(design / np.linalg.norm(design, axis=0))),
    }


def test_noiseless_plane_is_recovered_exactly() -> None:
    # Exact algebra: with no noise, OLS must return the planted coefficients to rounding (1e-10).
    rng = np.random.default_rng(3)
    x = rng.normal(0.0, 0.01, (120, 2))
    y = 0.001 + 0.7 * x[:, 0] - 0.4 * x[:, 1]
    out = factor_attribution(y, x, periods_per_year=PPY, factor_names=["a", "b"])
    assert out["alpha_per_period"] == pytest.approx(0.001, abs=1e-10)
    assert out["factors"][0]["beta"] == pytest.approx(0.7, abs=1e-10)
    assert out["factors"][1]["beta"] == pytest.approx(-0.4, abs=1e-10)
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-10)
    assert out["residual_std"] == pytest.approx(0.0, abs=1e-10)


def test_orthogonal_factors_give_the_single_factor_betas() -> None:
    # Orthogonal, centred factors: each multi-factor beta is cov(y, x_j) / var(x_j) (1e-10).
    rng = np.random.default_rng(5)
    n = 400
    x1 = rng.normal(0.0, 1.0, n)
    x2 = rng.normal(0.0, 1.0, n)
    x1 -= x1.mean()
    x2 -= x2.mean()
    x2 -= x1 * (x1 @ x2) / (x1 @ x1)
    y = 0.01 + 0.5 * x1 - 0.8 * x2 + rng.normal(0.0, 0.3, n)
    both = factor_attribution(
        y, np.column_stack([x1, x2]), periods_per_year=PPY, factor_names=["a", "b"]
    )
    for j, xj in enumerate((x1, x2)):
        single = float(np.cov(y, xj, ddof=0)[0, 1] / np.var(xj))
        assert both["factors"][j]["beta"] == pytest.approx(single, abs=1e-10)
        alone = factor_attribution(y, xj[:, None], periods_per_year=PPY, factor_names=["a"])
        assert alone["factors"][0]["beta"] == pytest.approx(single, abs=1e-10)


@pytest.mark.parametrize(("k", "phi"), [(1, 0.0), (3, 0.5), (4, 0.7)])
def test_matches_an_independent_recomputation(k: int, phi: float) -> None:
    # Different arithmetic order in lstsq and a double loop: agreement to 1e-10 relative.
    y, x = _data(250, k, seed=20 + k, phi=phi)
    out = factor_attribution(y, x, periods_per_year=PPY, factor_names=_names(k))
    lags = int(math.floor(4 * (250 / 100) ** (2 / 9)))
    ref = _oracle(y, x, lags)
    assert out["hac_lags"] == lags
    assert out["alpha_per_period"] == pytest.approx(ref["coef"][0], rel=1e-10)
    assert out["alpha_se"] == pytest.approx(ref["se"][0], rel=1e-10)
    for j in range(k):
        row = out["factors"][j]
        assert row["name"] == f"f{j}"
        assert row["beta"] == pytest.approx(ref["coef"][j + 1], rel=1e-10)
        assert row["se"] == pytest.approx(ref["se"][j + 1], rel=1e-10)
        assert row["t"] == pytest.approx(ref["coef"][j + 1] / ref["se"][j + 1], rel=1e-10)
        p = 2.0 * stats.norm.sf(abs(row["t"]))
        assert row["p"] == pytest.approx(p, rel=1e-10)
        half = Z95 * ref["se"][j + 1]
        assert row["ci95"][0] == pytest.approx(ref["coef"][j + 1] - half, rel=1e-9, abs=1e-12)
        assert row["ci95"][1] == pytest.approx(ref["coef"][j + 1] + half, rel=1e-9, abs=1e-12)
    assert out["r_squared"] == pytest.approx(ref["r2"], abs=1e-10)
    assert out["adj_r_squared"] == pytest.approx(ref["adj"], abs=1e-10)
    assert out["residual_std"] == pytest.approx(ref["resid_sd"], rel=1e-10)
    assert out["condition_number"] == pytest.approx(ref["cond"], rel=1e-9)
    assert out["n"] == 250
    assert out["k"] == k


def test_one_factor_reproduces_market_attribution() -> None:
    # Same OLS, same HAC lag rule and small-sample factor: equal to rounding (1e-12).
    y, x = _data(500, 1, seed=11, phi=0.4)
    new = factor_attribution(y, x, periods_per_year=PPY, factor_names=["mkt"])
    old = market_attribution(y, x[:, 0], periods_per_year=PPY)
    row = new["factors"][0]
    assert row["beta"] == pytest.approx(old["beta"], abs=1e-12)
    assert row["se"] == pytest.approx(old["beta_se"], abs=1e-12)
    assert row["ci95"][0] == pytest.approx(old["beta_ci95"][0], abs=1e-12)
    assert row["ci95"][1] == pytest.approx(old["beta_ci95"][1], abs=1e-12)
    assert new["alpha_per_period"] == pytest.approx(old["alpha_per_bar"], abs=1e-12)
    assert new["alpha_annual"] == pytest.approx(old["alpha_annual"], abs=1e-12)
    assert new["alpha_t"] == pytest.approx(old["alpha_t"], abs=1e-9)
    assert new["alpha_p"] == pytest.approx(old["alpha_p"], abs=1e-12)
    assert new["r_squared"] == pytest.approx(old["r_squared"], abs=1e-12)
    assert new["hac_lags"] == old["hac_lags"]


def test_alpha_annualisation_and_interval() -> None:
    # alpha_annual = per-period alpha * periods_per_year; the interval scales the same way.
    y, x = _data(300, 2, seed=8)
    out = factor_attribution(y, x, periods_per_year=52, factor_names=["a", "b"])
    assert out["alpha_annual"] == pytest.approx(out["alpha_per_period"] * 52, rel=1e-12)
    lo, hi = out["alpha_ci95_per_period"]
    assert lo == pytest.approx(out["alpha_per_period"] - Z95 * out["alpha_se"], rel=1e-9)
    assert hi == pytest.approx(out["alpha_per_period"] + Z95 * out["alpha_se"], rel=1e-9)
    assert out["alpha_ci95_annual"][0] == pytest.approx(lo * 52, rel=1e-12)
    assert out["alpha_ci95_annual"][1] == pytest.approx(hi * 52, rel=1e-12)
    assert out["alpha_p"] == pytest.approx(2.0 * stats.norm.sf(abs(out["alpha_t"])), rel=1e-10)


def test_interval_covers_the_true_beta_about_95_percent_of_the_time() -> None:
    # 2,000 seeded simulations, independent errors. The band is the binomial two-sided half-width
    # at z = 3.89 (alpha 1e-4) plus 0.01 for the finite-sample bias of a HAC normal interval.
    sims, n, true_beta = 2000, 300, 0.6
    rng = np.random.default_rng(2024)
    hits = 0
    for _ in range(sims):
        x = rng.normal(0.0, 1.0, (n, 2))
        y = 0.1 + true_beta * x[:, 0] - 0.2 * x[:, 1] + rng.normal(0.0, 1.0, n)
        out = factor_attribution(y, x, periods_per_year=PPY, factor_names=["a", "b"])
        lo, hi = out["factors"][0]["ci95"]
        hits += int(lo <= true_beta <= hi)
    band = 3.89 * math.sqrt(0.95 * 0.05 / sims) + 0.01
    assert hits / sims == pytest.approx(0.95, abs=band)


def test_hac_interval_is_wider_than_plain_ols_under_autocorrelated_errors() -> None:
    # Positively autocorrelated factor and errors: HAC se must exceed the iid OLS se.
    y, x = _data(600, 1, seed=31, phi=0.8)
    out = factor_attribution(y, x, periods_per_year=PPY, factor_names=["f"])
    design = np.column_stack([np.ones(600), x])
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ coef
    ols_se = math.sqrt(float(resid @ resid) / 598 * np.linalg.inv(design.T @ design)[1, 1])
    assert out["factors"][0]["se"] > 1.2 * ols_se


def test_identical_factors_are_rejected_by_name() -> None:
    y, x = _data(120, 2, seed=1)
    dup = np.column_stack([x[:, 0], x[:, 0]])
    with pytest.raises(DataError, match="f0.*f1|f1.*f0"):
        factor_attribution(y, dup, periods_per_year=PPY, factor_names=["f0", "f1"])


def test_nearly_identical_factors_are_rejected_by_the_bound() -> None:
    y, x = _data(200, 1, seed=2)
    rng = np.random.default_rng(9)
    near = np.column_stack([x[:, 0], x[:, 0] + rng.normal(0.0, 1e-4, 200)])
    with pytest.raises(DataError, match="condition number"):
        factor_attribution(y, near, periods_per_year=PPY, factor_names=["f0", "f1"])


def test_correlated_but_distinct_factors_are_accepted() -> None:
    # Correlation 0.9 gives a scaled condition number near 4, far under the bound.
    rng = np.random.default_rng(4)
    a = rng.normal(0.0, 0.01, 300)
    b = 0.9 * a + math.sqrt(1 - 0.81) * rng.normal(0.0, 0.01, 300)
    y = 0.5 * a + 0.2 * b + rng.normal(0.0, 0.004, 300)
    out = factor_attribution(
        y, np.column_stack([a, b]), periods_per_year=PPY, factor_names=["a", "b"]
    )
    assert 1.0 < out["condition_number"] < MAX_CONDITION_NUMBER


def test_minimum_observations_rule() -> None:
    # Convention max(36, 10 * (K + 1)): 36 for K <= 2, then 10 per parameter.
    assert min_observations(1) == 36
    assert min_observations(2) == 36
    assert min_observations(3) == 40
    assert min_observations(7) == 80
    assert fa.MIN_OBSERVATIONS_FLOOR == 36
    assert fa.OBSERVATIONS_PER_PARAMETER == 10
    y, x = _data(36, 1, seed=6)
    factor_attribution(y, x, periods_per_year=PPY, factor_names=["a"])
    y, x = _data(35, 1, seed=6)
    with pytest.raises(DataError, match="at least 36"):
        factor_attribution(y, x, periods_per_year=PPY, factor_names=["a"])
    y, x = _data(49, 4, seed=6)
    with pytest.raises(DataError, match="at least 50"):
        factor_attribution(y, x, periods_per_year=PPY, factor_names=_names(4))
    y, x = _data(50, 4, seed=6)
    factor_attribution(y, x, periods_per_year=PPY, factor_names=_names(4))


def test_bad_inputs_fail_loud() -> None:
    y, x = _data(100, 2, seed=7)
    names = ["a", "b"]

    def call(yy: Any, xx: Any, nn: Any = names, ppy: int = PPY) -> None:
        factor_attribution(yy, xx, periods_per_year=ppy, factor_names=nn)

    bad = y.copy()
    bad[3] = np.nan
    with pytest.raises(DataError, match="strategy"):
        call(bad, x)
    inf = x.copy()
    inf[5, 1] = np.inf
    with pytest.raises(DataError, match="factors"):
        call(y, inf)
    with pytest.raises(DataError, match="length"):
        call(y[:-1], x)
    with pytest.raises(DataError, match="duplicate"):
        call(y, x, ["a", "a"])
    with pytest.raises(DataError, match="factor_names"):
        call(y, x, ["a"])
    with pytest.raises(DataError, match="two-dimensional"):
        call(y, x[:, 0])
    with pytest.raises(DataError, match="one-dimensional"):
        call(x, x)
    with pytest.raises(DataError, match="periods_per_year"):
        call(y, x, ppy=0)
    with pytest.raises(DataError, match="strategy"):
        call(np.full(100, 0.01), x)
    flat = x.copy()
    flat[:, 1] = 0.02
    with pytest.raises(DataError, match="'b'"):
        call(y, flat)
    with pytest.raises(DataError, match="at least one"):
        call(y, np.zeros((100, 0)), [])


def test_same_inputs_same_outputs_and_no_global_random_state() -> None:
    y, x = _data(150, 3, seed=12, phi=0.3)
    np.random.seed(77)
    before = np.random.get_state(legacy=False)["state"]["key"].copy()
    one = factor_attribution(y, x, periods_per_year=PPY, factor_names=_names(3))
    two = factor_attribution(y, x, periods_per_year=PPY, factor_names=_names(3))
    after = np.random.get_state(legacy=False)["state"]["key"]
    assert one == two
    assert np.array_equal(before, after)
