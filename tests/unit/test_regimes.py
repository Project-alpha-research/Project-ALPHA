"""Volatility regimes: planted calm/turbulent blocks are found; the causal split is shifted."""

import math
import warnings
from typing import Any

import numpy as np
import pytest
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

from alpha_validation import regimes
from alpha_validation.metrics import sharpe_ratio
from alpha_validation.regimes import causal_states, returns_by_regime, volatility_regimes


def _blocks(seed: int = 2, lead_turbulent: bool = False) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    sizes = (200, 300, 150, 250) if lead_turbulent else (300, 200, 400)
    truth = np.concatenate(
        [np.full(size, (i + lead_turbulent) % 2) for i, size in enumerate(sizes)]
    ).astype(int)
    returns = np.where(
        truth == 1, rng.normal(-0.001, 0.03, truth.size), rng.normal(0.0006, 0.006, truth.size)
    )
    return returns, truth


@pytest.fixture(scope="module")
def fitted() -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    returns, truth = _blocks()
    return returns, truth, volatility_regimes(returns)


def _reference(returns: np.ndarray, seed: int = 0) -> Any:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = MarkovRegression(returns * 100.0, k_regimes=2, trend="c", switching_variance=True)
        return model, model.fit(search_reps=3, rng=np.random.default_rng(seed))


def test_planted_blocks_are_classified(
    fitted: tuple[np.ndarray, np.ndarray, dict[str, Any]],
) -> None:
    returns, truth, out = fitted
    assert out["converged"] is True
    assert out["k"] == 2
    assert out["n"] == 900
    assert out["labels"] == ["parameters-fit-in-sample"]
    assert out["basis"] == regimes.BASIS
    assert np.mean(np.array(out["hindsight_state"]) == truth) > 0.97
    causal = np.array(out["causal_state"])
    assert causal[0] == -1
    assert np.mean(causal[1:] == truth[1:]) > 0.93
    assert out["variances"][0] == pytest.approx(0.006**2, rel=0.25)
    assert out["variances"][1] == pytest.approx(0.03**2, rel=0.25)
    assert out["means"][0] == pytest.approx(0.0006, abs=0.001)
    assert out["means"][1] == pytest.approx(-0.001, abs=0.006)
    assert out["means"][0] != pytest.approx(out["means"][1], abs=1e-6)


def test_output_matches_statsmodels_reordered_by_variance(
    fitted: tuple[np.ndarray, np.ndarray, dict[str, Any]],
) -> None:
    returns, _, out = fitted
    model, fit = _reference(returns)
    params = dict(zip(model.param_names, fit.params, strict=True))
    raw_variances = np.array([params["sigma2[0]"], params["sigma2[1]"]])
    order = np.argsort(raw_variances)
    assert out["variances"] == pytest.approx(list(raw_variances[order] / 1e4), rel=1e-9)
    assert out["means"] == pytest.approx([params[f"const[{i}]"] / 100.0 for i in order], rel=1e-9)
    filtered, smoothed = np.array(out["filtered"]), np.array(out["smoothed"])
    assert filtered.shape == smoothed.shape == (900, 2)
    np.testing.assert_allclose(filtered, fit.filtered_marginal_probabilities[:, order], atol=1e-12)
    np.testing.assert_allclose(smoothed, fit.smoothed_marginal_probabilities[:, order], atol=1e-12)
    np.testing.assert_allclose(filtered.sum(axis=1), 1.0, atol=1e-9)
    assert not np.allclose(filtered, smoothed, atol=1e-3)
    transition = np.array(out["transition"])
    np.testing.assert_allclose(transition.sum(axis=1), 1.0, atol=1e-9)
    stay = [params["p[0->0]"], 1.0 - params["p[1->0]"]]
    assert transition[0, 0] == pytest.approx(stay[order[0]], rel=1e-9)
    assert transition[1, 1] == pytest.approx(stay[order[1]], rel=1e-9)
    assert transition[0, 1] == pytest.approx(1.0 - stay[order[0]], rel=1e-9)
    assert out["expected_durations"] == pytest.approx(
        [1.0 / (1.0 - transition[0, 0]), 1.0 / (1.0 - transition[1, 1])], rel=1e-9
    )
    assert out["log_likelihood"] == pytest.approx(float(fit.llf), rel=1e-12)
    assert out["hindsight_state"] == [int(v) for v in np.argmax(smoothed, axis=1)]
    assert out["causal_state"] == [-1, *(int(v) for v in np.argmax(filtered[:-1], axis=1))]
    assert out["causal_state"] == causal_states(out["filtered"])
    assert out["causal_state"] != out["hindsight_state"]


