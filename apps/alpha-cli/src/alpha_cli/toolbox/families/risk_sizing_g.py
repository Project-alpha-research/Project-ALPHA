"""Attribution of the deepest drawdown to the trades that closed inside it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result
from alpha_cli.toolbox.families.risk_common import (
    BASIS,
    check,
    closed_trades,
    equity_and_dates,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

TESTS = "test_toolbox_risk_sizing_d"
MIN_BARS = 20


def drawdown_causes(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = (
        "drawdown",
        "peak_date",
        "trough_date",
        "recovery_date",
        "bars_down",
        "equity_loss",
        "trades_closed",
        "closed_pnl",
        "worst_trade_pnl",
    )
    equity, dates = equity_and_dates(inputs)
    trades = closed_trades(inputs)
    if len(equity) < MIN_BARS:
        return unavailable(keys, f"Needs at least {MIN_BARS} equity points; found {len(equity)}.")
    peak_so_far = np.maximum.accumulate(equity)
    depth = equity / peak_so_far - 1
    trough = int(depth.argmin())
    if depth[trough] >= 0:
        return unavailable(keys, "Equity never fell below an earlier high.")
    high = float(peak_so_far[trough])
    peak = int(np.flatnonzero(equity[: trough + 1] == high)[-1])
    later = np.flatnonzero(equity[trough:] >= high)
    values: dict[str, Any] = {
        "drawdown": float(depth[trough]),
        "peak_date": dates[peak].date().isoformat(),
        "trough_date": dates[trough].date().isoformat(),
        "bars_down": trough - peak,
        "equity_loss": high - float(equity[trough]),
    }
    reasons = {}
    if later.size:
        values["recovery_date"] = dates[trough + int(later[0])].date().isoformat()
    else:
        values["recovery_date"] = None
        reasons["recovery_date"] = "The earlier high was not regained by the end of the run."
    inside = np.array([dates[peak] < ts <= dates[trough] for ts in trades.exit], dtype=bool)
    values["trades_closed"] = int(inside.sum())
    if inside.any():
        values["closed_pnl"] = float(trades.pnl[inside].sum())
        values["worst_trade_pnl"] = float(trades.pnl[inside].min())
    else:
        for key in ("closed_pnl", "worst_trade_pnl"):
            values[key] = None
            reasons[key] = "No trade closed between the peak and the trough."
    return Result(
        values, reasons, basis=BASIS + " Closed trades are after-cost profit in currency."
    )


CHECKS = (
    check(
        "attribution.drawdown_causes",
        TESTS,
        question="What happened during the deepest drawdown?",
        answers=("What caused my worst drawdown?",),
        situations=("drawdown",),
        needs=("stored_equity", "run_trades"),
        outputs=(
            Output(
                "drawdown",
                "Deepest drawdown",
                "Deepest fall from an earlier equity high, as a negative fraction.",
                "fraction",
            ),
            Output("peak_date", "Peak date", "Date of the last high before the fall.", "date"),
            Output("trough_date", "Trough date", "Date of the lowest point.", "date"),
            Output(
                "recovery_date",
                "Recovery date",
                "First date the earlier high was regained.",
                "date",
            ),
            Output("bars_down", "Bars to the low", "Bars from the peak to the trough.", "count"),
            Output(
                "equity_loss",
                "Equity lost",
                "Equity at the peak minus equity at the trough, in account currency.",
                "currency",
            ),
            Output(
                "trades_closed",
                "Trades closed",
                "Closed trades whose exit fell after the peak and by the trough.",
                "count",
            ),
            Output(
                "closed_pnl",
                "Profit of those trades",
                "Sum of after-cost profit of those trades.",
                "currency",
            ),
            Output(
                "worst_trade_pnl",
                "Worst of those trades",
                "Lowest profit among those trades.",
                "currency",
            ),
        ),
        reading=(
            "The deepest drawdown was {drawdown:.1%}, from {peak_date} to {trough_date}"
            " ({bars_down} bars);"
            " {trades_closed} trades closed in that stretch with a profit of {closed_pnl:.2f}."
        ),
        caveats=(
            "Closed trades leave out the loss on a position still open at the trough, so their"
            " profit"
            " need not match the equity lost.",
        ),
        compute=drawdown_causes,
        family="attribution",
    ),
)
