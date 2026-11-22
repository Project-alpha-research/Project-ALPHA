"""Shared reads and "too little to read" results for the performance-statistics checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alpha_cli.toolbox.contract import Result, Value

if TYPE_CHECKING:
    from alpha_cli.toolbox.inputs import Target
    from alpha_validation.metrics import FloatArray

MIN_RETURNS = 20
MIN_TRADES = 10
TESTS = "tests/unit/test_toolbox_performance_stats.py::"
POISON = TESTS + "test_future_observation_is_rejected"
EQUITY_BASIS = "Stored walk-forward equity after costs, one return per bar."


def stored_equity(run: Target) -> FloatArray:
    """The stored equity levels, dated, ordered, finite and positive, or a loud error."""
    import numpy as np

    frame = run.table("stored_equity", "ts", "equity")
    run.dates(frame, "stored_equity")
    equity = frame["equity"].to_numpy().astype(np.float64)
    if not np.isfinite(equity).all() or np.any(equity <= 0):
        raise ValueError("Stored equity must be finite and positive")
    return equity


def stored_returns(run: Target) -> tuple[FloatArray | None, str]:
    """Bar returns of the stored equity, or None with the reason there are too few."""
    from alpha_validation.metrics import to_returns

    equity = stored_equity(run)
    if equity.size - 1 < MIN_RETURNS:
        return None, too_few_returns(equity.size - 1)
    return to_returns(equity), ""


def too_few_returns(count: int) -> str:
    return f"Too little to read: {count} stored returns; at least {MIN_RETURNS} are needed."


def too_few_trades(count: int) -> str:
    return f"Too little to read: {count} closed trades; at least {MIN_TRADES} are needed."


def unavailable(
    keys: tuple[str, ...], reason: str, known: dict[str, Value] | None = None
) -> Result:
    """Every output in `keys` is missing for one reason; `known` holds the real counts."""
    values: dict[str, Value] = {**dict.fromkeys(keys), **(known or {})}
    reasons = {key: reason for key, value in values.items() if value is None}
    return Result(values, reasons, basis=EQUITY_BASIS)
