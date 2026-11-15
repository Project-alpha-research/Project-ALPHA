"""Volatility regimes of a market, and a strategy's returns split by regime.

Thin glue over ``statsmodels``: the regime model is the Markov-switching mean and variance model
of Hamilton (1989, "A New Approach to the Economic Analysis of Nonstationary Time Series and the
Business Cycle", Econometrica 57(2)) with the filter and smoother of Kim (1994, Journal of
Econometrics 60), as implemented by ``MarkovRegression``. No estimator is written here.

Honest limits, carried in the output as the label ``parameters-fit-in-sample``: the model's
means, variances and transition probabilities are estimated once on the whole sample. A filtered
probability at bar ``t`` uses the returns up to bar ``t`` only, but through parameters that have
seen every bar, so even the causal split below is a description, not a tradable signal.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

from alpha_validation.metrics import FloatArray, FloatSeq, sharpe_ratio

MIN_BARS = 60
SCALE = 100.0  # the model is fitted to percent returns, a better-conditioned optimisation
SEARCH_REPS = 3
LABEL = "parameters-fit-in-sample"
BASIS = (
    "Markov-switching model of the market's per-bar returns (switching mean and variance), "
    "regimes ordered from the lowest fitted variance (regime 0, calm) upwards; filtered "
    "probabilities use returns up to that bar, smoothed probabilities use the whole sample; "
    "parameters are estimated on the whole sample"
)
SPLIT_BASIS = (
    "each bar is assigned the most probable regime by the filtered probability of the bar "
    "before it, so the label uses only returns available before that bar; the first bar has no "
    "label; annualised mean = per-bar mean * periods_per_year; share of return = the regime's "
    "sum of log(1 + r) over the total"
)
HINDSIGHT_BASIS = (
    "each bar is assigned the most probable regime by the smoothed probability, which uses the "
    "whole sample including later bars (hindsight); otherwise as the causal split"
)


def _vector(values: FloatSeq, name: str) -> FloatArray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional series, got shape {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} contains a missing or infinite value")
    return arr


def causal_states(filtered: Any) -> list[int]:
    """Most probable filtered regime, shifted one bar later; ``-1`` marks the unlabelled first bar.

    Bar ``t`` receives ``argmax(filtered[t - 1])``: nothing observed at bar ``t`` or later enters
    its label (given the fitted parameters).
    """
    return [-1, *(int(value) for value in np.argmax(np.asarray(filtered)[:-1], axis=1))]


def volatility_regimes(market_returns: FloatSeq, *, k: int = 2, seed: int = 0) -> dict[str, Any]:
    """Fit a ``k``-regime switching-variance model to the MARKET's returns.

    Returns per-bar ``filtered`` and ``smoothed`` probabilities (one row per bar, one column per
    regime, calm first), the fitted ``means`` and ``variances`` in return units, the
    ``transition`` matrix (row = from, column = to), ``expected_durations`` in bars,
    ``causal_state`` (see :func:`causal_states`) and ``hindsight_state`` (most probable smoothed
    regime). ``seed`` fixes the optimiser's random restarts, so equal input gives equal output.
    Invalid input fails loud (``ValueError``); a fit that raises or does not converge returns
    ``{"converged": False, "reason": ...}`` instead.
    """
    x = _vector(market_returns, "market_returns")
    if k < 2:
        raise ValueError(f"k must be at least 2, got {k}")
    if x.size < MIN_BARS:
        raise ValueError(f"regime fitting needs at least {MIN_BARS} bars, got {x.size}")
    if float(np.ptp(x)) <= 0.0:
        raise ValueError("the market returns do not vary, so no regime can be fitted")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = MarkovRegression(x * SCALE, k_regimes=k, trend="c", switching_variance=True)
            fit = model.fit(search_reps=SEARCH_REPS, rng=np.random.default_rng(seed))
    except Exception as exc:  # the library's numerical failures are reported, never raised
        return {"converged": False, "reason": f"{type(exc).__name__}: {exc}", "labels": [LABEL]}
    params = dict(zip(model.param_names, np.asarray(fit.params, dtype=np.float64), strict=True))
    variances = np.array([params[f"sigma2[{i}]"] for i in range(k)]) / SCALE**2
    means = np.array([params[f"const[{i}]"] for i in range(k)]) / SCALE
    filtered = np.asarray(fit.filtered_marginal_probabilities, dtype=np.float64)
    smoothed = np.asarray(fit.smoothed_marginal_probabilities, dtype=np.float64)
    finite = all(bool(np.all(np.isfinite(v))) for v in (variances, means, filtered, smoothed))
    if not (bool(fit.mle_retvals["converged"]) and finite):
        reason = "the optimiser did not converge" if finite else "the fit produced undefined values"
        return {"converged": False, "reason": reason, "labels": [LABEL]}
    order = np.argsort(variances, kind="stable")
    filtered, smoothed = filtered[:, order], smoothed[:, order]
    # statsmodels stores transition[to, from]; reported here as rows = from, columns = to.
    transition = np.asarray(fit.regime_transition)[:, :, 0][np.ix_(order, order)].T
    return {
        "converged": True,
        "k": k,
        "n": int(x.size),
        "means": [float(v) for v in means[order]],
        "variances": [float(v) for v in variances[order]],
        "transition": [[float(v) for v in row] for row in transition],
        "expected_durations": [float(v) for v in np.asarray(fit.expected_durations)[order]],
        "filtered": filtered.tolist(),
        "smoothed": smoothed.tolist(),
        "causal_state": causal_states(filtered),
        "hindsight_state": [int(v) for v in np.argmax(smoothed, axis=1)],
        "log_likelihood": float(fit.llf),
        "labels": [LABEL],
        "basis": BASIS,
    }


def _sharpe(returns: FloatArray, periods_per_year: int) -> tuple[float | None, str | None]:
    if returns.size < 2:
        return None, "fewer than two bars in this regime"
    if float(np.ptp(returns)) <= 0.0:
        return None, "returns do not vary in this regime"
    return sharpe_ratio(returns, periods_per_year=periods_per_year), None


def returns_by_regime(
    strategy_returns: FloatSeq,
    benchmark_returns: FloatSeq,
    state: Any,
    *,
    periods_per_year: int,
    k: int | None = None,
) -> dict[str, Any]:
    """Describe the strategy and the benchmark inside each regime of ``state``.

    ``state`` holds one regime index per bar; negative entries are unlabelled bars and are left
    out. ``k`` is the number of regimes (default: the highest index present plus one). For each
    regime: bars, share of labelled time, annualised mean return and Sharpe of both series, and
    the share of the strategy's total log return earned there (null, with a reason, unless that
    total is positive). Fails loud (``ValueError``) on misaligned or non-finite input, or a
    return of -100% or worse.
    """
    strategy = _vector(strategy_returns, "strategy_returns")
    benchmark = _vector(benchmark_returns, "benchmark_returns")
    states = np.asarray(state, dtype=np.int64)
    if not (strategy.shape == benchmark.shape == states.shape):
        raise ValueError("strategy, benchmark and state must have equal length")
    if periods_per_year < 1:
        raise ValueError(f"periods_per_year must be at least 1, got {periods_per_year}")
    if bool(np.any(strategy <= -1.0)):
        raise ValueError("a strategy return of -100% or worse has no log return")
    count = int(states.max()) + 1 if k is None else k
    if count < 1 or int(states.max()) >= count:
        raise ValueError("state must label at least one bar with a regime index below k")
    labelled = states >= 0
    logs = np.log1p(strategy)
    total = float(np.sum(logs[labelled]))
    regimes = []
    for index in range(count):
        mask = states == index
        bars = int(np.sum(mask))
        row: dict[str, Any] = {
            "regime": index,
            "bars": bars,
            "share_of_time": bars / int(np.sum(labelled)),
            "strategy_log_return": float(np.sum(logs[mask])),
        }
        reasons: dict[str, str] = {}
        for name, series in (("strategy", strategy[mask]), ("benchmark", benchmark[mask])):
            row[f"{name}_annual_mean"] = float(np.mean(series)) * periods_per_year if bars else None
            row[f"{name}_sharpe"], reason = _sharpe(series, periods_per_year)
            if not bars:
                reasons[f"{name}_annual_mean"] = "no bars in this regime"
            if reason is not None:
                reasons[f"{name}_sharpe"] = reason
        row["share_of_log_return"] = row["strategy_log_return"] / total if total > 0.0 else None
        if total <= 0.0:
            reasons["share_of_log_return"] = "the strategy's total log return is not positive"
        row["reasons"] = reasons
        regimes.append(row)
    return {
        "labelled_bars": int(np.sum(labelled)),
        "unlabelled_bars": int(np.sum(~labelled)),
        "strategy_total_log_return": total,
        "regimes": regimes,
    }
