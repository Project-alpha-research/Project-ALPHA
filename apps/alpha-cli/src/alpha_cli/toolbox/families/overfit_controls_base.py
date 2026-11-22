"""Shared helpers of the overfitting-control checks: the scored sample, try counts, spec shape."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    from collections.abc import Callable

    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_cli.toolbox.situations import Situation
    from alpha_validation import FloatArray

TESTS = "tests/unit/test_toolbox_overfit_controls.py::"
BASIS = "After-cost scored bar returns from the stored walk-forward equity curve."
TRADE_BASIS = "After-cost closed trades of the stored run."
MIN_BARS = 30
TRIES = Param(
    "n_trials",
    int,
    0,
    range(0, 1_000_001),
    "Number of ideas and settings tried. 0 uses the count recorded with the run.",
)
FLAT = "A reading needs varying scored returns."
NO_TRIES = "No try count was recorded with this run; set n_trials."
POOR = "A haircut needs a positive Sharpe ratio; this run's is zero or below."


@dataclass(frozen=True)
class Sample:
    """The scored returns of a run, or the reason they cannot be read."""

    returns: FloatArray
    ppy: int
    reason: str | None
    sr: float | None

    @property
    def sharpe_bar(self) -> float:
        """Per-bar Sharpe ratio; only valid when ``reason`` is None."""
        if self.sr is None:
            raise ValueError("The Sharpe ratio of an unreadable sample is not defined")
        return self.sr

    @property
    def bars(self) -> int:
        return len(self.returns)

    @property
    def years(self) -> float:
        return self.bars / self.ppy

    @property
    def sharpe(self) -> float:
        """Annual Sharpe ratio; only valid when ``reason`` is None."""
        return self.sharpe_bar * math.sqrt(self.ppy)


def sample(inputs: Inputs, minimum: int = MIN_BARS) -> Sample:
    returns = inputs.stored.scored_returns()
    ppy = inputs.stored.ppy
    if len(returns) < minimum:
        reason = (
            f"The reading needs at least {minimum} scored bar returns; this run has {len(returns)}."
        )
        return Sample(returns, ppy, reason, None)
    spread = float(returns.std(ddof=1))
    if spread <= 0.0:
        return Sample(returns, ppy, FLAT, None)
    return Sample(returns, ppy, None, float(returns.mean()) / spread)


def blank(keys: tuple[str, ...], reason: str, basis: str = BASIS, **known: float | str) -> Result:
    """A result with every key unavailable except the ``known`` ones."""
    values: dict[str, Any] = {key: known.get(key) for key in keys}
    return Result(values, {k: reason for k, v in values.items() if v is None}, basis=basis)


def tries(inputs: Inputs, params: dict[str, Any]) -> int | None:
    """The stated try count, else the one recorded with the run; None when neither exists."""
    stated = params["n_trials"]
    if stated:
        return int(stated)
    recorded = (inputs.stored.manifest.get("dsr") or {}).get("n_trials")
    if recorded is None:
        return None
    if type(recorded) is not int or recorded < 1:
        raise ValueError("The recorded n_trials must be a positive integer")
    return recorded


def closed_trades(inputs: Inputs) -> FloatArray:
    """Realised profits in entry order, after checking every date sits inside the run period."""
    run = inputs.stored
    frame = run.table("run_trades", "entry_ts", "exit_ts", "realized_pnl")
    for entry, exit_ts in frame.select("entry_ts", "exit_ts").iter_rows():
        if any(not isinstance(ts, datetime) or ts.utcoffset() is None for ts in (entry, exit_ts)):
            raise ValueError("Closed trades require timezone-aware entry and exit dates")
        if entry >= exit_ts or exit_ts > run.last_ts:
            raise ValueError(
                "Closed trades require entry before exit within the recorded run period"
            )
    profits = frame.sort("entry_ts", maintain_order=True)["realized_pnl"].to_numpy()
    if not np.isfinite(profits).all():
        raise ValueError("Closed trades require finite realized profits")
    return profits


def check(
    name: str,
    question: str,
    *,
    answers: tuple[str, ...],
    situations: tuple[Situation, ...],
    outputs: tuple[Output, ...],
    reading: str,
    caveat: str,
    compute: Callable[[Inputs, dict[str, Any], Generator | None], Result],
    params: tuple[Param, ...] = (),
    kind: Literal["diagnostic", "test", "control"] = "test",
    needs: Literal["stored_equity", "run_trades"] = "stored_equity",
) -> ToolSpec:
    return ToolSpec(
        id=f"overfit_controls.{name}",
        answers=answers,
        situations=situations,
        family="overfit_controls",
        kind=kind,
        look="describe" if kind != "test" else "test",
        cost="instant",
        question=question,
        needs=(needs,),
        params=params,
        outputs=outputs,
        reading=reading,
        caveats=(
            caveat,
            "A reading describes this one history; it does not show that an edge exists.",
        ),
        time_safety="hindsight",
        poison_test=TESTS + "test_future_input_rejected",
        reference=TESTS + "test_public_function_parity",
        compute=compute,
    )
