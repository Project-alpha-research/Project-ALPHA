"""Shared reads and result helpers for the risk and attribution checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_cli.toolbox.situations import Situation
    from alpha_validation import FloatArray

TRADE_BASIS = "After-cost realized profit on closed walk-forward trades, in account currency."
BASIS = "After-cost bar returns from the stored walk-forward equity curve."
POISON = "tests/unit/test_toolbox_risk_sizing.py::test_future_input_rejected"
CONFIDENCE = Param(
    "confidence",
    float,
    0.95,
    (0.9, 0.95, 0.975, 0.99),
    "Share of bars the loss figure should cover (0.95 means a loss worse than it in 1 bar in 20).",
)
PAST = (
    "It describes this one history and cannot tell you how large the next loss will be if"
    " markets change character."
)


def unavailable(keys: tuple[str, ...] | list[str], reason: str, basis: str = BASIS) -> Result:
    return Result(dict.fromkeys(keys), dict.fromkeys(keys, reason), basis=basis)


def bar_returns(inputs: Inputs) -> FloatArray:
    """Scored after-cost bar returns; dates are checked against the recorded run period."""
    return inputs.stored.scored_returns()


def equity_and_dates(inputs: Inputs) -> tuple[FloatArray, list[datetime]]:
    from alpha_validation.metrics import to_returns

    run = inputs.stored
    frame = run.table("stored_equity", "ts", "equity")
    dates = run.dates(frame, "stored_equity") if frame.height else []
    equity = frame["equity"].to_numpy()
    if equity.size >= 2:
        to_returns(equity)  # fails loud on a non-finite or non-positive curve
    return equity, dates


@dataclass(frozen=True)
class Trades:
    """Closed trades in entry order: profit in currency, return on the amount used, and dates."""

    pnl: FloatArray
    ret: FloatArray
    entry: list[datetime]
    exit: list[datetime]


def closed_trades(inputs: Inputs) -> Trades:
    import numpy as np

    run = inputs.stored
    frame = run.table(
        "run_trades", "entry_ts", "exit_ts", "realized_pnl", "quantity", "entry_price"
    )
    for entry, exit_ts in frame.select("entry_ts", "exit_ts").iter_rows():
        if any(not isinstance(ts, datetime) or ts.utcoffset() is None for ts in (entry, exit_ts)):
            raise ValueError("Closed trades require timezone-aware entry and exit dates")
        if entry >= exit_ts or exit_ts > run.last_ts:
            raise ValueError(
                "Closed trades require entry before exit within the recorded run period"
            )
    ordered = frame.sort("entry_ts", maintain_order=True)
    pnl = ordered["realized_pnl"].to_numpy().astype(np.float64)
    quantity = ordered["quantity"].to_numpy().astype(np.float64)
    price = ordered["entry_price"].to_numpy().astype(np.float64)
    cost = quantity * price
    if not (np.isfinite(pnl).all() and np.isfinite(cost).all() and (cost > 0).all()):
        raise ValueError("trades.parquet requires finite profit and positive quantity * price")
    # After-cost return on the amount used: realized_return leaves commissions out.
    ret = pnl / cost
    return Trades(pnl, ret, ordered["entry_ts"].to_list(), ordered["exit_ts"].to_list())


def too_few_trades(count: int, minimum: int) -> str | None:
    if count < minimum:
        return f"Needs at least {minimum} closed trades; found {count}."
    return None


def check(
    tool_id: str,
    tests: str,
    *,
    question: str,
    answers: tuple[str, ...],
    situations: tuple[Situation, ...],
    needs: tuple[Literal["stored_equity", "run_trades"], ...],
    outputs: tuple[Output, ...],
    reading: str,
    caveats: tuple[str, ...],
    compute: Callable[[Inputs, dict[str, Any], Generator | None], Result],
    params: tuple[Param, ...] = (),
    family: str = "risk",
    cost: Literal["instant", "seconds", "minutes"] = "instant",
) -> ToolSpec:
    """One diagnostic check: its reference is the known-answer test named like the check."""
    return ToolSpec(
        id=tool_id,
        answers=answers,
        situations=situations,
        family=family,
        question=question,
        needs=needs,
        params=params,
        outputs=outputs,
        reading=reading,
        caveats=caveats,
        reference=f"tests/unit/{tests}.py::test_{tool_id.split('.')[1]}",
        compute=compute,
        cost=cost,
        time_safety="hindsight",
        poison_test=POISON,
    )
