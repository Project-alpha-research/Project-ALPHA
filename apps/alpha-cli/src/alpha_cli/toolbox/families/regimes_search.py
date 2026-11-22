"""Searches for breaks at unknown dates: Quandt-Andrews sup-F and Bai-Perron style partitions."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.regimes_base import (
    BASIS,
    dated_returns,
    spec,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

MIN_SEARCH_BARS = 60
TRIM = 0.15  # Andrews (1993) and Bai and Perron (1998): each part holds at least this share.
SUPF_KEYS = ("sup_f", "break_date", "p_value", "first_mean", "second_mean", "bars")
CHUNK = 200


def sup_f_paths(paths: FloatArray, low: int, high: int) -> tuple[FloatArray, FloatArray]:
    """Largest mean-shift F over splits low..high of each row, and the split that gave it."""
    import numpy as np

    n = paths.shape[1]
    split = np.arange(low, high + 1)
    cum = np.cumsum(paths, axis=1)
    first = cum[:, split - 1] / split
    second = (cum[:, -1:] - cum[:, split - 1]) / (n - split)
    gain = split * (n - split) / n * (first - second) ** 2
    rss0 = ((paths - paths.mean(axis=1, keepdims=True)) ** 2).sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = gain / ((rss0 - gain) / (n - 2))
    best = f.argmax(axis=1)
    return f[np.arange(paths.shape[0]), best], split[best]


def sup_f(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Quandt (1960) / Andrews (1993) supremum of Chow F; p-value by simulating normal returns."""
    import numpy as np

    sims = params["n_sims"]
    if sims < 100:
        raise ValueError("n_sims must be at least 100")
    dates, returns = dated_returns(inputs)
    n = returns.size
    if n < MIN_SEARCH_BARS:
        return unavailable(SUPF_KEYS, f"Needs at least {MIN_SEARCH_BARS} scored bars; found {n}.")
    low = math.ceil(TRIM * n)
    high = n - low
    observed, at = sup_f_paths(returns[None, :], low, high)
    if not np.isfinite(observed[0]):
        return unavailable(
            SUPF_KEYS, "Returns do not vary or fit a break exactly, so no test applies."
        )
    assert rng is not None
    beaten = 0
    for start in range(0, sims, CHUNK):
        draws = rng.standard_normal((min(CHUNK, sims - start), n))
        beaten += int((sup_f_paths(draws, low, high)[0] >= observed[0]).sum())
    cut = int(at[0])
    return Result(
        {
            "sup_f": float(observed[0]),
            "break_date": dates[cut].date().isoformat(),
            "p_value": (1 + beaten) / (1 + sims),
            "first_mean": float(returns[:cut].mean()),
            "second_mean": float(returns[cut:].mean()),
            "bars": int(n),
        },
        {},
        details={
            "simulations": sims,
            "searched_from": dates[low].date().isoformat(),
            "searched_to": dates[high].date().isoformat(),
        },
        basis=BASIS,
    )


SUP_F = spec(
    "regimes.sup_f",
    "Is there a break in the average return at a date I did not name?",
    ("stored_equity",),
    (
        Output(
            "sup_f",
            "Largest F",
            "Largest Chow F over every split date in the middle 70 percent of bars.",
            "ratio",
        ),
        Output(
            "break_date",
            "Best split date",
            "First date of the second part at the largest F.",
            "date",
        ),
        Output(
            "p_value",
            "Simulated p-value",
            "Share of simulated no-break histories of the same length with an equal or larger F.",
            "p_value",
        ),
        Output(
            "first_mean",
            "Mean bar return before",
            "Average return per bar before the best split.",
            "fraction",
        ),
        Output(
            "second_mean",
            "Mean bar return after",
            "Average return per bar from the best split on.",
            "fraction",
        ),
        Output("bars", "Bars", "Number of scored bars.", "count"),
    ),
    "The best split was {break_date}: {first_mean:.4%} per bar before and {second_mean:.4%} after"
    " (largest F {sup_f:.2f}, simulated p-value {p_value:.3f}).",
    "This is the sup-F test of Quandt (1960) and Andrews (1993). The p-value comes from seeded"
    " simulation of independent normal returns, so fat tails or volatility clusters make it too"
    " small. It finds one break only; the first and last 15 percent of bars are not searched.",
    "test_sup_f_known_answer",
    sup_f,
    params=(
        Param(
            "n_sims",
            int,
            2000,
            None,
            "Number of simulated no-break histories for the p-value; at least 100.",
        ),
    ),
    kind="test",
    seeded=True,
)

BREAK_KEYS = ("breaks", "first_break", "last_break", "largest_gap", "bars")
GRID = 1000  # at most this many candidate break positions, so long histories stay fast


