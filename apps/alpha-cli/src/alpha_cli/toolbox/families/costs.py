"""Break-even multiples of the fill costs on the scored walk-forward bars."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

BASIS = "Scored walk-forward returns, with the stored fill costs scaled on each bar."
OLD_RUN = "This run was made before costs were stored per bar. Run the rule test again."
NO_COST = "This run charged no costs. There is nothing to scale."


def _threshold(
    gross: FloatArray, costs: FloatArray, target_wealth: float, *, zero: bool
) -> tuple[float | None, str]:
    import numpy as np
    from scipy.optimize import bisect

    # Costs are non-negative on every bar (checked by the caller), so compounded after-cost wealth
    # never rises as k grows: one sign change at most, which bisection finds.
    def difference(k: float) -> float:
        after = gross - k * costs
        # Once a bar exhausts the portfolio, later negative factors cannot restore capital.
        if np.any(after <= -1):
            return -math.inf
        # Compare compounded wealth in log space, including the benchmark in the same units.
        return math.fsum(np.log(1.0 + after)) - math.log(target_wealth)

    if difference(0) < 0:
        return None, (
            "The result is not positive even with no costs."
            if zero
            else "The result falls short of buy and hold even with no costs."
        )
    if difference(100) > 0:
        return None, (
            "The result is still positive at 100 times today's costs."
            if zero
            else "The result still beats buy and hold at 100 times today's costs."
        )
    # Bisect in multiples of today's costs. Keep the endpoint cases exact.
    multiple = 1.0 if difference(1) == 0 else float(bisect(difference, 0.0, 100.0, xtol=1e-13))

    if zero:
        if multiple == 0:
            return multiple, "The result is not positive even with no costs."
        prefix = "The result is not positive at today's costs. " if multiple <= 1 else ""
        return multiple, f"{prefix}The result breaks even at {_times(multiple)} today's costs."
    prefix = "The result does not beat buy and hold at today's costs. " if multiple <= 1 else ""
    return multiple, f"{prefix}It matches buy and hold at {_times(multiple)} today's costs."


def _times(multiple: float) -> str:
    """A multiple with sensible digits: 3.2 times, 0.45 times, 11.6 times, 100 times."""
    if multiple < 0.01:
        return "under 0.01 times"
    return f"{multiple:.3g} times" if multiple >= 10 else f"{multiple:.2g} times"


def break_even(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_cli.toolbox.inputs import HOLD_KINDS
    from alpha_validation.metrics import to_returns

    run = inputs.stored
    frame = run.table("stored_equity")
    dates = run.dates(frame, "stored_equity")
    if not {"gross_return", "cost_return"} <= set(frame.columns):
        keys = ("zero_multiple", "hold_multiple", "cost_share")
        return Result(
            {**dict.fromkeys(keys), "sentence": OLD_RUN}, dict.fromkeys(keys, OLD_RUN), basis=BASIS
        )

    equity = frame["equity"].to_numpy()
    net = to_returns(equity)
    gross = frame["gross_return"].to_numpy()
    costs = frame["cost_return"].to_numpy()
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
    gross, costs = gross[1:], costs[1:]
    comparison = run.table(
        "stored_benchmark", "ts", "benchmark_equity", "available", "benchmark_kind"
    )
    if run.dates(comparison, "stored_benchmark") != dates:
        raise ValueError("Buy-and-hold dates must match the scored equity dates")
    if not all(comparison["available"]) or any(
        kind not in HOLD_KINDS for kind in comparison["benchmark_kind"]
    ):
        raise ValueError("A stored buy-and-hold comparison is required over the scored period")
    market = comparison["benchmark_equity"].to_numpy()
    to_returns(market)
    hold = float(market[-1] / market[0])

    # Use the actual prior equity to express every bar's cost and profit in the same currency.
    profit = math.fsum(equity[:-1] * gross)
    values: dict[str, Value] = {
        "cost_share": math.fsum(equity[:-1] * costs) / profit if profit > 0 else None,
    }
    reasons = {} if profit > 0 else {"cost_share": "Gross profit is not positive."}
    if np.any(costs):
        sentences = []
        for key, target in (("zero_multiple", 1.0), ("hold_multiple", hold)):
            value, sentence = _threshold(gross, costs, target, zero=key == "zero_multiple")
            values[key] = value
            if value is None:
                reasons[key] = sentence
            sentences.append(sentence)
        values["sentence"] = " ".join(sentences)
    else:
        values.update(zero_multiple=None, hold_multiple=None, sentence=NO_COST)
        reasons.update(zero_multiple=NO_COST, hold_multiple=NO_COST)
    return Result(values, reasons, basis=BASIS)


BREAK_EVEN = ToolSpec(
    id="costs.break_even",
    family="costs",
    question="How much could costs rise before the result reached zero or matched buy and hold?",
    needs=("stored_equity", "stored_benchmark"),
    params=(),
    outputs=(
        Output(
            "zero_multiple",
            "Break-even costs",
            "Multiple of fill costs at zero total return.",
            "ratio",
        ),
        Output(
            "hold_multiple",
            "Buy-and-hold threshold",
            "Multiple of fill costs at the buy-and-hold total return.",
            "ratio",
        ),
        Output(
            "cost_share",
            "Share spent on costs",
            "Total fill costs divided by positive before-cost profit, both in account currency.",
            "fraction",
        ),
        Output(
            "sentence", "Cost thresholds", "Plain reading of the two break-even thresholds.", "text"
        ),
    ),
    reading="{sentence}",
    caveats=(
        "Scaling costs cannot tell you how wider spreads in stressed markets, partial fills or"
        " whole-share rounding would affect the result.",
    ),
    time_safety="hindsight",
    poison_test="tests/unit/test_toolbox_run_level_checks.py::test_future_observation_is_rejected",
    reference="tests/unit/test_toolbox_run_level_checks.py::test_break_even",
    compute=break_even,
)
