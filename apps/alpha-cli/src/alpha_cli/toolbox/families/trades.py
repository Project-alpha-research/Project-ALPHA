"""Order-dependent tests on after-cost closed trade outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec
from alpha_cli.toolbox.families.performance import TRADE_BASIS

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

TESTS = "tests/unit/test_toolbox_resampling_checks.py::"


def dependence(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation.trade_dependence import trade_runs_test

    run = inputs.stored
    frame = run.table("run_trades", "entry_ts", "exit_ts", "realized_pnl")
    end = run.last_ts
    for entry, exit_ts in frame.select("entry_ts", "exit_ts").iter_rows():
        if any(not isinstance(ts, datetime) or ts.utcoffset() is None for ts in (entry, exit_ts)):
            raise ValueError("Closed trades require timezone-aware entry and exit dates")
        if entry >= exit_ts or exit_ts > end:
            raise ValueError(
                "Closed trades require entry before exit within the recorded run period"
            )

    ordered = frame.sort("entry_ts", maintain_order=True)
    test = trade_runs_test(ordered["realized_pnl"].to_numpy())
    if test is None:
        keys = ("runs", "expected", "z", "p_value")
        reason = "Needs at least 3 closed trades, with at least one win and one loss."
        return Result(dict.fromkeys(keys), dict.fromkeys(keys, reason), basis=TRADE_BASIS)
    return Result(
        {"runs": test.n_runs, "expected": test.expected_runs, "z": test.z, "p_value": test.p_value},
        {},
        basis=TRADE_BASIS,
    )


DEPENDENCE = ToolSpec(
    id="trades.dependence",
    answers=("Did winning and losing trades cluster or alternate?",),
    situations=("trade-streaks", "few-trades"),
    family="trades",
    kind="test",
    look="test",
    question="Did winning and losing trades cluster or alternate?",
    needs=("run_trades",),
    params=(),
    outputs=(
        Output(
            "runs",
            "Observed streaks",
            "Number of unbroken runs of wins or of losses, in entry order.",
            "count",
        ),
        Output(
            "expected",
            "Expected streaks",
            "Number of streaks expected if the same wins and losses came in random order.",
            "count",
        ),
        Output(
            "z", "Runs z-score", "Negative means clustering, positive means alternation.", "ratio"
        ),
        Output(
            "p_value",
            "Two-sided p-value",
            "Chance of a gap this large if the order were random (normal approximation).",
            "p_value",
        ),
    ),
    reading=(
        "Wins and losses formed {runs} streaks; random order would give about {expected:.1f}"
        " (p-value {p_value:.3f}; a small p-value means the order was probably not random)."
    ),
    caveats=(
        "It only looks at whether each trade won or lost, not by how much, and cannot tell you"
        " what caused a streak. Fewer streaks than random means wins and losses bunched.",
    ),
    time_safety="hindsight",
    poison_test=TESTS + "test_future_input_rejected",
    reference=TESTS + "test_public_function_parity",
    compute=dependence,
)