def test_regime_zero_is_calm_whichever_block_comes_first() -> None:
    returns, truth = _blocks(seed=4, lead_turbulent=True)
    out = volatility_regimes(returns)
    assert out["variances"][0] < out["variances"][1]
    assert np.mean(np.array(out["hindsight_state"]) == truth) > 0.97
    transition = np.array(out["transition"])
    # rows are "from": the long calm regime is the stickier one in this sample
    np.testing.assert_allclose(transition.sum(axis=1), 1.0, atol=1e-9)
    assert out["expected_durations"][0] == pytest.approx(1.0 / transition[0, 1], rel=1e-9)
    assert out["expected_durations"][1] == pytest.approx(1.0 / transition[1, 0], rel=1e-9)


def test_same_seed_same_output(fitted: tuple[np.ndarray, np.ndarray, dict[str, Any]]) -> None:
    returns, _, out = fitted
    assert volatility_regimes(returns, seed=0) == out


def test_causal_states_shift_one_bar_later() -> None:
    filtered = [[0.9, 0.1], [0.2, 0.8], [0.6, 0.4], [0.1, 0.9]]
    assert causal_states(filtered) == [-1, 0, 1, 0]
    assert causal_states(np.array(filtered)[:, ::-1]) == [-1, 1, 0, 1]
    assert causal_states([[0.1, 0.2, 0.7], [0.5, 0.3, 0.2]]) == [-1, 2]


def test_a_bar_cannot_change_its_own_causal_label() -> None:
    """Future-poison check with its leaky twin, at fixed model parameters.

    Bar ``t`` gets a huge return. Under the shifted (causal) labelling nothing up to and
    including bar ``t`` changes; the unshifted labelling (the leaky twin) changes at ``t``.
    """
    returns, _ = _blocks()
    model, fit = _reference(returns)
    t = 100  # deep inside the first calm block
    poisoned = returns.copy()
    poisoned[t] = 0.25
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        again = MarkovRegression(poisoned * 100.0, k_regimes=2, trend="c", switching_variance=True)
        refiltered = again.filter(fit.params).filtered_marginal_probabilities
    clean = fit.filtered_marginal_probabilities
    np.testing.assert_allclose(refiltered[:t], clean[:t], atol=1e-12)
    assert causal_states(refiltered)[: t + 1] == causal_states(clean)[: t + 1]
    leaky_clean, leaky_poisoned = np.argmax(clean, axis=1), np.argmax(refiltered, axis=1)
    assert leaky_clean[t] != leaky_poisoned[t]
    assert causal_states(refiltered)[t + 1] != causal_states(clean)[t + 1]


class _Raises:
    param_names: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def fit(self, **kwargs: Any) -> Any:
        raise np.linalg.LinAlgError("singular matrix")


def test_fit_that_raises_reports_not_converged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(regimes, "MarkovRegression", _Raises)
    out = volatility_regimes(_blocks()[0])
    assert out == {
        "converged": False,
        "reason": "LinAlgError: singular matrix",
        "labels": ["parameters-fit-in-sample"],
    }


@pytest.mark.parametrize(
    ("converged", "poison", "reason"),
    [
        (False, False, "the optimiser did not converge"),
        (True, True, "the fit produced undefined values"),
        (False, True, "the fit produced undefined values"),
    ],
)
def test_unconverged_or_undefined_fit_reports_not_converged(
    monkeypatch: pytest.MonkeyPatch, converged: bool, poison: bool, reason: str
) -> None:
    returns = _blocks()[0]
    real_fit = MarkovRegression.fit
    seen: dict[str, Any] = {}

    def fit(self: Any, **kwargs: Any) -> Any:
        seen.update(kwargs, endog=np.asarray(self.endog).ravel().copy())
        result = real_fit(self, **kwargs)
        result.mle_retvals["converged"] = converged
        if poison:
            result.smoothed_marginal_probabilities[5, 0] = np.nan
        return result

    monkeypatch.setattr(MarkovRegression, "fit", fit)
    out = volatility_regimes(returns, seed=7)
    assert out == {"converged": False, "reason": reason, "labels": ["parameters-fit-in-sample"]}
    assert seen["search_reps"] == 3
    np.testing.assert_allclose(seen["endog"], returns * 100.0, rtol=1e-12)
    assert seen["rng"].bit_generator.seed_seq.entropy == 7


