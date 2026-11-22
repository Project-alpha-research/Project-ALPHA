"""Shared helpers for the extra resampling checks: stored inputs, blank results, spec defaults."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec
from alpha_cli.toolbox.situations import Situation

if TYPE_CHECKING:
    from alpha_cli.toolbox.inputs import Inputs, Target
    from alpha_validation import FloatArray

TESTS = "tests/unit/test_toolbox_resampling_more.py::"
RETURN_BASIS = "After-cost bar returns from the stored walk-forward equity curve."
TRADE_BASIS = "After-cost realized profit on closed walk-forward trades, in account currency."
PAST = (
    "It assumes the future looks like this history; it cannot tell you how the rule will do if"
    " markets change character."
)
N_PATHS = Param("n_paths", int, 2000, None, "Number of redrawn histories.")


def blank(keys: tuple[str, ...], reason: str, basis: str, seed: int | None = None) -> Result:
    """A "too little to read" result: every output carries the reason."""
    details = {} if seed is None else {"seed": seed}
    return Result(dict.fromkeys(keys), dict.fromkeys(keys, reason), details=details, basis=basis)


def scored(inputs: Inputs) -> FloatArray:
    return inputs.stored.scored_returns()


def dated_returns(inputs: Inputs) -> tuple[FloatArray, list[int]]:
    """Scored returns with the calendar year of the bar that ended each interval."""
    run = inputs.stored
    returns = run.scored_returns()
    if len(returns) < 1:
        return returns, []
    frame = run.table("stored_equity", "ts")
    return returns, [ts.year for ts in run.dates(frame, "stored_equity")[1:]]


def closed_trades(run: Target) -> FloatArray:
    """After-cost profit of each closed trade, in entry order; bad or future dates fail loud."""
    frame = run.table("run_trades", "entry_ts", "exit_ts", "realized_pnl")
    for entry, exit_ts in frame.select("entry_ts", "exit_ts").iter_rows():
        if any(not isinstance(ts, datetime) or ts.utcoffset() is None for ts in (entry, exit_ts)):
            raise ValueError("Closed trades require timezone-aware entry and exit dates")
        if entry >= exit_ts or exit_ts > run.last_ts:
            raise ValueError(
                "Closed trades require entry before exit within the recorded run period"
            )
    return frame.sort("entry_ts", maintain_order=True)["realized_pnl"].to_numpy()


def make_spec(
    tool_id: str,
    *,
    question: str,
    needs: tuple[Any, ...],
    params: tuple[Param, ...],
    outputs: tuple[Output, ...],
    reading: str,
    caveats: tuple[str, ...],
    reference: str,
    compute: Any,
    situations: tuple[Situation, ...],
    seeded: bool,
    kind: Any = "test",
) -> ToolSpec:
    return ToolSpec(
        id=tool_id,
        answers=(question,),
        situations=situations,
        family="resampling",
        kind=kind,
        look="test" if kind == "test" else "describe",
        question=question,
        needs=needs,
        params=params,
        outputs=outputs,
        reading=reading,
        caveats=caveats,
        reference=TESTS + reference,
        seeded=seeded,
        time_safety="hindsight",
        poison_test=TESTS + "test_future_input_rejected",
        compute=compute,
    )
