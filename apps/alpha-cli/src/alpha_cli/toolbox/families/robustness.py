"""Date sensitivity of the stored walk-forward strategy and its aligned passive benchmark."""

from __future__ import annotations

import calendar
from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec, Value

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

METRICS = (
    ("total_return", "total return"),
    ("cagr", "compound yearly return"),
    ("sharpe", "annualized Sharpe"),
    ("max_drawdown", "worst peak-to-trough drop"),
)
BASIS = (
    "Walk-forward equity and its stored open-to-open buy-and-hold comparison over the same dates."
)


def shift_months(ts: datetime, months: int) -> datetime:
    """Move by calendar months, keeping the day or clipping it to the month's last day."""
    index = ts.month - 1 + months
    year, month = ts.year + index // 12, index % 12 + 1
    return ts.replace(year=year, month=month, day=min(ts.day, calendar.monthrange(year, month)[1]))


def start_end_dates(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_cli.spine.diagnostics import performance
    from alpha_validation.metrics import to_returns

    step = params["step_months"]
    if step < 1:
        raise ValueError("step_months must be positive")
    run = inputs.stored
    frame = run.table(
        "stored_benchmark",
        "ts",
        "strategy_equity",
        "benchmark_equity",
        "available",
        "benchmark_kind",
    )
    dates = run.dates(frame, "stored_benchmark")
    if not all(frame["available"]) or any(
        k not in {"passive_open_to_open_price_only", "passive_open_to_open_with_dividends"}
        for k in frame["benchmark_kind"]
    ):
        raise ValueError(
            "benchmark_comparison.parquet requires a stored buy-and-hold value at every date"
        )
    equity = frame["strategy_equity"].to_numpy()
    market = frame["benchmark_equity"].to_numpy()
    to_returns(equity)
    to_returns(market)
    rows = []
    shifts = range(0, 5 * step, step)
    for start in shifts:
        left = bisect_left(dates, shift_months(dates[0], start))
        for end in shifts:
            right = bisect_right(dates, shift_months(dates[-1], -end))
            if right - left < 2:
                raise ValueError(
                    f"Too little stored history for all 25 windows at step_months={step}"
                )
            metrics = performance(equity[left:right], run.ppy, BASIS)
            metrics.pop("basis")
            rows.append(
                {
                    "start_months": start,
                    "end_months": end,
                    "first_date": dates[left].date().isoformat(),
                    "last_date": dates[right - 1].date().isoformat(),
                    "benchmark_return": float(market[right - 1] / market[left] - 1),
                    **metrics,
                }
            )
    values: dict[str, Value] = {
        "positive_share": sum(row["total_return"] > 0 for row in rows) / len(rows),
        "beat_hold_share": sum(row["total_return"] > row["benchmark_return"] for row in rows)
        / len(rows),
    }
    reasons = {}
    for key, _ in METRICS:
        defined = [row[key] for row in rows if row[key] is not None]
        for suffix, bound in (("min", min), ("max", max)):
            name = f"{key}_{suffix}"
            values[name] = bound(defined) if defined else None
            if not defined:
                reasons[name] = f"No window had a defined {key}."
    return Result(values, reasons, details={"windows": rows}, basis=BASIS)


START_END_DATES = ToolSpec(
    id="robustness.start_end_dates",
    family="robustness",
    question="How sensitive were returns to moving the first and last dates?",
    needs=("stored_benchmark",),
    params=(
        Param(
            "step_months",
            int,
            3,
            None,
            "Positive calendar months between successive cuts at either end.",
        ),
    ),
    outputs=(
        *(
            Output(
                f"{key}_{suffix}",
                f"{word} {label}",
                f"{word} {label} among windows with a defined value.",
                "ratio" if key == "sharpe" else "fraction",
            )
            for key, label in METRICS
            for suffix, word in (("min", "Lowest"), ("max", "Highest"))
        ),
        Output(
            "positive_share",
            "Profitable windows",
            "Fraction of windows with a positive total return.",
            "fraction",
        ),
        Output(
            "beat_hold_share",
            "Windows beating buy and hold",
            "Fraction of windows beating the matching buy-and-hold return.",
            "fraction",
        ),
    ),
    reading=(
        "Across the shifted date windows total return ranged from {total_return_min:.1%} to"
        " {total_return_max:.1%}; {positive_share:.0%} of windows gained and {beat_hold_share:.0%}"
        " beat buy and hold over the same dates."
    ),
    caveats=("Overlapping windows cannot tell you how the rule will perform on fresh data.",),
    time_safety="hindsight",
    poison_test="tests/unit/test_toolbox_run_level_checks.py::test_future_observation_is_rejected",
    reference="tests/unit/test_toolbox_run_level_checks.py::test_date_windows",
    compute=start_end_dates,
)
