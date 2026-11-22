"""Closed-trade statistics: payoff and expectancy, win and loss streaks, holding periods."""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value
from alpha_cli.toolbox.families.performance import TRADE_BASIS
from alpha_cli.toolbox.families.performance_stats_common import (
    MIN_TRADES,
    POISON,
    TESTS,
    too_few_trades,
)

if TYPE_CHECKING:
    import polars as pl
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs


def _trades(inputs: Inputs) -> pl.DataFrame:
    """Closed trades in entry order; dated, finite and inside the recorded run period."""
    run = inputs.stored
    frame = run.table("run_trades", "entry_ts", "exit_ts", "realized_pnl")
    for entry, exit_ts in frame.select("entry_ts", "exit_ts").iter_rows():
        if any(not isinstance(ts, datetime) or ts.utcoffset() is None for ts in (entry, exit_ts)):
            raise ValueError("Closed trades require timezone-aware entry and exit dates")
        if entry >= exit_ts or exit_ts > run.last_ts:
            raise ValueError("Closed trades require entry before exit within the run period")
    if not frame["realized_pnl"].is_finite().all():
        raise ValueError("trades.parquet requires finite realized_pnl")
    return frame.sort("entry_ts", maintain_order=True)


def _short(keys: tuple[str, ...], count: int) -> Result:
    reason = too_few_trades(count)
    values: dict[str, Value] = {**dict.fromkeys(keys), "trades": count}
    return Result(values, dict.fromkeys(keys, reason), basis=TRADE_BASIS)


