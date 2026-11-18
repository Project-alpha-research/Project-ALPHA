"""Downside risk and closed-trade descriptions of stored walk-forward results."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

REFERENCE = "tests/unit/test_toolbox_run_level_checks.py::"
BASIS = "Stored walk-forward equity, one return per bar, and the manifest's out-of-sample Sharpe."
TRADE_BASIS = "After-cost realized profit on closed walk-forward trades, in account currency."


def downside_ratios(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np
    import pandas as pd
    from quantstats_lumi import stats

    from alpha_validation.metrics import cagr, max_drawdown, profit_factor, to_returns

    run = inputs.stored
    frame = run.table("stored_equity", "ts", "equity")
    dates = run.dates(frame, "stored_equity")
    equity = frame["equity"].to_numpy()
    returns = to_returns(equity)
    if "sharpe" not in run.manifest.get("oos_metrics", {}):
        raise ValueError("manifest.json is missing oos_metrics.sharpe")
    sharpe = run.manifest["oos_metrics"]["sharpe"]
    reasons = {"sharpe": "Stored out-of-sample Sharpe is undefined."} if sharpe is None else {}
    values: dict[str, Value] = {"sharpe": sharpe}
    ratios = ("sortino", "calmar", "omega", "tail_ratio")
    if len(returns) < 2:
        values.update(dict.fromkeys(ratios))
        reasons.update(dict.fromkeys(ratios, "Fewer than two stored returns."))
        return Result(values, reasons, basis=BASIS)
    if np.any(returns < 0):
        sample = pd.Series(returns, index=pd.DatetimeIndex(dates[1:]))
        values["sortino"] = float(stats.sortino(sample, periods=run.ppy))
        values["calmar"] = cagr(equity, periods_per_year=run.ppy) / abs(max_drawdown(equity))
        values["omega"] = profit_factor(returns)
    else:
        values.update(dict.fromkeys(ratios[:3]))
        reasons.update(dict.fromkeys(ratios[:3], "No losing periods in the stored equity curve."))
    low, high = np.percentile(returns, [5, 95])
    values["tail_ratio"] = float(high / abs(low)) if low < 0 < high else None
    if low >= 0:
        reasons["tail_ratio"] = "The fifth percentile of returns is not a loss."
    elif high <= 0:
        reasons["tail_ratio"] = "The 95th percentile of returns is not a gain."
    return Result(values, reasons, basis=BASIS)


DOWNSIDE_RATIOS = ToolSpec(
    id="performance.downside_ratios",
    family="performance",
    question="How large was the return relative to downside risk?",
    needs=("stored_equity",),
    params=(),
    outputs=(
        Output(
            "sortino",
            "Sortino ratio",
            "Mean bar return over downside deviation (root mean square of losses below zero,"
            " averaged over all bars), times the square root of bars per year.",
            "ratio",
        ),
        Output(
            "calmar",
            "Calmar ratio",
            "Compound yearly return over the whole run divided by its deepest peak-to-trough drop.",
            "ratio",
        ),
        Output(
            "omega",
            "Omega at zero",
            "Sum of bar gains divided by the sum of bar losses (threshold zero).",
            "ratio",
        ),
        Output(
            "tail_ratio",
            "Tail ratio",
            "95th percentile of bar returns divided by the size of the fifth percentile loss.",
            "ratio",
        ),
        Output(
            "sharpe", "Stored Sharpe", "Annualized Sharpe recorded in the run manifest.", "ratio"
        ),
    ),
    reading=(
        "Sortino {sortino:.2f}, Calmar {calmar:.2f}, Omega {omega:.2f} and tail ratio"
        " {tail_ratio:.2f}, beside the stored Sharpe of {sharpe:.2f}."
    ),
    caveats=("These ratios cannot tell you how large the next loss will be.",),
    reference=REFERENCE + "test_downside_ratios",
    time_safety="hindsight",
    poison_test=REFERENCE + "test_future_observation_is_rejected",
    compute=downside_ratios,
)


def side_contribution(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation.native_tearsheet import TradeObservation, _trade_statistics

    fields = ("side", "realized_pnl", "realized_return", "entry_ts", "exit_ts")
    frame = inputs.stored.table("run_trades", *fields)
    trades = [TradeObservation(*row) for row in frame.iter_rows()]
    if any(t.side not in {"BUY", "SELL"} for t in trades):
        raise ValueError("trades.parquet requires BUY or SELL for each trade side")
    total = math.fsum(t.realized_pnl for t in trades)
    values: dict[str, Value] = {}
    reasons = {}
    present = []
    for direction, side in (("long", "BUY"), ("short", "SELL")):
        group = [t for t in trades if t.side == side]
        if group:
            present.append(direction)
        stats = {s.metric: s.value for s in _trade_statistics(group)}
        values[f"{direction}_count"] = len(group) if group else None
        for key, metric in (("win_rate", "win_rate"), ("average_pnl", "average_realized_pnl")):
            values[f"{direction}_{key}"] = stats[metric] if group else None
        share = f"{direction}_profit_share"
        values[share] = (
            math.fsum(t.realized_pnl for t in group) / total if group and total > 0 else None
        )
        if group and total <= 0:
            reasons[share] = "Total closed-trade profit is not positive."
        if not group:
            reasons.update(
                {k: f"No closed {direction} trades." for k in values if k.startswith(direction)}
            )
    if len(present) == 1:
        values["sides"] = f"{present[0]}-only"
    else:
        values["sides"] = "long and short" if present else "none"
    return Result(values, reasons, basis=TRADE_BASIS)


SIDE_CONTRIBUTION = ToolSpec(
    id="trades.side_contribution",
    family="trades",
    question="How much did long and short trades each contribute?",
    needs=("run_trades",),
    params=(),
    outputs=(
        Output("sides", "Sides traded", "Directions represented among closed trades.", "text"),
        *(
            output
            for side in ("long", "short")
            for output in (
                Output(
                    f"{side}_count",
                    f"Closed {side} trades",
                    f"Count of closed {side} trades.",
                    "count",
                ),
                Output(
                    f"{side}_profit_share",
                    f"{side.title()} profit share",
                    f"{side.title()} trades' after-cost profit divided by the total; above 100%"
                    " or below zero when the other side lost money.",
                    "fraction",
                ),
                Output(
                    f"{side}_win_rate",
                    f"{side.title()} win rate",
                    f"Fraction of closed {side} trades with after-cost profit above zero.",
                    "fraction",
                ),
                Output(
                    f"{side}_average_pnl",
                    f"Average {side} profit",
                    f"Average after-cost profit per closed {side} trade.",
                    "currency",
                ),
            )
        ),
    ),
    reading=(
        "Sides traded: {sides}. Long trades supplied {long_profit_share:.0%} of after-cost profit"
        " and short trades {short_profit_share:.0%}."
    ),
    caveats=("Closed trades cannot tell you the profit still open at the end.",),
    reference=REFERENCE + "test_side_contribution",
    compute=side_contribution,
)


def concentration(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    pnls = inputs.stored.table("run_trades", "realized_pnl")["realized_pnl"].to_numpy()
    if not np.isfinite(pnls).all():
        raise ValueError("trades.parquet requires finite realized_pnl")
    ordered = np.sort(pnls)[::-1]
    values: dict[str, Value] = {}
    reasons = {}
    for n in (1, 3, 5):
        key = f"without_best_{n}"
        values[key] = math.fsum(ordered[n:]) if len(ordered) > n else None
        if values[key] is None:
            reasons[key] = f"Removing the best {n} leaves no closed trades."
    total = math.fsum(ordered)
    best = math.ceil(len(ordered) / 10)
    share = len(ordered) >= 10 and total > 0
    values["top_decile_share"] = math.fsum(ordered[:best]) / total if share else None
    if len(ordered) < 10:
        reasons["top_decile_share"] = "Fewer than ten closed trades."
    elif total <= 0:
        reasons["top_decile_share"] = "Total closed-trade profit is not positive."
    return Result(values, reasons, basis=TRADE_BASIS)


CONCENTRATION = ToolSpec(
    id="trades.concentration",
    family="trades",
    question="How much after-cost profit remains without the best trades?",
    needs=("run_trades",),
    params=(),
    outputs=(
        *(
            Output(
                f"without_best_{n}",
                f"Profit without best {n}",
                f"After-cost realized profit left after removing the {n} most profitable"
                f" closed trade{'s' if n > 1 else ''}.",
                "currency",
            )
            for n in (1, 3, 5)
        ),
        Output(
            "top_decile_share",
            "Top tenth's profit share",
            "Fraction of after-cost profit from the best tenth of trades (rounded up to whole"
            " trades; needs ten or more); above 100% when the other trades lost money.",
            "fraction",
        ),
    ),
    reading=(
        "The best tenth of closed trades supplied {top_decile_share:.1%} of after-cost profit;"
        " without the single best trade the total was {without_best_1:.2f}."
    ),
    caveats=("This sum cannot tell you how removing trades would affect later position sizes.",),
    reference=REFERENCE + "test_concentration",
    compute=concentration,
)
