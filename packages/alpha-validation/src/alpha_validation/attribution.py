"""Market attribution: how much of a return series is benchmark exposure, and what is left.

Thin glue over ``statsmodels`` ordinary least squares; no estimator is written here. The model
is the single-index (market) regression of Sharpe (1964) and Jensen (1968):

    r_strategy,t - rf_t = alpha + beta * (r_benchmark,t - rf_t) + e_t

with heteroskedasticity- and autocorrelation-consistent standard errors (Newey and West 1987,
"A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance
Matrix", Econometrica 55(3)), Bartlett kernel, lag truncation ``floor(4 * (n / 100) ** (2 / 9))``
(the rule of thumb of Newey and West 1994, Review of Economic Studies 61(4)).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import statsmodels.api as sm  # type: ignore[import-untyped]

from alpha_validation.metrics import FloatArray, FloatSeq

MIN_BARS = 60
MIN_SIDE_BARS = 30
BASIS = (
    "ordinary least squares of per-bar simple excess returns on the benchmark's, with a constant; "
    "Newey-West standard errors (Bartlett kernel, lags = floor(4 * (n / 100) ** (2 / 9)), "
    "small-sample correction); p-value and interval from the normal distribution; "
    "alpha_annual = alpha_per_bar * periods_per_year"
)


def hac_lags(n: int) -> int:
    """Newey-West (1994) rule-of-thumb lag truncation for ``n`` observations."""
    return int(math.floor(4 * (n / 100) ** (2 / 9)))


def _vector(values: FloatSeq, name: str) -> FloatArray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional series, got shape {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} contains a missing or infinite value")
    return arr


def _side_beta(strategy: FloatArray, benchmark: FloatArray, mask: Any) -> tuple[Any, Any]:
    """Slope of a separate regression on one side of the benchmark's sign; (value, reason)."""
    bars = int(np.sum(mask))
    if bars < MIN_SIDE_BARS:
        return None, f"only {bars} bars on this side; at least {MIN_SIDE_BARS} are needed"
    x = benchmark[mask]
    if float(np.ptp(x)) <= 0.0:
        return None, "the benchmark return does not vary on this side"
    return float(sm.OLS(strategy[mask], sm.add_constant(x)).fit().params[1]), None


def market_attribution(
    strategy_returns: FloatSeq,
    benchmark_returns: FloatSeq,
    *,
    periods_per_year: int,
    risk_free: float = 0.0,
) -> dict[str, Any]:
    """Split a strategy's per-bar returns into benchmark exposure (beta) and the rest (alpha).

    Inputs are aligned per-bar simple returns of equal length; the caller aligns them by date.
    ``risk_free`` is an annual rate, removed from both series as ``risk_free / periods_per_year``
    per bar. ``up_beta`` and ``down_beta`` are the slopes of separate regressions on the bars
    where the benchmark's raw return is ``>= 0`` and ``< 0``. Fails loud (``ValueError``) on
    fewer than 60 bars, non-finite values, or a series that does not vary.
    """
    if periods_per_year < 1:
        raise ValueError(f"periods_per_year must be at least 1, got {periods_per_year}")
    strategy = _vector(strategy_returns, "strategy_returns")
    benchmark = _vector(benchmark_returns, "benchmark_returns")
    if strategy.shape != benchmark.shape:
        raise ValueError(
            f"the two series must have equal length, got {strategy.size} and {benchmark.size}"
        )
    n = int(strategy.size)
    if n < MIN_BARS:
        raise ValueError(f"market attribution needs at least {MIN_BARS} aligned bars, got {n}")
    if float(np.ptp(benchmark)) <= 0.0:
        raise ValueError("the benchmark returns do not vary, so beta is undefined")
    if float(np.ptp(strategy)) <= 0.0:
        raise ValueError("the strategy returns do not vary, so there is nothing to attribute")
    per_bar = risk_free / periods_per_year
    y, x = strategy - per_bar, benchmark - per_bar
    lags = hac_lags(n)
    fit = sm.OLS(y, sm.add_constant(x)).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": True}
    )
    low, high = fit.conf_int(alpha=0.05)[1]
    up_beta, up_reason = _side_beta(y, x, benchmark >= 0.0)
    down_beta, down_reason = _side_beta(y, x, benchmark < 0.0)
    reasons = {
        key: reason
        for key, reason in (("up_beta", up_reason), ("down_beta", down_reason))
        if reason is not None
    }
    r_squared = float(fit.rsquared)
    return {
        "beta": float(fit.params[1]),
        "beta_se": float(fit.bse[1]),
        "beta_ci95": [float(low), float(high)],
        "alpha_per_bar": float(fit.params[0]),
        "alpha_annual": float(fit.params[0]) * periods_per_year,
        "alpha_t": float(fit.tvalues[0]),
        "alpha_p": float(fit.pvalues[0]),
        "r_squared": r_squared,
        "share_of_variance_explained": r_squared,
        "n": n,
        "hac_lags": lags,
        "up_beta": up_beta,
        "down_beta": down_beta,
        "reasons": reasons,
        "basis": BASIS,
    }