def payoff_expectancy(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("payoff_ratio", "expectancy", "expectancy_in_average_losses")
    frame = _trades(inputs)
    if frame.height < MIN_TRADES:
        return _short(keys, frame.height)
    pnl = frame["realized_pnl"].to_list()
    wins = [p for p in pnl if p > 0]
    losses = [-p for p in pnl if p < 0]
    expectancy = math.fsum(pnl) / len(pnl)
    values: dict[str, Value] = {
        "trades": len(pnl),
        "payoff_ratio": None,
        "expectancy": expectancy,
        "expectancy_in_average_losses": None,
    }
    reasons = {}
    if losses:
        average_loss = math.fsum(losses) / len(losses)
        values["expectancy_in_average_losses"] = expectancy / average_loss
        if wins:
            values["payoff_ratio"] = (math.fsum(wins) / len(wins)) / average_loss
        else:
            reasons["payoff_ratio"] = "No winning trades."
    else:
        reasons["payoff_ratio"] = "No losing trades."
        reasons["expectancy_in_average_losses"] = "No losing trades."
    return Result(values, reasons, basis=TRADE_BASIS)


PAYOFF_EXPECTANCY = ToolSpec(
    id="performance.payoff_expectancy",
    version=2,
    situations=("risk-adjusted",),
    answers=(
        "Do the winning trades outsize the losing ones?",
        "What is the average result per trade?",
    ),
    family="performance",
    question="What is the average winner against the average loser, and the average trade?",
    needs=("run_trades",),
    params=(),
    outputs=(
        Output("trades", "Closed trades", "Number of closed trades read.", "count"),
        Output(
            "payoff_ratio",
            "Payoff ratio",
            "Average winning trade divided by the size of the average losing trade, after costs.",
            "ratio",
        ),
        Output(
            "expectancy",
            "Expectancy per trade",
            "Mean after-cost profit of a closed trade, in account currency.",
            "currency",
        ),
        Output(
            "expectancy_in_average_losses",
            "Expectancy in average losses",
            "Expectancy divided by the size of the average losing trade; one average loss"
            " stands in for Tharp's R, because the stored trades carry no stop distance.",
            "ratio",
        ),
    ),
    reading=(
        "Over {trades} closed trades the average winner was {payoff_ratio:.2f} times the average"
        " loser; the average trade made {expectancy:.2f}, or {expectancy_in_average_losses:.2f}"
        " average losses."
    ),
    caveats=(
        "A trade that broke even is neither a win nor a loss. The reading cannot tell you the"
        " trade-by-trade spread, and its average loss is not a planned risk per trade.",
    ),
    reference=TESTS + "test_payoff_expectancy",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=payoff_expectancy,
)


def _streaks(pnl: list[float]) -> tuple[list[int], list[int]]:
    wins: list[int] = []
    losses: list[int] = []
    run, kind = 0, 0
    for p in [*pnl, 0.0]:
        now = (p > 0) - (p < 0)
        if now == kind:
            run += 1
            continue
        if kind:
            (wins if kind > 0 else losses).append(run)
        run, kind = 1, now
    return wins, losses


def streaks(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("longest_win_streak", "longest_loss_streak", "loss_streaks", "average_loss_streak")
    frame = _trades(inputs)
    if frame.height < MIN_TRADES:
        return _short(keys, frame.height)
    wins, losses = _streaks(frame["realized_pnl"].to_list())
    values: dict[str, Value] = {
        "trades": frame.height,
        "longest_win_streak": max(wins, default=0),
        "longest_loss_streak": max(losses, default=0),
        "loss_streaks": len(losses),
        "average_loss_streak": math.fsum(losses) / len(losses) if losses else None,
    }
    reasons = {} if losses else {"average_loss_streak": "No losing trades."}
    return Result(values, reasons, basis=TRADE_BASIS)


STREAKS = ToolSpec(
    id="performance.streaks",
    situations=("trade-streaks",),
    answers=("How long can winning and losing streaks get?",),
    family="performance",
    question="How long were the longest winning and losing streaks of trades?",
    needs=("run_trades",),
    params=(),
    outputs=(
        Output("trades", "Closed trades", "Number of closed trades read.", "count"),
        Output(
            "longest_win_streak",
            "Longest winning streak",
            "Most consecutive closed trades with after-cost profit above zero, in entry order.",
            "count",
        ),
        Output(
            "longest_loss_streak",
            "Longest losing streak",
            "Most consecutive closed trades with after-cost loss, in entry order.",
            "count",
        ),
        Output("loss_streaks", "Losing streaks", "Number of separate losing streaks.", "count"),
        Output(
            "average_loss_streak",
            "Average losing streak",
            "Mean length of the separate losing streaks.",
            "ratio",
        ),
    ),
    reading=(
        "Over {trades} closed trades the longest winning streak was {longest_win_streak} and"
        " the longest losing streak {longest_loss_streak}; losing streaks averaged"
        " {average_loss_streak:.2f} trades."
    ),
    caveats=(
        "A break-even trade ends both kinds of streak. It lists streaks only and cannot tell you"
        " whether they were more than chance; trades.dependence tests that.",
    ),
    reference=TESTS + "test_streaks",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=streaks,
)


def holding_period(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = (
        "median_days",
        "mean_days",
        "shortest_days",
        "longest_days",
        "winners_mean_days",
        "losers_mean_days",
    )
    frame = _trades(inputs)
    if frame.height < MIN_TRADES:
        return _short(keys, frame.height)
    days = np.array(
        [
            (b - a).total_seconds() / 86400
            for a, b in frame.select("entry_ts", "exit_ts").iter_rows()
        ]
    )
    pnl = frame["realized_pnl"].to_numpy()
    values: dict[str, Value] = {
        "trades": frame.height,
        "median_days": float(np.median(days)),
        "mean_days": float(np.mean(days)),
        "shortest_days": float(np.min(days)),
        "longest_days": float(np.max(days)),
        "winners_mean_days": float(np.mean(days[pnl > 0])) if np.any(pnl > 0) else None,
        "losers_mean_days": float(np.mean(days[pnl < 0])) if np.any(pnl < 0) else None,
    }
    reasons = {
        key: f"No {word} trades."
        for key, word in (("winners_mean_days", "winning"), ("losers_mean_days", "losing"))
        if values[key] is None
    }
    return Result(values, reasons, basis=TRADE_BASIS)


def _day_output(key: str, label: str, gloss: str) -> Output:
    return Output(key, label, gloss + " In calendar days.", "count")


HOLDING_PERIOD = ToolSpec(
    id="performance.holding_period",
    situations=("cost-fragile",),
    answers=("How long were trades held, and were losers held longer than winners?",),
    family="performance",
    question="How long were trades held?",
    needs=("run_trades",),
    params=(),
    outputs=(
        Output("trades", "Closed trades", "Number of closed trades read.", "count"),
        _day_output("median_days", "Median holding time", "Middle holding time of a trade."),
        _day_output("mean_days", "Mean holding time", "Average holding time of a trade."),
        _day_output("shortest_days", "Shortest holding time", "Briefest trade."),
        _day_output("longest_days", "Longest holding time", "Longest trade."),
        _day_output("winners_mean_days", "Winners' mean time", "Average time of winning trades."),
        _day_output("losers_mean_days", "Losers' mean time", "Average time of losing trades."),
    ),
    reading=(
        "Over {trades} closed trades the median holding time was {median_days:.1f} days;"
        " winners were held {winners_mean_days:.1f} days on average and losers"
        " {losers_mean_days:.1f}."
    ),
    caveats=(
        "Times are calendar days from entry to exit. The reading cannot tell you why one group"
        " was held longer.",
    ),
    reference=TESTS + "test_holding_period",
    poison_test=POISON,
    time_safety="hindsight",
    cost="instant",
    compute=holding_period,
)
CHECKS = (PAYOFF_EXPECTANCY, STREAKS, HOLDING_PERIOD)
