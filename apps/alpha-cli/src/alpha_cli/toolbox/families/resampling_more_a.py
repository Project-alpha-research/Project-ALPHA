"""Fixed-block, circular-block and wild bootstraps, and the chance of a ruinous drop."""

from __future__ import annotations

import math
from functools import partial
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.resampling_more_common import (
    N_PATHS,
    PAST,
    RETURN_BASIS,
    blank,
    make_spec,
    scored,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

PATH_KEYS = ("low", "median", "high", "drop_q95")
PATH_OUTPUTS = (
    Output("low", "Low final return", "5th percentile of final return.", "fraction"),
    Output("median", "Typical final return", "Median final return.", "fraction"),
    Output("high", "High final return", "95th percentile of final return.", "fraction"),
    Output(
        "drop_q95",
        "1-in-20 worst drop",
        "95th percentile of the worst drops: one history in 20 fell further.",
        "fraction",
    ),
)


def fixed_block_indices(n: int, block: int, n_paths: int, rng: Generator, *, circular: bool) -> Any:
    """Rows of bar positions built from equal blocks, cut to the length of the history.

    Moving blocks (Kuensch 1989) start only where a whole block fits; circular blocks
    (Politis and Romano 1992) start anywhere and wrap past the end.
    """
    import numpy as np

    n_blocks = math.ceil(n / block)
    starts = rng.integers(0, n if circular else n - block + 1, size=(n_paths, n_blocks))
    rows = (starts[:, :, None] + np.arange(block)).reshape(n_paths, n_blocks * block)[:, :n]
    return rows % n


def block_family(
    inputs: Inputs, params: dict[str, Any], rng: Generator | None, *, circular: bool
) -> Result:
    import numpy as np

    from alpha_validation.path_montecarlo import path_metric_arrays

    returns = scored(inputs)
    block, n_paths = params["block_length"], params["n_paths"]
    if block < 1 or n_paths < 1:
        raise ValueError("block_length and n_paths must be at least 1")
    if len(returns) < 2:
        reason = "Paths need at least 2 scored bar returns."
        return blank(PATH_KEYS, reason, RETURN_BASIS, inputs.seed)
    if block > len(returns):
        reason = f"The block of {block} bars is longer than the {len(returns)} scored returns."
        return blank(PATH_KEYS, reason, RETURN_BASIS, inputs.seed)
    if rng is None:
        raise ValueError("Block bootstrap paths require a seeded generator")
    rows = fixed_block_indices(len(returns), block, n_paths, rng, circular=circular)
    metrics = path_metric_arrays(returns[rows])
    low, median, high = np.quantile(metrics.terminal_return, [0.05, 0.5, 0.95])
    return Result(
        dict(
            zip(
                PATH_KEYS,
                (
                    float(low),
                    float(median),
                    float(high),
                    float(np.quantile(metrics.maximum_drawdown, 0.95)),
                ),
                strict=True,
            )
        ),
        {},
        basis=RETURN_BASIS,
        details={"seed": inputs.seed},
    )


BLOCK_PARAMS = (
    N_PATHS,
    Param("block_length", int, 5, None, "Number of consecutive bars per block."),
)
BLOCK_READING = (
    "Redrawing {kind} blocks gave a typical final return of {{median:+.1%}}. Nine histories in ten"
    " ended between {{low:+.1%}} and {{high:+.1%}}. One in twenty had a worst drop deeper than"
    " {{drop_q95:.1%}}."
)
MOVING_BLOCKS = make_spec(
    "resampling.moving_block_paths",
    question="What range of final return and worst drop do fixed blocks of bars give?",
    needs=("stored_equity",),
    params=BLOCK_PARAMS,
    outputs=PATH_OUTPUTS,
    reading=BLOCK_READING.format(kind="fixed-length"),
    caveats=(
        "Blocks of one fixed length keep short runs of bars together, but bars near the ends join"
        " fewer blocks. " + PAST,
    ),
    reference="test_known_answer_blocks",
    compute=partial(block_family, circular=False),
    situations=("drawdown", "return-range"),
    seeded=True,
)
CIRCULAR_BLOCKS = make_spec(
    "resampling.circular_block_paths",
    question="What range of final return and worst drop do blocks wrapped around the history give?",
    needs=("stored_equity",),
    params=BLOCK_PARAMS,
    outputs=PATH_OUTPUTS,
    reading=BLOCK_READING.format(kind="wrapped-around"),
    caveats=(
        "Blocks may run past the last bar and continue from the first, which joins the end of"
        " the history to its start. " + PAST,
    ),
    reference="test_known_answer_blocks",
    compute=partial(block_family, circular=True),
    situations=("drawdown", "return-range"),
    seeded=True,
)


def wild(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Wild bootstrap of the mean bar return (Wu 1986; Liu 1988) with Mammen's (1993) weights."""
    import numpy as np

    returns = scored(inputs)
    keys = ("mean", "lower", "upper", "share_at_or_below_zero")
    if len(returns) < 3:
        return blank(
            keys, "The range needs at least 3 scored bar returns.", RETURN_BASIS, inputs.seed
        )
    if returns.min() == returns.max():
        return blank(
            keys, "A reportable range needs varying scored returns.", RETURN_BASIS, inputs.seed
        )
    confidence, n_resamples = params["confidence"], params["n_resamples"]
    if not 0.0 < confidence < 1.0 or n_resamples < 1:
        raise ValueError("confidence must be inside (0, 1) and n_resamples at least 1")
    if rng is None:
        raise ValueError("The wild bootstrap requires a seeded generator")
    mean = float(returns.mean())
    root = math.sqrt(5.0)
    # Two-point weights with mean 0, variance 1 and third moment 1.
    small, large = (1.0 - root) / 2.0, (1.0 + root) / 2.0
    draws = rng.random((n_resamples, len(returns))) < (root + 1.0) / (2.0 * root)
    weights = np.where(draws, small, large)
    means = mean + (weights * (returns - mean)).mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(means, [tail, 1.0 - tail])
    return Result(
        {
            "mean": mean,
            "lower": float(lower),
            "upper": float(upper),
            "share_at_or_below_zero": float(np.mean(means <= 0.0)),
        },
        {},
        basis=RETURN_BASIS,
        details={"seed": inputs.seed},
    )


WILD_BOOTSTRAP = make_spec(
    "resampling.wild_bootstrap",
    question="What range of average bar return holds when bars of different size are weighted?",
    needs=("stored_equity",),
    params=(
        Param("n_resamples", int, 2000, None, "Number of weighted redraws."),
        Param("confidence", float, 0.95, None, "Confidence level for the two-sided interval."),
    ),
    outputs=(
        Output("mean", "Average bar return", "Mean after-cost return per bar.", "fraction"),
        Output("lower", "Lower limit", "Lower end of the wild-bootstrap interval.", "fraction"),
        Output("upper", "Upper limit", "Upper end of the wild-bootstrap interval.", "fraction"),
        Output(
            "share_at_or_below_zero",
            "Share at or below zero",
            "Share of redraws whose average bar return was zero or lower.",
            "fraction",
        ),
    ),
    reading=(
        "Average bar return was {mean:.4%}. Re-weighting each bar's distance from that average"
        " puts it between {lower:.4%} and {upper:.4%}; {share_at_or_below_zero:.0%} of redraws"
        " were at or below zero."
    ),
    caveats=(
        "Each bar keeps its own size of surprise, so it copes with calm and turbulent bars, but"
        " it treats bars as unrelated to their neighbours. It cannot tell you why the average"
        " is what it is.",
    ),
    reference="test_known_answer_wild",
    compute=wild,
    situations=("return-range", "looks-too-good", "few-trades"),
    seeded=True,
)


def ruin(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation.bootstrap import risk_of_ruin

    returns = scored(inputs)
    keys = ("ruin_share", "std_error")
    if len(returns) < 2:
        return blank(keys, "Paths need at least 2 scored bar returns.", RETURN_BASIS, inputs.seed)
    share = risk_of_ruin(
        returns,
        ruin_drawdown=params["ruin_drawdown"],
        n_paths=params["n_paths"],
        mean_block=params["mean_block"],
        seed=inputs.seed,
    )
    error = math.sqrt(share * (1.0 - share) / params["n_paths"])
    return Result(
        {"ruin_share": share, "std_error": error},
        {},
        basis=RETURN_BASIS,
        details={"seed": inputs.seed},
    )


RISK_OF_RUIN = make_spec(
    "resampling.risk_of_ruin",
    question="How often does a redrawn history fall past a ruinous drop?",
    needs=("stored_equity",),
    params=(
        Param("ruin_drawdown", float, 0.5, None, "Peak-to-trough fall counted as ruin, 0 to 1."),
        Param("n_paths", int, 1000, None, "Number of redrawn histories."),
        Param("mean_block", float, 5.0, None, "Mean number of consecutive bars in a block."),
    ),
    outputs=(
        Output(
            "ruin_share",
            "Share of ruined histories",
            "Share of redrawn histories whose worst drop reached the ruin level.",
            "fraction",
        ),
        Output(
            "std_error",
            "Draw error",
            "Standard error of that share from the number of redraws alone.",
            "fraction",
        ),
    ),
    reading=(
        "{ruin_share:.1%} of redrawn histories fell past the ruin level (draw error"
        " {std_error:.1%})."
    ),
    caveats=(
        "A share of zero means none of these redraws reached the level, not that it cannot"
        " happen. " + PAST,
    ),
    reference="test_known_answer_ruin",
    compute=ruin,
    situations=("drawdown",),
    seeded=True,
)
CHECKS = (MOVING_BLOCKS, CIRCULAR_BLOCKS, WILD_BOOTSTRAP, RISK_OF_RUIN)
