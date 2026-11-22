"""Shared helpers for the regime checks: dated returns, a market pair, and one-line results."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    from datetime import datetime

    from numpy.random import Generator

    from alpha_cli.toolbox.contract import InputKind
    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

TESTS = "tests/unit/test_toolbox_regimes.py::"
BASIS = (
    "After-cost bar returns from the stored walk-forward equity curve; each return is dated at the"
    " open that starts its interval."
)
MARKET_BASIS = (
    "After-cost bar returns of the stored walk-forward equity and of the stored open-to-open"
    " buy-and-hold line over the same dates; each return is dated at the open that starts it."
)
# Below this many bars a split of the history says nothing worth reading.
MIN_BARS = 30
MIN_GROUP = 10
Compute = Callable[["Inputs", dict[str, Any], "Generator | None"], Result]


def dated_returns(inputs: Inputs) -> tuple[list[datetime], FloatArray]:
    """After-cost return per interval, with the date of the open that starts it."""
    import numpy as np

    from alpha_validation.metrics import to_returns

    run = inputs.stored
    frame = run.table("stored_equity", "ts", "equity")
    if not frame.height:
        return [], np.empty(0, dtype=np.float64)
    dates = run.dates(frame, "stored_equity")
    equity = frame["equity"].to_numpy()
    if equity.size < 2:
        return [], np.empty(0, dtype=np.float64)
    return dates[:-1], to_returns(equity)


def market_pair(inputs: Inputs) -> tuple[list[datetime], FloatArray, FloatArray, FloatArray]:
    """Dates, strategy returns, market returns and market levels from the stored comparison."""
    from alpha_cli.toolbox.inputs import HOLD_KINDS
    from alpha_validation.metrics import to_returns

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
    if not all(frame["available"]) or any(k not in HOLD_KINDS for k in frame["benchmark_kind"]):
        raise ValueError(
            "benchmark_comparison.parquet requires a stored buy-and-hold value at every date"
        )
    levels = frame["benchmark_equity"].to_numpy()
    return (
        dates[:-1],
        to_returns(frame["strategy_equity"].to_numpy()),
        to_returns(levels),
        levels[:-1],
    )


def unavailable(keys: tuple[str, ...], reason: str, **details: Any) -> Result:
    return Result(dict.fromkeys(keys), dict.fromkeys(keys, reason), details=details, basis=BASIS)


def welch(first: FloatArray, second: FloatArray) -> tuple[float, float] | None:
    """Welch (1947) two-sample t statistic and two-sided p-value; None when undefined."""
    import numpy as np
    from scipy import stats

    if first.size < 2 or second.size < 2 or (np.ptp(first) == 0 and np.ptp(second) == 0):
        return None
    result = stats.ttest_ind(first, second, equal_var=False)
    if not (np.isfinite(result.statistic) and np.isfinite(result.pvalue)):
        return None
    return float(result.statistic), float(result.pvalue)


def two_group_result(
    first: FloatArray,
    second: FloatArray,
    names: tuple[str, str],
    *,
    basis: str = BASIS,
    extra: dict[str, Any] | None = None,
) -> Result:
    """Mean bar return of two groups, their gap and the Welch p-value of the gap."""
    counts = {f"{names[0]}_bars": int(first.size), f"{names[1]}_bars": int(second.size)}
    test = welch(first, second)
    values: dict[str, Any] = {
        f"{names[0]}_mean": float(first.mean()),
        f"{names[1]}_mean": float(second.mean()),
        "gap": float(first.mean() - second.mean()),
        "p_value": None if test is None else test[1],
        **counts,
    }
    reasons = (
        {} if test else {"p_value": "Returns do not vary in either group, so no test applies."}
    )
    return Result(values, reasons, details=dict(extra or {}), basis=basis)


def two_group_outputs(
    names: tuple[str, str], labels: tuple[str, str], what: str
) -> tuple[Output, ...]:
    first, second = names
    return (
        Output(
            f"{first}_mean",
            f"Mean bar return, {labels[0]}",
            f"Average return per bar {what}.",
            "fraction",
        ),
        Output(
            f"{second}_mean",
            f"Mean bar return, {labels[1]}",
            f"Average return per bar {what}.",
            "fraction",
        ),
        Output("gap", "Gap", "First group's mean bar return minus the second group's.", "fraction"),
        Output(
            "p_value",
            "Two-sided p-value",
            "Chance of a gap this large if both groups had the same mean (Welch t-test).",
            "p_value",
        ),
        Output(f"{first}_bars", f"Bars, {labels[0]}", "Number of bars in the group.", "count"),
        Output(f"{second}_bars", f"Bars, {labels[1]}", "Number of bars in the group.", "count"),
    )


def spec(
    tool_id: str,
    question: str,
    needs: tuple[InputKind, ...],
    outputs: tuple[Output, ...],
    reading: str,
    caveat: str,
    reference_test: str,
    compute: Compute,
    *,
    params: tuple[Param, ...] = (),
    kind: Literal["diagnostic", "test"] = "diagnostic",
    seeded: bool = False,
) -> ToolSpec:
    return ToolSpec(
        id=tool_id,
        answers=(question,),
        family="regimes",
        kind=kind,
        look="test" if kind == "test" else "describe",
        question=question,
        needs=needs,
        params=params,
        outputs=outputs,
        reading=reading,
        caveats=(caveat,),
        reference=TESTS + reference_test,
        compute=compute,
        seeded=seeded,
        time_safety="hindsight",
        poison_test=TESTS + "test_future_input_rejected",
    )
