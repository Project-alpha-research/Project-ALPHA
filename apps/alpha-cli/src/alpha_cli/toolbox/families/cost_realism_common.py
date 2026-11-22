"""Shared readers and the spec factory for the cost and execution realism checks."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import InputKind, Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    import polars as pl
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_core import Bar
    from alpha_validation import FloatArray

TESTS = "tests/unit/test_toolbox_cost_realism.py::"
OLD_RUN = "This run was made before costs were stored per bar. Run the rule test again."
OLD_TRADES = "This run's trades do not store quantity and price. Run the rule test again."
NO_TRADES = "Too little to read: the run has no closed trades."
NO_BARS = "The run carries no price bars, so this check cannot read it."
Compute = Callable[["Inputs", dict[str, Any], "Generator | None"], Result]


def make(
    name: str,
    question: str,
    needs: tuple[InputKind, ...],
    params: tuple[Param, ...],
    outputs: tuple[Output, ...],
    reading: str,
    caveat: str,
    compute: Compute,
) -> ToolSpec:
    """One cost-realism entry: a descriptive reading on the stored run, never a verdict."""
    return ToolSpec(
        id=f"cost_realism.{name}",
        answers=(question,),
        situations=("cost-fragile",),
        family="cost_realism",
        question=question,
        needs=needs,
        params=params,
        outputs=outputs,
        reading=reading,
        caveats=(caveat,),
        time_safety="hindsight",
        poison_test=TESTS + "test_future_observation_is_rejected",
        reference=TESTS + f"test_{name}",
        compute=compute,
    )


def unavailable(outputs: tuple[Output, ...], reason: str, basis: str) -> Result:
    keys = [o.key for o in outputs]
    return Result(dict.fromkeys(keys), dict.fromkeys(keys, reason), basis=basis)


def cost_curve(inputs: Inputs) -> tuple[list[datetime], FloatArray, FloatArray, FloatArray] | None:
    """Dates, equity, gross and cost returns per interval; None for a run without stored costs."""
    import numpy as np

    from alpha_validation.metrics import to_returns

    run = inputs.stored
    frame = run.table("stored_equity")
    dates = run.dates(frame, "stored_equity")
    if not {"gross_return", "cost_return"} <= set(frame.columns):
        return None
    equity = frame["equity"].to_numpy()
    net = to_returns(equity)
    gross, costs = frame["gross_return"].to_numpy(), frame["cost_return"].to_numpy()
    if (
        gross[0] != 0
        or costs[0] != 0
        or not np.isfinite(gross).all()
        or not np.isfinite(costs).all()
        or np.any(costs < 0)
        or not np.allclose(gross[1:] - costs[1:], net, rtol=0, atol=1e-12)
    ):
        raise ValueError(
            "Stored gross_return and cost_return must reconcile to equity on every bar"
        )
    return dates, equity, gross[1:], costs[1:]


def closed_trades(inputs: Inputs, *columns: str) -> pl.DataFrame | None:
    """The stored trades in entry order; None when a needed column was never stored."""
    import numpy as np

    run = inputs.stored
    frame = run.table("run_trades")
    if not set(columns) <= set(frame.columns):
        return None
    for entry, exit_ts in frame.select("entry_ts", "exit_ts").iter_rows():
        if any(not isinstance(ts, datetime) or ts.utcoffset() is None for ts in (entry, exit_ts)):
            raise ValueError("Closed trades require timezone-aware entry and exit dates")
        if entry >= exit_ts or exit_ts > run.last_ts:
            raise ValueError(
                "Closed trades require entry before exit within the recorded run period"
            )
    for column in set(columns) & {"quantity", "entry_price"}:
        values = frame[column].to_numpy()
        if values.size and not (np.isfinite(values).all() and (values > 0).all()):
            raise ValueError(f"Trade {column} must be finite and positive")
    return frame.sort("entry_ts", maintain_order=True)


def equity_at(inputs: Inputs, when: list[datetime]) -> FloatArray:
    """Account value in currency at or before each instant; a trade before the curve is an error.

    The stored curve starts at 1.0, in units of the starting cash, so it is scaled by that cash.
    """
    import numpy as np

    cash = inputs.stored.require_cash()
    frame = inputs.stored.table("stored_equity", "ts", "equity")
    dates = inputs.stored.dates(frame, "stored_equity")
    position = [bisect_right(dates, ts) - 1 for ts in when]
    if min(position) < 0:
        raise ValueError("A trade starts before the stored equity curve")
    return np.asarray(frame["equity"].to_numpy()[position]) * float(cash)


def run_bars(inputs: Inputs) -> tuple[Bar, ...]:
    """The run's own bars from the shared loader (cut at the held-back boundary)."""
    from alpha_cli.toolbox import inputs as loader

    source = inputs.source
    series = (
        source
        if isinstance(source, loader.RunSeries)
        else loader.load_run(inputs.data_home, source)
    )
    return series.bars
