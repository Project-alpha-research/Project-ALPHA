"""Leave-one-out and stress readings: trade order, single trades, single years, bigger swings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result
from alpha_cli.toolbox.families.resampling_more_common import (
    N_PATHS,
    TRADE_BASIS,
    blank,
    closed_trades,
    make_spec,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray


def worst_drops(pnl: FloatArray, start: float) -> Any:
    """Largest fall from a running high, as a fraction of that high, for each row of profits."""
    import numpy as np

    equity = np.concatenate(
        (np.full((pnl.shape[0], 1), start), start + np.cumsum(pnl, axis=1)), axis=1
    )
    return (1.0 - equity / np.maximum.accumulate(equity, axis=1)).max(axis=1)


def trade_order(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    run = inputs.stored
    pnl = closed_trades(run)
    keys = ("observed", "median", "q95")
    if len(pnl) < 5:
        reason = f"The reshuffle needs at least 5 closed trades; the run has {len(pnl)}."
        return blank(keys, reason, TRADE_BASIS, inputs.seed)
    n = params["n_paths"]
    if n < 1 or rng is None:
        raise ValueError("n_paths must be at least 1 and a seeded generator is required")
    cash = run.require_cash()
    observed = float(worst_drops(pnl[None, :], float(cash))[0])
    drops = worst_drops(rng.permuted(np.tile(pnl, (n, 1)), axis=1), float(cash))
    median, q95 = np.quantile(drops, [0.5, 0.95])
    return Result(
        {"observed": observed, "median": float(median), "q95": float(q95)},
        {},
        basis=TRADE_BASIS,
        details={"seed": inputs.seed},
    )


TRADE_ORDER = make_spec(
    "resampling.trade_order_drawdown",
    question="How much does the worst drop depend on the order of the trades?",
    needs=("run_trades",),
    params=(N_PATHS,),
    outputs=(
        Output(
            "observed",
            "Worst drop in trade order",
            "Largest fall of starting cash plus running trade profit, in the order trades opened.",
            "fraction",
        ),
        Output(
            "median",
            "Typical reordered worst drop",
            "Median worst drop over random orders of the same trades.",
            "fraction",
        ),
        Output(
            "q95",
            "1-in-20 reordered worst drop",
            "95th percentile of those worst drops: one order in 20 fell further.",
            "fraction",
        ),
    ),
    reading=(
        "Worst drop of the trade-by-trade account: {observed:.1%}. The same trades in random order"
        " gave a typical worst drop of {median:.1%}; one order in twenty fell further than"
        " {q95:.1%}."
    ),
    caveats=(
        "Trades are added to the starting cash one after the other, with no overlap and no"
        " resizing, so it ignores how open trades overlap. Reordering shows luck of sequence only.",
    ),
    reference="test_known_answer_trade_order",
    compute=trade_order,
    situations=("drawdown", "few-trades"),
    seeded=True,
)


def trade_jackknife(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Leave-one-out means with Tukey's (1958) jackknife standard error (Quenouille 1949)."""
    import numpy as np

    pnl = closed_trades(inputs.stored)
    keys = ("mean", "lowest", "highest", "std_error")
    if len(pnl) < 3:
        reason = f"The jackknife needs at least 3 closed trades; the run has {len(pnl)}."
        return blank(keys, reason, TRADE_BASIS)
    n = len(pnl)
    leave_out = (pnl.sum() - pnl) / (n - 1)
    error = np.sqrt((n - 1) / n * np.sum((leave_out - leave_out.mean()) ** 2))
    return Result(
        {
            "mean": float(pnl.mean()),
            "lowest": float(leave_out.min()),
            "highest": float(leave_out.max()),
            "std_error": float(error),
        },
        {},
        basis=TRADE_BASIS,
    )


TRADE_JACKKNIFE = make_spec(
    "resampling.trade_jackknife",
    question="Does any single trade drive the average profit per trade?",
    needs=("run_trades",),
    params=(),
    outputs=(
        Output(
            "mean", "Average profit per trade", "Mean after-cost profit of all trades.", "currency"
        ),
        Output(
            "lowest",
            "Lowest average without one trade",
            "Smallest mean profit after dropping any one trade.",
            "currency",
        ),
        Output(
            "highest",
            "Highest average without one trade",
            "Largest mean profit after dropping any one trade.",
            "currency",
        ),
        Output(
            "std_error",
            "Jackknife standard error",
            "Standard error of the average from the leave-one-out means (Tukey 1958).",
            "currency",
        ),
    ),
    reading=(
        "Average profit per trade was {mean:.2f}. Dropping each trade in turn moved it between"
        " {lowest:.2f} and {highest:.2f} (jackknife standard error {std_error:.2f})."
    ),
    caveats=(
        "It drops one trade at a time, so two large trades that carry the result together are"
        " not separated. trades.concentration drops the best several at once.",
    ),
    reference="test_known_answer_jackknife",
    compute=trade_jackknife,
    situations=("lucky-trades", "few-trades"),
    seeded=False,
)

CHECKS = (TRADE_ORDER, TRADE_JACKKNIFE)
