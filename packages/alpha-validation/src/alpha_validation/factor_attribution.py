"""Factor attribution: ordinary least squares of a return series on K factors, with HAC errors.

Model: ``y_t = alpha + sum_j beta_j * x_jt + e_t``, estimated by ordinary least squares with a
constant (any standard regression text, for example Greene, *Econometric Analysis*). Standard
errors are heteroskedasticity- and autocorrelation-consistent: Newey and West (1987), "A Simple,
Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix",
Econometrica 55(3), with the Bartlett kernel. The lag rule ``floor(4 * (n / 100) ** (2 / 9))``
is the one ``attribution.hac_lags`` uses (Newey and West 1994, Review of Economic Studies 61(4)),
and the covariance carries the small-sample factor ``n / (n - K - 1)``. These are the same
conventions as ``market_attribution``, so with K = 1 the two agree. Intervals and p-values use the
normal distribution, as ``market_attribution`` does.

Collinearity: the condition number of the design matrix (a constant column plus the factors) with
every column scaled to unit length, the Belsley, Kuh and Welsch (1980) *Regression Diagnostics*
convention. Above ``MAX_CONDITION_NUMBER`` the call fails; their rule of thumb flags values of
about 30 and more.

A significant beta is not evidence of an edge; it measures exposure to the factor.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import stats

from alpha_core import DataError
from alpha_validation.attribution import hac_lags
from alpha_validation.metrics import FloatArray, FloatSeq

MIN_OBSERVATIONS_FLOOR = 36
OBSERVATIONS_PER_PARAMETER = 10
MAX_CONDITION_NUMBER = 30.0
_Z95 = float(stats.norm.ppf(0.975))
BASIS = (
    "ordinary least squares of per-period returns on K factors with a constant; Newey-West "
    "standard errors (Bartlett kernel, lags = floor(4 * (n / 100) ** (2 / 9)), n / (n - K - 1) "
    "small-sample factor); p-value and 95% interval from the normal distribution; "
    "alpha_annual = alpha_per_period * periods_per_year; condition number of the design matrix "
    "with unit-length columns"
)


def min_observations(k: int) -> int:
    """Smallest sample for K factors: ``max(36, 10 * (K + 1))``; a convention, not a law."""
    return max(MIN_OBSERVATIONS_FLOOR, OBSERVATIONS_PER_PARAMETER * (k + 1))


def _array(values: FloatSeq, name: str, ndim: int) -> FloatArray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != ndim:
        word = "one" if ndim == 1 else "two"
        raise DataError(f"{name} must be {word}-dimensional, got shape {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise DataError(f"{name} contains a missing or infinite value")
    return arr


def _check_inputs(
    strategy: FloatArray, factors: FloatArray, names: Sequence[str], periods_per_year: int
) -> None:
    if periods_per_year < 1:
        raise DataError(f"periods_per_year must be at least 1, got {periods_per_year}")
    k = int(factors.shape[1])
    if k < 1:
        raise DataError("factor attribution needs at least one factor")
    if len(names) != k:
        raise DataError(f"factor_names has {len(names)} names for {k} factors")
    if len(set(names)) != k:
        raise DataError(f"duplicate factor names: {sorted(names)}")
    if strategy.size != factors.shape[0]:
        raise DataError(
            f"strategy and factors must have equal length, got {strategy.size} and "
            f"{factors.shape[0]}"
        )
    need = min_observations(k)
    if strategy.size < need:
        raise DataError(f"{k} factors need at least {need} observations, got {strategy.size}")
    if float(np.ptp(strategy)) <= 0.0:
        raise DataError("the strategy returns do not vary, so there is nothing to attribute")
    for j, name in enumerate(names):
        if float(np.ptp(factors[:, j])) <= 0.0:
            raise DataError(f"factor '{name}' does not vary, so its beta is undefined")


def _condition(design: FloatArray, names: Sequence[str]) -> float:
    scaled = design / np.linalg.norm(design, axis=0)
    _, sing, vt = np.linalg.svd(scaled, full_matrices=False)
    smallest = float(sing[-1])
    cond = math.inf if smallest <= 0.0 else float(sing[0]) / smallest
    if cond > MAX_CONDITION_NUMBER:
        weights = np.abs(vt[-1])
        labels = ["constant", *names]
        involved = [labels[i] for i in range(len(labels)) if weights[i] >= 0.25 * weights.max()]
        shown = "inf" if math.isinf(cond) else f"{cond:.1f}"
        raise DataError(
            f"design is collinear: condition number {shown} exceeds {MAX_CONDITION_NUMBER}; "
            f"columns involved: {involved}"
        )
    return cond


def _newey_west(design: FloatArray, resid: FloatArray, lags: int) -> FloatArray:
    n, p = design.shape
    scores = design * resid[:, None]
    meat = scores.T @ scores
    for lag in range(1, lags + 1):
        cross = scores[lag:].T @ scores[:-lag]
        meat += (1.0 - lag / (lags + 1.0)) * (cross + cross.T)
    bread = np.linalg.inv(design.T @ design)
    return np.asarray(bread @ meat @ bread * n / (n - p), dtype=np.float64)


def _row(estimate: float, se: float) -> dict[str, Any]:
    """Estimate, standard error, t, two-sided normal p and 95% interval.

    At ``se == 0`` (an exact fit) there is no sampling distribution: ``t`` and ``p`` are None and
    ``edge`` is ``"zero_standard_error"``; otherwise ``edge`` is None.
    """
    t: float | None = None
    p: float | None = None
    edge: str | None = "zero_standard_error"
    if se > 0.0:
        t = estimate / se
        p = float(2.0 * stats.norm.sf(abs(t)))
        edge = None
    ci95 = [estimate - _Z95 * se, estimate + _Z95 * se]
    return {"se": se, "t": t, "p": p, "edge": edge, "ci95": ci95}


def factor_attribution(
    strategy: FloatSeq,
    factors: Any,
    *,
    periods_per_year: int,
    factor_names: Sequence[str],
) -> dict[str, Any]:
    """Regress per-period strategy returns (length N) on an N x K factor matrix, with a constant.

    The caller aligns the series by date and removes any risk-free rate. Returns, per factor,
    ``beta``, ``se``, ``t``, ``p``, ``edge`` and ``ci95``; the intercept per period and annualised
    (alpha times ``periods_per_year``) with ``alpha_se``, ``alpha_t``, ``alpha_p``, ``alpha_edge``
    and intervals; ``r_squared``, ``adj_r_squared``, ``n``, ``k``, ``hac_lags``,
    ``residual_std`` (sqrt of SSR / (N - K - 1)) and ``condition_number``. Fails loud with
    ``DataError`` on non-finite input, unequal lengths, duplicate names, fewer than
    ``min_observations(K)`` rows, a series that does not vary, or a design whose condition
    number exceeds ``MAX_CONDITION_NUMBER``.
    HAC standard errors are large-sample approximations: the 95% intervals under-cover in small
    samples, more so under serial correlation (a seeded check with N = 60, K = 2 covered about 92%
    with independent errors and about 89% with AR(1) errors, phi = 0.5; N = 500 covered about
    95-96% and 94%). Exposure to a factor is not evidence of an edge.
    """
    y = _array(strategy, "strategy", 1)
    x = _array(factors, "factors", 2)
    names = list(factor_names)
    _check_inputs(y, x, names, periods_per_year)
    n, k = int(x.shape[0]), int(x.shape[1])
    design = np.column_stack([np.ones(n), x])
    cond = _condition(design, names)
    coef = np.linalg.lstsq(design, y, rcond=None)[0]
    resid = y - design @ coef
    lags = hac_lags(n)
    se = np.sqrt(np.diag(_newey_west(design, resid, lags)))
    ssr = float(resid @ resid)
    r_squared = 1.0 - ssr / float(np.sum((y - y.mean()) ** 2))
    alpha = float(coef[0])
    alpha_row = _row(alpha, float(se[0]))
    factor_rows = [
        {"name": names[j], "beta": float(coef[j + 1]), **_row(float(coef[j + 1]), float(se[j + 1]))}
        for j in range(k)
    ]
    return {
        "alpha_per_period": alpha,
        "alpha_annual": alpha * periods_per_year,
        "alpha_se": alpha_row["se"],
        "alpha_t": alpha_row["t"],
        "alpha_p": alpha_row["p"],
        "alpha_edge": alpha_row["edge"],
        "alpha_ci95_per_period": alpha_row["ci95"],
        "alpha_ci95_annual": [bound * periods_per_year for bound in alpha_row["ci95"]],
        "factors": factor_rows,
        "r_squared": r_squared,
        "adj_r_squared": 1.0 - (1.0 - r_squared) * (n - 1) / (n - k - 1),
        "n": n,
        "k": k,
        "hac_lags": lags,
        "residual_std": math.sqrt(ssr / (n - k - 1)),
        "condition_number": cond,
        "basis": BASIS,
    }