def best_partitions(y: FloatArray, most: int, min_len: int) -> tuple[list[float], list[list[int]]]:
    """Least-squares partitions into 1..most+1 constant-mean parts (Bai and Perron 1998, dynamic
    programme); returns each partition's residual sum of squares and its break positions."""
    import numpy as np

    n = y.size
    grid = np.unique(np.append(np.arange(0, n, max(1, n // GRID)), n))
    total, squares = np.append(0.0, np.cumsum(y)), np.append(0.0, np.cumsum(y * y))
    width = grid[None, :] - grid[:, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        sums = total[grid][None, :] - total[grid][:, None]
        cost = (squares[grid][None, :] - squares[grid][:, None]) - sums**2 / width
    cost = np.where(width >= min_len, np.maximum(cost, 0.0), np.inf)
    best = cost[0].copy()
    rss, choices = [float(best[-1])], []
    for _ in range(most):
        stacked = best[:, None] + cost
        choices.append(stacked.argmin(axis=0))
        best = stacked.min(axis=0)
        rss.append(float(best[-1]))
    partitions: list[list[int]] = [[]]
    for count in range(1, most + 1):
        at, cuts = len(grid) - 1, []
        for level in range(count - 1, -1, -1):
            at = int(choices[level][at])
            cuts.append(int(grid[at]))
        partitions.append(sorted(cuts))
    return rss, partitions


def bai_perron(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    dates, returns = dated_returns(inputs)
    n = returns.size
    if n < MIN_SEARCH_BARS:
        return unavailable(BREAK_KEYS, f"Needs at least {MIN_SEARCH_BARS} scored bars; found {n}.")
    if np.ptp(returns) == 0:
        return unavailable(BREAK_KEYS, "Returns do not vary, so no break can be placed.")
    min_len = max(2, math.ceil(TRIM * n))
    most = min(params["max_breaks"], n // min_len - 1)
    rss, partitions = best_partitions(returns, most, min_len)
    # Yao (1988) criterion: n ln(RSS / n) + (2m + 1) ln n for m breaks.
    score = [
        n * math.log(max(r / n, 1e-300)) + (2 * m + 1) * math.log(n) for m, r in enumerate(rss)
    ]
    chosen = int(np.argmin(score))
    cuts = partitions[chosen]
    edges = [0, *cuts, n]
    means = [float(returns[a:b].mean()) for a, b in zip(edges, edges[1:], strict=False)]
    values: dict[str, Any] = {
        "breaks": chosen,
        "first_break": dates[cuts[0]].date().isoformat() if cuts else None,
        "last_break": dates[cuts[-1]].date().isoformat() if cuts else None,
        "largest_gap": max(abs(b - a) for a, b in zip(means, means[1:], strict=False))
        if cuts
        else 0.0,
        "bars": int(n),
    }
    reason = "No break was chosen, so the history is read as one part."
    reasons = {k: reason for k in ("first_break", "last_break") if values[k] is None}
    parts = [
        {"first_date": dates[a].date().isoformat(), "bars": b - a, "mean_return": m}
        for (a, b), m in zip(zip(edges, edges[1:], strict=False), means, strict=True)
    ]
    return Result(values, reasons, details={"parts": parts, "criterion": score}, basis=BASIS)


BAI_PERRON = spec(
    "regimes.break_count",
    "How many breaks in the average return, and where?",
    ("stored_equity",),
    (
        Output(
            "breaks",
            "Breaks chosen",
            "Number of breaks in the mean return picked by an information criterion.",
            "count",
        ),
        Output(
            "first_break",
            "First break",
            "First date of the second part, when a break was chosen.",
            "date",
        ),
        Output(
            "last_break",
            "Last break",
            "First date of the last part, when a break was chosen.",
            "date",
        ),
        Output(
            "largest_gap",
            "Largest step",
            "Largest difference in mean bar return between neighbouring parts.",
            "fraction",
        ),
        Output("bars", "Bars", "Number of scored bars.", "count"),
    ),
    "The information criterion chose {breaks} breaks in the mean return. The largest step in the"
    " average bar return between neighbouring parts was {largest_gap:.4%}; it is zero when there is"
    " no break.",
    "This follows Bai and Perron (1998) for up to five breaks, with parts of at least 15 percent of"
    " the bars, but it picks the count by the Yao (1988) criterion instead of their sequential"
    " tests, so it gives no p-value. Breaks are placed to within a few bars on long histories.",
    "test_break_count_known_answer",
    bai_perron,
    params=(
        Param("max_breaks", int, 3, range(1, 6), "Largest number of breaks to look for, 1 to 5."),
    ),
    kind="test",
)
