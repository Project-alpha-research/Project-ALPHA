"""Calendar-year shuffle and random-halves checks on the scored returns."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.resampling_more_b import DROP_KEYS, DROP_OUTPUTS, DROP_READING
from alpha_cli.toolbox.families.resampling_more_common import (
    RETURN_BASIS,
    blank,
    dated_returns,
    make_spec,
    scored,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs


def year_shuffle(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_validation.path_montecarlo import path_metric_arrays

    returns, years = dated_returns(inputs)
    distinct = sorted(set(years))
    if len(distinct) < 3:
        reason = f"The test needs at least 3 calendar years; the run has {len(distinct)}."
        return blank(DROP_KEYS, reason, RETURN_BASIS, inputs.seed)
    n = params["n_paths"]
    if n < 1 or rng is None:
        raise ValueError("n_paths must be at least 1 and a seeded generator is required")
    labels = np.asarray(years)
    blocks = [np.flatnonzero(labels == year) for year in distinct]
    rows = np.stack(
        [np.concatenate([blocks[k] for k in rng.permutation(len(blocks))]) for _ in range(n)]
    )
    drops = path_metric_arrays(returns[rows]).maximum_drawdown
    observed = float(path_metric_arrays(returns[None, :]).maximum_drawdown[0])
    median, q95 = np.quantile(drops, [0.5, 0.95])
    return Result(
        dict(
            zip(
                DROP_KEYS,
                (observed, float(median), float(q95), float(np.mean(drops >= observed))),
                strict=True,
            )
        ),
        {},
        basis=RETURN_BASIS,
        details={"seed": inputs.seed, "years": len(distinct)},
    )


YEAR_SHUFFLE = make_spec(
    "resampling.calendar_year_shuffle",
    question="Is the worst drop tied to the order of the calendar years?",
    needs=("stored_equity",),
    params=(Param("n_paths", int, 1000, None, "Number of year reorderings."),),
    outputs=DROP_OUTPUTS,
    reading=DROP_READING.replace("{what}", "Putting whole calendar years in random order"),
    caveats=(
        "Each year keeps its own bars in order, so only the sequence of years changes; the final"
        " return stays the same. With few years there are few distinct orders, and a partial first"
        " or last year counts as a year.",
    ),
    reference="test_known_answer_years",
    compute=year_shuffle,
    situations=("drawdown", "works-only-sometimes"),
    seeded=True,
)


def halves(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    returns = scored(inputs)
    keys = ("median_gap", "weaker_half", "share_both_positive")
    if len(returns) < 20:
        reason = "The halves test needs at least 20 scored bar returns."
        return blank(keys, reason, RETURN_BASIS, inputs.seed)
    n = params["n_splits"]
    if n < 1 or rng is None:
        raise ValueError("n_splits must be at least 1 and a seeded generator is required")
    order = rng.permuted(np.tile(np.arange(len(returns)), (n, 1)), axis=1)
    cut = len(returns) // 2
    parts = (returns[order[:, :cut]], returns[order[:, cut:]])
    means = [part.mean(axis=1) for part in parts]
    spreads = [part.std(axis=1, ddof=1) for part in parts]
    valid = (spreads[0] > 0) & (spreads[1] > 0)
    if not valid.any():
        return blank(keys, "Every random half had constant returns.", RETURN_BASIS, inputs.seed)
    scale = math.sqrt(inputs.stored.ppy)
    sharpes = [(m[valid] / s[valid]) * scale for m, s in zip(means, spreads, strict=True)]
    return Result(
        {
            "median_gap": float(np.median(np.abs(sharpes[0] - sharpes[1]))),
            "weaker_half": float(np.quantile(np.minimum(*sharpes), 0.05)),
            "share_both_positive": float(np.mean((means[0] > 0) & (means[1] > 0))),
        },
        {},
        basis=RETURN_BASIS,
        details={"seed": inputs.seed, "splits_used": int(valid.sum())},
    )


INTERLEAVED_HALVES = make_spec(
    "resampling.interleaved_halves",
    question="Do two random halves of the bars tell the same story?",
    needs=("stored_equity",),
    params=(Param("n_splits", int, 500, None, "Number of random splits into two halves."),),
    outputs=(
        Output(
            "median_gap",
            "Typical Sharpe gap",
            "Median absolute difference between the yearly Sharpe ratios of the two halves.",
            "ratio",
        ),
        Output(
            "weaker_half",
            "Weaker half, 1-in-20",
            "5th percentile of the lower of the two halves' yearly Sharpe ratios.",
            "ratio",
        ),
        Output(
            "share_both_positive",
            "Share both positive",
            "Share of splits where both halves had a positive average bar return.",
            "fraction",
        ),
    ),
    reading=(
        "Two random halves of the bars differed by a typical {median_gap:.2f} in yearly Sharpe"
        " ratio. In one split in twenty the weaker half was at or below {weaker_half:.2f}; both"
        " halves gained in {share_both_positive:.0%} of splits."
    ),
    caveats=(
        "Halves are drawn from the same history, so they share its market. Agreement does not"
        " show the edge holds in a later period.",
    ),
    reference="test_known_answer_halves",
    compute=halves,
    situations=("works-only-sometimes", "looks-too-good"),
    seeded=True,
)
CHECKS = (YEAR_SHUFFLE, INTERLEAVED_HALVES)
