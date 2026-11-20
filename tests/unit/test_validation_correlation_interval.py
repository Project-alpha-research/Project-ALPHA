"""Correlation interval: hand-recomputed Fisher interval, invariances, coverage, edge cases.

Oracles are the test's own arithmetic. They live in ``tests/unit`` because no oracle file may be
added to the protected ``tests/oracles`` folder without the owner.
"""

import math
from typing import Any

import numpy as np
import pytest
from scipy import stats

from alpha_core import DataError
from alpha_validation.correlation_interval import correlation_interval

Z95 = 1.959963984540054


def _pair_with_r(r: float, n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Two samples whose Pearson correlation is exactly ``r`` (centred, orthogonal, equal norm)."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0, 1.0, n)
    b = rng.normal(0.0, 1.0, n)
    a -= a.mean()
    b -= b.mean()
    b -= a * (a @ b) / (a @ a)
    b *= math.sqrt(a @ a) / math.sqrt(b @ b)
    return a, r * a + math.sqrt(1.0 - r * r) * b


def test_textbook_fisher_interval_r_half_n_28() -> None:
    # z = atanh(0.5); se = 1 / sqrt(25) = 0.2; interval = tanh(z -+ 1.96 * 0.2). Tolerance 1e-9.
    x, y = _pair_with_r(0.5, 28, seed=1)
    out = correlation_interval(x, y)
    z = math.atanh(0.5)
    assert out["r"] == pytest.approx(0.5, abs=1e-12)
    assert out["n"] == 28
    assert out["z"] == pytest.approx(z, abs=1e-9)
    assert out["se_z"] == pytest.approx(0.2, abs=1e-15)
    assert out["ci95"][0] == pytest.approx(math.tanh(z - Z95 * 0.2), abs=1e-9)
    assert out["ci95"][1] == pytest.approx(math.tanh(z + Z95 * 0.2), abs=1e-9)
    assert out["ci95"][0] == pytest.approx(0.15603, abs=1e-5)
    assert out["ci95"][1] == pytest.approx(0.73582, abs=1e-5)
    p = 2.0 * stats.norm.sf(z / 0.2)
    assert out["p"] == pytest.approx(p, abs=1e-12)
    assert out["method"] == "pearson"
    assert "independent" in out["assumption"]


def test_matches_numpy_corrcoef() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=80)
    y = 0.3 * x + rng.normal(size=80)
    out = correlation_interval(x, y)
    assert out["r"] == pytest.approx(float(np.corrcoef(x, y)[0, 1]), abs=1e-12)


def test_symmetry_and_positive_rescaling() -> None:
    # r(x, y) = r(y, x); and x -> 3x + 7, y -> 0.2y - 1 leave everything unchanged (1e-12).
    rng = np.random.default_rng(4)
    x = rng.normal(size=60)
    y = 0.5 * x + rng.normal(size=60)
    base = correlation_interval(x, y)
    swap = correlation_interval(y, x)
    scaled = correlation_interval(3.0 * x + 7.0, 0.2 * y - 1.0)
    for other in (swap, scaled):
        assert other["r"] == pytest.approx(base["r"], abs=1e-12)
        assert other["ci95"][0] == pytest.approx(base["ci95"][0], abs=1e-12)
        assert other["ci95"][1] == pytest.approx(base["ci95"][1], abs=1e-12)
        assert other["p"] == pytest.approx(base["p"], abs=1e-12)
    flipped = correlation_interval(-x, y)
    assert flipped["r"] == pytest.approx(-base["r"], abs=1e-12)
    assert flipped["ci95"][0] == pytest.approx(-base["ci95"][1], abs=1e-12)
    assert flipped["ci95"][1] == pytest.approx(-base["ci95"][0], abs=1e-12)
    assert flipped["p"] == pytest.approx(base["p"], abs=1e-12)


def test_p_value_agrees_with_the_t_form_in_large_samples() -> None:
    # Fisher-normal p versus the exact t(n-2) test of rho = 0: close, not equal; 5e-3 absolute
    # at n = 400 is far above the observed gap and far below any decision threshold.
    rng = np.random.default_rng(5)
    x = rng.normal(size=400)
    y = 0.12 * x + rng.normal(size=400)
    out = correlation_interval(x, y)
    r = out["r"]
    t = r * math.sqrt(398 / (1.0 - r * r))
    p_t = 2.0 * stats.t.sf(abs(t), 398)
    assert out["p"] == pytest.approx(p_t, abs=5e-3)


@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_perfect_correlation_is_a_stated_edge(sign: float) -> None:
    # Fisher z is infinite at |r| = 1: return r = +-1, a degenerate interval and p = 0.
    x = np.arange(10.0)
    out = correlation_interval(x, sign * (2.0 * x + 1.0))
    assert out["r"] == sign
    assert out["ci95"] == [sign, sign]
    assert out["p"] == pytest.approx(0.0, abs=1e-15)
    assert out["z"] is None
    assert out["se_z"] == pytest.approx(1.0 / math.sqrt(7.0), abs=1e-15)
    assert out["edge"] == "perfect_correlation"


