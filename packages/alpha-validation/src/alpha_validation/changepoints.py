"""Change points: dates at which a series' behaviour shifted, described with hindsight.

Thin glue over ``ruptures``; no search or cost function is written here. The search is the
penalised exact method PELT (Killick, Fearnhead and Eckley 2012, "Optimal Detection of
Changepoints With a Linear Computational Cost", JASA 107(500)) in ruptures' compiled kernel
implementation ``KernelCPD`` (Celisse, Marot, Pierre-Jean and Rigaill 2018; Arlot, Celisse and
Harchaoui 2019, JMLR 20(162)). It returns the same breaks as ``ruptures.Pelt(model, jump=1)``
with the matching cost ("rbf", or "l2" as the linear kernel) and is hundreds of times faster.

Every break is found using the whole series, later bars included: the output is a description
of the past and carries the label ``hindsight``. It must never drive a trading decision.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import ruptures

from alpha_validation.metrics import FloatArray, FloatSeq

KERNELS = {"rbf": "rbf", "l2": "linear"}
PENALTY_GROWTH = 2.0
MAX_RAISES = 60
BASIS = {
    "rbf": (
        "penalised kernel change-point search (PELT, Gaussian kernel with the median bandwidth): "
        "finds shifts in the whole distribution, such as a change in volatility; default "
        "penalty 2 * log(n) because each bar's kernel cost is at most 1 (a common heuristic); "
        "breaks use the whole series (hindsight)"
    ),
    "l2": (
        "penalised least-squares change-point search (PELT): finds shifts in the mean level; "
        "default penalty 2 * log(n) * noise variance, the variance estimated robustly from "
        "first differences; breaks use the whole series (hindsight)"
    ),
}


def noise_variance(x: FloatArray) -> float:
    """Robust noise variance from first differences, so level shifts do not inflate it.

    ``sigma = 1.4826 * median(|d - median(d)|) / sqrt(2)`` for ``d = diff(x)``: 1.4826 makes the
    median absolute deviation consistent for a normal standard deviation, and a difference of
    two independent bars has twice the variance of one.
    """
    d = np.diff(x)
    sigma = 1.4826 * float(np.median(np.abs(d - np.median(d)))) / math.sqrt(2.0)
    return sigma * sigma


def default_penalty(x: FloatArray, model: str) -> float:
    """``2 * log(n)`` times the model's cost scale (1 for "rbf", the noise variance for "l2")."""
    scale = 1.0 if model == "rbf" else noise_variance(x)
    return 2.0 * math.log(x.size) * scale


def change_points(
    series: FloatSeq,
    *,
    model: str = "rbf",
    penalty: float | None = None,
    min_size: int = 20,
    max_points: int = 8,
) -> dict[str, Any]:
    """Split a series into segments at penalised change points and describe each segment.

    ``breaks`` holds the index of the first observation of every segment after the first. When
    more than ``max_points`` breaks are found the penalty is doubled until at most that many
    remain; ``penalty`` reports the value finally used and ``penalty_raises`` how often it was
    doubled. Fails loud (``ValueError``) on non-finite input, an unknown model, a series that
    does not vary, or fewer than ``3 * min_size`` points.
    """
    if model not in KERNELS:
        raise ValueError(f"unknown change-point model {model!r}; known: {', '.join(KERNELS)}")
    if min_size < 2:
        raise ValueError(f"min_size must be at least 2, got {min_size}")
    if max_points < 1:
        raise ValueError(f"max_points must be at least 1, got {max_points}")
    x = np.asarray(series, dtype=np.float64)
    if x.ndim != 1:
        raise ValueError(f"series must be one-dimensional, got shape {x.shape}")
    if not bool(np.all(np.isfinite(x))):
        raise ValueError("series contains a missing or infinite value")
    n = int(x.size)
    if n < 3 * min_size:
        raise ValueError(
            f"change points need at least 3 * min_size = {3 * min_size} points, got {n}"
        )
    if float(np.ptp(x)) <= 0.0:
        raise ValueError("the series does not vary, so it has no change points")
    used = default_penalty(x, model) if penalty is None else float(penalty)
    if not math.isfinite(used) or used <= 0.0:
        raise ValueError(f"penalty must be a positive number, got {used}")
    search = ruptures.KernelCPD(kernel=KERNELS[model], min_size=min_size).fit(x)
    raises = 0
    ends = [int(end) for end in search.predict(pen=used)]
    while len(ends) - 1 > max_points:
        if raises >= MAX_RAISES:
            raise ValueError(f"more than {max_points} change points remain at penalty {used}")
        used *= PENALTY_GROWTH
        raises += 1
        ends = [int(end) for end in search.predict(pen=used)]
    starts = [0, *ends[:-1]]
    segments = [
        {
            "start": start,
            "end": end,
            "n": end - start,
            "mean": float(np.mean(x[start:end])),
            "std": float(np.std(x[start:end], ddof=1)),
        }
        for start, end in zip(starts, ends, strict=True)
    ]
    return {
        "breaks": ends[:-1],
        "segments": segments,
        "n": n,
        "model": model,
        "min_size": min_size,
        "max_points": max_points,
        "penalty": used,
        "penalty_raises": raises,
        "labels": ["hindsight"],
        "basis": BASIS[model],
    }
