"""Market attribution: planted beta and alpha are recovered; numbers match first principles."""

import math

import numpy as np
import pytest
from scipy import stats

from alpha_validation import attribution
from alpha_validation.attribution import hac_lags, market_attribution


def _planted(n: int = 2000, seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    benchmark = rng.normal(0.0004, 0.01, n)
    strategy = 0.5 * benchmark + 0.0002 + rng.normal(0.0, 0.004, n)
    return strategy, benchmark


def _newey_west(y: np.ndarray, x: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray]:
    """Independent numpy implementation: OLS coefficients and Newey-West (1987) standard errors."""
    design = np.column_stack([np.ones_like(x), x])
    n, k = design.shape
    inverse = np.linalg.inv(design.T @ design)
    coefficients = inverse @ design.T @ y
    scores = design * (y - design @ coefficients)[:, None]
    meat = scores.T @ scores
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        cross = scores[lag:].T @ scores[:-lag]
        meat += weight * (cross + cross.T)
    covariance = inverse @ meat @ inverse * n / (n - k)
    return coefficients, np.sqrt(np.diag(covariance))


@pytest.mark.parametrize(("n", "lags"), [(60, 3), (100, 4), (2000, 7), (6000, 9), (3200, 8)])
def test_hac_lag_rule(n: int, lags: int) -> None:
    assert hac_lags(n) == lags == math.floor(4 * (n / 100) ** (2 / 9))


def test_planted_beta_and_alpha_are_recovered() -> None:
    strategy, benchmark = _planted()
    out = market_attribution(strategy, benchmark, periods_per_year=252)
    low, high = out["beta_ci95"]
    assert low < 0.5 < high
    assert out["beta"] == pytest.approx(0.5, abs=0.03)
    assert out["alpha_per_bar"] == pytest.approx(0.0002, abs=0.0002)
    assert out["alpha_annual"] == pytest.approx(out["alpha_per_bar"] * 252, rel=1e-12)
    assert out["alpha_t"] > 2
    assert out["alpha_p"] < 0.05
    assert out["n"] == 2000
    assert out["hac_lags"] == 7
    assert out["reasons"] == {}
    assert out["basis"] == attribution.BASIS
    assert "Newey-West" in out["basis"]
    assert "periods_per_year" in out["basis"]
    assert set(out) == {
        "beta",
        "beta_se",
        "beta_ci95",
        "alpha_per_bar",
        "alpha_annual",
        "alpha_t",
        "alpha_p",
        "r_squared",
        "share_of_variance_explained",
        "n",
        "hac_lags",
        "up_beta",
        "down_beta",
        "reasons",
        "basis",
    }


def test_matches_first_principles_and_independent_newey_west() -> None:
    strategy, benchmark = _planted(n=700, seed=5)
    # Autocorrelated, heteroskedastic noise so the HAC correction matters.
    rng = np.random.default_rng(6)
    noise = rng.normal(0.0, 0.003, 700) * (1 + 5 * np.abs(benchmark) / 0.01)
    strategy = strategy + np.convolve(noise, [1.0, 0.6, 0.3], mode="same")
    out = market_attribution(strategy, benchmark, periods_per_year=365)
    coefficients, errors = _newey_west(strategy, benchmark, hac_lags(700))
    beta = np.cov(strategy, benchmark, ddof=1)[0, 1] / np.var(benchmark, ddof=1)
    assert out["hac_lags"] == 6
    assert out["beta"] == pytest.approx(beta, rel=1e-9)
    assert out["beta"] == pytest.approx(coefficients[1], rel=1e-9)
    assert out["alpha_per_bar"] == pytest.approx(
        strategy.mean() - beta * benchmark.mean(), rel=1e-9
    )
    assert out["alpha_per_bar"] == pytest.approx(coefficients[0], rel=1e-9)
    assert out["alpha_annual"] == pytest.approx(coefficients[0] * 365, rel=1e-9)
    assert out["beta_se"] == pytest.approx(errors[1], rel=1e-8)
    assert out["alpha_t"] == pytest.approx(coefficients[0] / errors[0], rel=1e-8)
    assert out["alpha_p"] == pytest.approx(2 * stats.norm.sf(abs(out["alpha_t"])), rel=1e-8)
    assert out["beta_ci95"] == pytest.approx(
        [beta - stats.norm.ppf(0.975) * errors[1], beta + stats.norm.ppf(0.975) * errors[1]],
        rel=1e-8,
    )
    r_squared = np.corrcoef(strategy, benchmark)[0, 1] ** 2
    assert out["r_squared"] == pytest.approx(r_squared, rel=1e-9)
    assert out["share_of_variance_explained"] == pytest.approx(r_squared, rel=1e-9)
    # The correction is not a no-op here: plain OLS errors differ.
    residual = strategy - coefficients[0] - coefficients[1] * benchmark
    plain = math.sqrt(residual @ residual / 698 / np.sum((benchmark - benchmark.mean()) ** 2))
    assert abs(out["beta_se"] / plain - 1) > 0.05


def test_pure_benchmark_has_unit_beta_and_full_r_squared() -> None:
    _, benchmark = _planted(n=300)
    noise = np.random.default_rng(1).normal(0.0, 1e-9, 300)
    out = market_attribution(benchmark + noise, benchmark, periods_per_year=252)
    assert out["beta"] == pytest.approx(1.0, abs=1e-6)
    assert out["r_squared"] == pytest.approx(1.0, abs=1e-9)
    assert out["alpha_annual"] == pytest.approx(0.0, abs=1e-6)
    assert out["up_beta"] == pytest.approx(1.0, abs=1e-6)
    assert out["down_beta"] == pytest.approx(1.0, abs=1e-6)


def test_risk_free_is_removed_per_bar_from_both_series() -> None:
    strategy, benchmark = _planted(n=500)
    base = market_attribution(strategy, benchmark, periods_per_year=252)
    shifted = market_attribution(strategy, benchmark, periods_per_year=252, risk_free=0.0504)
    per_bar = 0.0504 / 252
    assert shifted["beta"] == pytest.approx(base["beta"], rel=1e-9)
    assert shifted["beta_se"] == pytest.approx(base["beta_se"], rel=1e-9)
    assert shifted["alpha_per_bar"] == pytest.approx(
        base["alpha_per_bar"] - per_bar * (1 - base["beta"]), rel=1e-9
    )
    assert shifted["alpha_per_bar"] != pytest.approx(base["alpha_per_bar"], rel=1e-3)
    assert shifted["up_beta"] == pytest.approx(base["up_beta"], rel=1e-9)
    assert shifted["down_beta"] == pytest.approx(base["down_beta"], rel=1e-9)


def test_planted_asymmetric_betas() -> None:
    rng = np.random.default_rng(3)
    benchmark = rng.normal(0.0, 0.01, 3000)
    strategy = np.where(benchmark >= 0, 0.9, 0.2) * benchmark + rng.normal(0.0, 0.001, 3000)
    out = market_attribution(strategy, benchmark, periods_per_year=252)
    assert out["up_beta"] == pytest.approx(0.9, abs=0.03)
    assert out["down_beta"] == pytest.approx(0.2, abs=0.03)
    assert out["down_beta"] < out["beta"] < out["up_beta"]
    up = benchmark >= 0
    assert out["up_beta"] == pytest.approx(
        np.cov(strategy[up], benchmark[up])[0, 1] / np.var(benchmark[up], ddof=1), rel=1e-9
    )
    assert out["down_beta"] == pytest.approx(
        np.cov(strategy[~up], benchmark[~up])[0, 1] / np.var(benchmark[~up], ddof=1), rel=1e-9
    )


def test_zero_benchmark_bar_counts_as_up() -> None:
    rng = np.random.default_rng(8)
    benchmark = np.r_[
        np.zeros(1), np.abs(rng.normal(0.0, 0.01, 29)), -np.abs(rng.normal(0, 0.01, 30))
    ]
    strategy = benchmark * 0.7 + rng.normal(0.0, 0.001, 60)
    out = market_attribution(strategy, benchmark, periods_per_year=252)
    assert out["up_beta"] is not None
    assert out["down_beta"] is not None
    assert out["reasons"] == {}


def test_thin_side_is_null_with_a_reason() -> None:
    rng = np.random.default_rng(4)
    benchmark = np.r_[np.abs(rng.normal(0.0, 0.01, 71)), -np.abs(rng.normal(0.0, 0.01, 29))]
    strategy = 0.5 * benchmark + rng.normal(0.0, 0.002, 100)
    out = market_attribution(strategy, benchmark, periods_per_year=252)
    assert out["up_beta"] is not None
    assert out["down_beta"] is None
    assert out["reasons"] == {"down_beta": "only 29 bars on this side; at least 30 are needed"}
    mirrored = market_attribution(-strategy, -benchmark, periods_per_year=252)
    assert mirrored["up_beta"] is None
    assert mirrored["down_beta"] is not None
    assert mirrored["reasons"] == {"up_beta": "only 29 bars on this side; at least 30 are needed"}


def test_constant_side_is_null_with_a_reason() -> None:
    rng = np.random.default_rng(9)
    benchmark = np.r_[np.full(40, 0.01), -np.abs(rng.normal(0.0, 0.01, 40))]
    strategy = 0.5 * benchmark + rng.normal(0.0, 0.002, 80)
    out = market_attribution(strategy, benchmark, periods_per_year=252)
    assert out["up_beta"] is None
    assert out["reasons"] == {"up_beta": "the benchmark return does not vary on this side"}


def test_exactly_sixty_bars_is_enough() -> None:
    strategy, benchmark = _planted(n=60)
    assert market_attribution(strategy, benchmark, periods_per_year=252)["n"] == 60


@pytest.mark.parametrize(
    ("strategy", "benchmark", "ppy", "message"),
    [
        (np.zeros(59) + np.arange(59), np.arange(59.0), 252, "at least 60 aligned bars, got 59"),
        (np.arange(80.0), np.arange(81.0), 252, "equal length, got 80 and 81"),
        (np.arange(80.0), np.ones(80), 252, "benchmark returns do not vary"),
        (np.ones(80), np.arange(80.0), 252, "strategy returns do not vary"),
        (np.r_[np.nan, np.arange(79.0)], np.arange(80.0), 252, "strategy_returns contains"),
        (np.arange(80.0), np.r_[np.inf, np.arange(79.0)], 252, "benchmark_returns contains"),
        (np.ones((40, 2)), np.arange(80.0), 252, r"strategy_returns must be .* \(40, 2\)"),
        (np.arange(80.0), np.arange(80.0), 0, "periods_per_year must be at least 1, got 0"),
    ],
)
def test_invalid_input_fails_loud(
    strategy: np.ndarray, benchmark: np.ndarray, ppy: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        market_attribution(strategy, benchmark, periods_per_year=ppy)


def test_one_period_per_year_is_allowed() -> None:
    strategy, benchmark = _planted(n=80)
    out = market_attribution(strategy, benchmark, periods_per_year=1)
    assert out["alpha_annual"] == pytest.approx(out["alpha_per_bar"], rel=1e-12)
