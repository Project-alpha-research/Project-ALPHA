"""Correlation with a 95% interval by the Fisher z-transformation, and a two-sided p-value.

``z = atanh(r)`` is approximately normal with standard error ``1 / sqrt(n - 3)`` (Fisher 1915,
Biometrika 10, and 1921, Metron 1); the interval is the back-transform ``tanh(z -+ 1.96 * se)``.
The p-value tests rho = 0 with ``z * sqrt(n - 3)`` against the standard normal.

Assumption: independent pairs from a roughly bivariate normal distribution. Serial correlation in
either series makes the interval too narrow and the test over-reject. No effective-N adjustment
is made: with serially correlated data the interval and the p-value are too optimistic.

``method="spearman"`` runs Pearson on average ranks (ties share the mean rank) and applies the
same Fisher interval. That is an approximation: the variance of the transformed rank correlation is
somewhat larger than ``1 / (n - 3)``; Fieller, Hartley and Pearson (1957, Biometrika 44) give
about ``1.06 / (n - 3)`` for bivariate normal data, so the interval is about 3% too narrow there
(a seeded check at n = 50, rho = 0.5 covered about 94%).

A correlation is not evidence of an edge.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

from alpha_core import DataError
from alpha_validation.metrics import FloatArray, FloatSeq

MIN_PAIRS = 4
_Z95 = float(stats.norm.ppf(0.975))
_PERFECT = 1e-12
_ASSUMPTION = (
    "independent pairs, roughly bivariate normal; serial correlation makes the interval too "
    "narrow; interval assumes independent pairs (no effective-N adjustment)"
)
_SPEARMAN_NOTE = (
    "; Spearman: Pearson on average ranks with the Fisher interval, an approximation that is "
    "slightly narrow"
)


def _vector(values: FloatSeq, name: str) -> FloatArray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise DataError(f"{name} must be one-dimensional, got shape {arr.shape}")
    if not bool(np.all(np.isfinite(arr))):
        raise DataError(f"{name} contains a missing or infinite value")
    return arr


def correlation_interval(x: FloatSeq, y: FloatSeq, *, method: str = "pearson") -> dict[str, Any]:
    """Correlation of two equal-length series with a Fisher 95% interval and a two-sided p-value.

    Returns ``r``, ``n``, ``z``, ``se_z``, ``ci95``, ``p``, ``edge``, ``method``, ``assumption``. At
    ``|r| = 1`` Fisher's z is infinite: the result is ``r = +-1``, ``ci95 = [r, r]``, ``p = 0``,
    ``z = None`` and ``edge = "perfect_correlation"``; otherwise ``edge`` is None. Fails loud
    with ``DataError`` on non-finite values, unequal lengths, fewer than 4 pairs, a series that
    does not vary, or an unknown method.
    """
    if method not in ("pearson", "spearman"):
        raise DataError(f"method must be 'pearson' or 'spearman', got {method!r}")
    a = _vector(x, "x")
    b = _vector(y, "y")
    if a.size != b.size:
        raise DataError(f"x and y must have equal length, got {a.size} and {b.size}")
    n = int(a.size)
    if n < MIN_PAIRS:
        raise DataError(f"a correlation interval needs at least {MIN_PAIRS} pairs, got {n}")
    if float(np.ptp(a)) <= 0.0 or float(np.ptp(b)) <= 0.0:
        raise DataError("a series does not vary, so its correlation is undefined")
    if method == "spearman":
        a, b = stats.rankdata(a), stats.rankdata(b)
    r = float(np.clip(np.corrcoef(a, b)[0, 1], -1.0, 1.0))
    se = 1.0 / math.sqrt(n - 3)
    note = _SPEARMAN_NOTE if method == "spearman" else ""
    base = {"n": n, "se_z": se, "edge": None, "method": method, "assumption": _ASSUMPTION + note}
    if abs(r) >= 1.0 - _PERFECT:
        sign = math.copysign(1.0, r)
        base["edge"] = "perfect_correlation"
        return {"r": sign, "z": None, "ci95": [sign, sign], "p": 0.0, **base}
    z = math.atanh(r)
    return {
        "r": r,
        "z": z,
        "ci95": [math.tanh(z - _Z95 * se), math.tanh(z + _Z95 * se)],
        "p": float(2.0 * stats.norm.sf(abs(z) / se)),
        **base,
    }