def test_three_regimes_are_ordered_by_variance() -> None:
    rng = np.random.default_rng(12)
    returns = np.concatenate(
        [rng.normal(0, 0.004, 300), rng.normal(0, 0.05, 200), rng.normal(0, 0.015, 300)]
    )
    out = volatility_regimes(returns, k=3)
    if out["converged"]:
        assert out["k"] == 3
        assert out["variances"] == sorted(out["variances"])
        assert np.array(out["filtered"]).shape == (800, 3)
        np.testing.assert_allclose(np.array(out["transition"]).sum(axis=1), 1.0, atol=1e-9)
    else:
        assert out["reason"]


@pytest.mark.parametrize(
    ("values", "k", "message"),
    [
        (np.arange(59.0), 2, "at least 60 bars, got 59"),
        (np.arange(100.0), 1, "k must be at least 2, got 1"),
        (np.ones(100), 2, "market returns do not vary"),
        (np.r_[np.nan, np.arange(99.0)], 2, "market_returns contains a missing"),
        (np.ones((50, 2)), 2, r"market_returns must be .* \(50, 2\)"),
    ],
)
def test_invalid_market_input_fails_loud(values: np.ndarray, k: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        volatility_regimes(values, k=k)


def test_sixty_bars_are_accepted() -> None:
    out = volatility_regimes(np.random.default_rng(0).normal(0, 0.01, 60))
    assert out["converged"] in (True, False)
    assert out["labels"] == ["parameters-fit-in-sample"]


def test_returns_by_regime_exact_numbers() -> None:
    strategy = np.array([0.01, 0.02, -0.01, 0.03, 0.0, 0.05, -0.02])
    benchmark = np.array([0.02, 0.01, -0.02, 0.01, 0.01, 0.02, -0.03])
    state = np.array([-1, 0, 0, 1, 0, 1, 1])
    out = returns_by_regime(strategy, benchmark, state, periods_per_year=252)
    logs = np.log1p(strategy)
    total = logs[1:].sum()
    assert out["labelled_bars"] == 6
    assert out["unlabelled_bars"] == 1
    assert out["strategy_total_log_return"] == pytest.approx(total, rel=1e-12)
    calm, turbulent = out["regimes"]
    assert (calm["regime"], calm["bars"], turbulent["regime"], turbulent["bars"]) == (0, 3, 1, 3)
    assert calm["share_of_time"] == pytest.approx(0.5)
    assert calm["strategy_log_return"] == pytest.approx(logs[[1, 2, 4]].sum(), rel=1e-12)
    assert calm["share_of_log_return"] == pytest.approx(logs[[1, 2, 4]].sum() / total, rel=1e-12)
    assert turbulent["share_of_log_return"] == pytest.approx(logs[[3, 5, 6]].sum() / total)
    assert calm["share_of_log_return"] + turbulent["share_of_log_return"] == pytest.approx(1.0)
    assert calm["strategy_annual_mean"] == pytest.approx(strategy[[1, 2, 4]].mean() * 252)
    assert calm["benchmark_annual_mean"] == pytest.approx(benchmark[[1, 2, 4]].mean() * 252)
    assert turbulent["strategy_annual_mean"] == pytest.approx(strategy[[3, 5, 6]].mean() * 252)
    assert calm["strategy_sharpe"] == pytest.approx(
        sharpe_ratio(strategy[[1, 2, 4]], periods_per_year=252)
    )
    assert turbulent["benchmark_sharpe"] == pytest.approx(
        benchmark[[3, 5, 6]].mean() / benchmark[[3, 5, 6]].std(ddof=1) * math.sqrt(252)
    )
    assert calm["reasons"] == {} == turbulent["reasons"]
    weekly = returns_by_regime(strategy, benchmark, state, periods_per_year=52)
    assert weekly["regimes"][0]["strategy_annual_mean"] == pytest.approx(
        strategy[[1, 2, 4]].mean() * 52
    )
    assert weekly["regimes"][0]["strategy_sharpe"] == pytest.approx(
        sharpe_ratio(strategy[[1, 2, 4]], periods_per_year=52)
    )


def test_returns_by_regime_explains_what_it_cannot_compute() -> None:
    strategy = np.array([-0.01, -0.02, 0.01, 0.0, 0.0])
    benchmark = np.array([0.01, 0.01, 0.02, 0.01, 0.03])
    out = returns_by_regime(strategy, benchmark, [0, 0, 1, 0, 0], periods_per_year=252, k=3)
    calm, single, empty = out["regimes"]
    assert out["unlabelled_bars"] == 0
    assert out["strategy_total_log_return"] < 0
    assert calm["share_of_log_return"] is None
    assert calm["reasons"] == {
        "share_of_log_return": "the strategy's total log return is not positive"
    }
    assert single["bars"] == 1
    assert single["strategy_annual_mean"] == pytest.approx(0.01 * 252)
    assert single["strategy_sharpe"] is None
    assert single["reasons"]["strategy_sharpe"] == "fewer than two bars in this regime"
    assert single["reasons"]["benchmark_sharpe"] == "fewer than two bars in this regime"
    assert empty["bars"] == 0
    assert empty["share_of_time"] == 0
    assert empty["strategy_annual_mean"] is None
    assert empty["benchmark_annual_mean"] is None
    assert empty["strategy_log_return"] == 0
    assert empty["reasons"] == {
        "strategy_annual_mean": "no bars in this regime",
        "strategy_sharpe": "fewer than two bars in this regime",
        "benchmark_annual_mean": "no bars in this regime",
        "benchmark_sharpe": "fewer than two bars in this regime",
        "share_of_log_return": "the strategy's total log return is not positive",
    }
    flat = returns_by_regime([0.0, 0.0, 0.01], [0.01, 0.01, 0.02], [0, 0, 1], periods_per_year=12)
    assert flat["regimes"][0]["strategy_sharpe"] is None
    assert flat["regimes"][0]["reasons"] == {
        "strategy_sharpe": "returns do not vary in this regime",
        "benchmark_sharpe": "returns do not vary in this regime",
    }
    assert flat["regimes"][1]["share_of_log_return"] == pytest.approx(1.0)
    zero = returns_by_regime([0.01, -0.01 / 1.01], [0.01, 0.02], [0, 0], periods_per_year=12)
    assert zero["regimes"][0]["share_of_log_return"] is None


@pytest.mark.parametrize(
    ("strategy", "benchmark", "state", "ppy", "k", "message"),
    [
        ([0.1, 0.2], [0.1], [0, 0], 252, None, "equal length"),
        ([0.1, 0.2], [0.1, 0.2], [0], 252, None, "equal length"),
        ([0.1, -1.0], [0.1, 0.2], [0, 0], 252, None, "-100% or worse"),
        ([0.1, 0.2], [0.1, 0.2], [0, 0], 0, None, "periods_per_year must be at least 1, got 0"),
        ([0.1, 0.2], [0.1, 0.2], [-1, -1], 252, None, "at least one bar"),
        ([0.1, 0.2], [0.1, 0.2], [0, 2], 252, 2, "regime index below k"),
        ([0.1, np.nan], [0.1, 0.2], [0, 0], 252, None, "strategy_returns contains"),
        ([0.1, 0.2], [0.1, np.inf], [0, 0], 252, None, "benchmark_returns contains"),
    ],
)
def test_returns_by_regime_fails_loud(
    strategy: list[float],
    benchmark: list[float],
    state: list[int],
    ppy: int,
    k: int | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        returns_by_regime(strategy, benchmark, state, periods_per_year=ppy, k=k)


def test_one_period_per_year_and_exact_k_are_allowed() -> None:
    out = returns_by_regime([0.1, 0.2], [0.1, 0.2], [0, 1], periods_per_year=1, k=2)
    assert [row["bars"] for row in out["regimes"]] == [1, 1]
    assert out["regimes"][1]["strategy_annual_mean"] == pytest.approx(0.2)


def test_returns_by_regime_with_no_labelled_bar_fails_loud() -> None:
    # Review finding: all-unlabelled states with an explicit k divided by zero.
    zeros = np.zeros(5)
    with pytest.raises(ValueError, match="at least one bar"):
        returns_by_regime(zeros, zeros, [-1] * 5, periods_per_year=252, k=2)