def test_ordinary_correlation_has_no_edge_label() -> None:
    x = np.arange(10.0)
    assert correlation_interval(x, x**2 * np.cos(x))["edge"] is None


def test_coverage_of_the_true_correlation() -> None:
    # Bivariate normal rho = 0.6, n = 50, 2,000 seeded draws: ~95% coverage, within the binomial
    # two-sided half-width at z = 3.89 (alpha 1e-4) plus 0.01 for the Fisher approximation.
    rng = np.random.default_rng(99)
    rho, n, sims = 0.6, 50, 2000
    hits = 0
    for _ in range(sims):
        x = rng.normal(size=n)
        y = rho * x + math.sqrt(1 - rho * rho) * rng.normal(size=n)
        lo, hi = correlation_interval(x, y)["ci95"]
        hits += int(lo <= rho <= hi)
    band = 3.89 * math.sqrt(0.95 * 0.05 / sims) + 0.01
    assert hits / sims == pytest.approx(0.95, abs=band)


def test_serial_correlation_makes_the_test_over_reject() -> None:
    # The documented limit: two independent AR(1) series (phi = 0.8) reject rho = 0 far above 5%.
    rng = np.random.default_rng(7)
    rejections, sims, n = 0, 400, 200
    for _ in range(sims):
        series = []
        for _ in range(2):
            shocks = rng.normal(size=n)
            s = np.zeros(n)
            for t in range(1, n):
                s[t] = 0.8 * s[t - 1] + shocks[t]
            series.append(s)
        rejections += int(correlation_interval(series[0], series[1])["p"] < 0.05)
    assert rejections / sims > 0.25


def test_spearman_uses_average_ranks_and_fisher_interval() -> None:
    # Ties get average ranks, so r equals scipy's spearmanr (1e-12); the interval is Fisher's.
    x = np.array([1.0, 2.0, 2.0, 3.0, 5.0, 5.0, 5.0, 8.0, 9.0, 11.0])
    y = np.array([2.0, 1.0, 4.0, 4.0, 3.0, 8.0, 9.0, 7.0, 7.0, 12.0])
    out = correlation_interval(x, y, method="spearman")
    rho = float(stats.spearmanr(x, y)[0])
    assert out["method"] == "spearman"
    assert out["r"] == pytest.approx(rho, abs=1e-12)
    half = Z95 / math.sqrt(7.0)
    assert out["ci95"][0] == pytest.approx(math.tanh(math.atanh(rho) - half), abs=1e-12)
    assert out["ci95"][1] == pytest.approx(math.tanh(math.atanh(rho) + half), abs=1e-12)
    assert "approximat" in out["assumption"]


def test_spearman_is_invariant_to_monotone_transforms() -> None:
    rng = np.random.default_rng(8)
    x = rng.normal(size=50)
    y = x + rng.normal(size=50)
    base = correlation_interval(x, y, method="spearman")
    warped = correlation_interval(np.exp(x), y**3, method="spearman")
    assert warped["r"] == pytest.approx(base["r"], abs=1e-12)
    assert warped["ci95"][0] == pytest.approx(base["ci95"][0], abs=1e-12)


def test_minimum_sample_is_four() -> None:
    # Fisher z needs n > 3: n = 4 gives se = 1 and is accepted; n = 3 is refused.
    out = correlation_interval([1.0, 2.0, 3.0, 5.0], [2.0, 1.0, 4.0, 3.0])
    assert out["se_z"] == pytest.approx(1.0, abs=1e-15)
    with pytest.raises(DataError, match="at least 4"):
        correlation_interval([1.0, 2.0, 3.0], [1.0, 3.0, 2.0])


def test_bad_inputs_fail_loud() -> None:
    good = [1.0, 2.0, 3.0, 4.0, 6.0]
    other = [2.0, 1.0, 4.0, 3.0, 5.0]

    def call(x: Any, y: Any, **kw: Any) -> None:
        correlation_interval(x, y, **kw)

    with pytest.raises(DataError, match="finite"):
        call([1.0, float("nan"), 3.0, 4.0, 5.0], other)
    with pytest.raises(DataError, match="finite"):
        call(good, [1.0, float("inf"), 3.0, 4.0, 5.0])
    with pytest.raises(DataError, match="length"):
        call(good, other[:-1])
    with pytest.raises(DataError, match="does not vary"):
        call([2.0] * 5, other)
    with pytest.raises(DataError, match="does not vary"):
        call(good, [2.0] * 5)
    with pytest.raises(DataError, match="one-dimensional"):
        call(np.ones((5, 2)), other)
    with pytest.raises(DataError, match="method"):
        call(good, other, method="kendall")


def test_same_inputs_same_outputs_and_no_global_random_state() -> None:
    rng = np.random.default_rng(10)
    x = rng.normal(size=70)
    y = x + rng.normal(size=70)
    np.random.seed(5)
    before = np.random.get_state(legacy=False)["state"]["key"].copy()
    one = correlation_interval(x, y)
    two = correlation_interval(x, y)
    assert one == two
    assert np.array_equal(before, np.random.get_state(legacy=False)["state"]["key"])
