"""Cost realism on closed trades: financing, tax, commission schedule and share rounding."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec
from alpha_cli.toolbox.families.cost_realism_common import (
    NO_TRADES,
    OLD_TRADES,
    closed_trades,
    equity_at,
    make,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

BASIS = "Closed trades of the stored run, in account currency, summed without compounding."
SIZED = ("quantity", "entry_price", "entry_ts", "exit_ts", "realized_pnl")
DAY = 86400.0

FINANCING_OUTPUTS = (
    Output(
        "leveraged_trades",
        "Trades on borrowed money",
        "Trades whose entry value was above the account equity.",
        "count",
    ),
    Output(
        "interest",
        "Interest",
        "Interest on the borrowed part of each trade for its days held.",
        "currency",
    ),
    Output(
        "profit_after_interest",
        "Profit after interest",
        "Summed trade profit less the interest.",
        "currency",
    ),
)


def financing(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    trades = closed_trades(inputs, *SIZED)
    if trades is None:
        return unavailable(FINANCING_OUTPUTS, OLD_TRADES, BASIS)
    if not trades.height:
        return unavailable(FINANCING_OUTPUTS, NO_TRADES, BASIS)
    value = (trades["quantity"] * trades["entry_price"]).to_numpy()
    equity = equity_at(inputs, trades["entry_ts"].to_list())
    days = [
        (x - e).total_seconds() / DAY
        for e, x in zip(trades["entry_ts"], trades["exit_ts"], strict=True)
    ]
    borrowed = (value - equity).clip(min=0)
    interest = math.fsum(borrowed * params["rate_pct"] / 100 * days / 365)
    return Result(
        {
            "leveraged_trades": int((borrowed > 0).sum()),
            "interest": interest,
            "profit_after_interest": math.fsum(trades["realized_pnl"]) - interest,
        },
        {},
        basis=BASIS,
    )


FINANCING = make(
    "financing_cost",
    "What does the borrowed money in the run's trades cost?",
    ("stored_equity", "run_trades"),
    (Param("rate_pct", float, 6.0, None, "Yearly interest rate on borrowed money, in percent."),),
    FINANCING_OUTPUTS,
    "{leveraged_trades} trades used borrowed money ; "
    "interest comes to {interest:.2f}, leaving {profit_after_interest:.2f} of profit.",
    "The rate is an assumption you set, not a quote from a broker. Interest is simple, on the "
    "borrowed part only, and ignores margin rules. A trade is sized at its peak for its whole "
    "hold, so interest is an upper bound for a position that was scaled in.",
    financing,
)

TAX_OUTPUTS = (
    Output("pre_tax_profit", "Profit before tax", "Summed trade profit.", "currency"),
    Output("tax", "Tax", "Tax on each year's net gains, short-term and long-term.", "currency"),
    Output("after_tax_profit", "Profit after tax", "Profit before tax less the tax.", "currency"),
    Output(
        "wash_losses",
        "Wash-sale losses",
        "Losing trades followed by a new trade within 30 days.",
        "count",
    ),
)


def _year_tax(short: float, long: float, rate_short: float, rate_long: float) -> float:
    if short > 0 and long > 0:
        return short * rate_short + long * rate_long
    net = short + long
    if net <= 0:
        return 0.0
    return net * (rate_short if short > 0 else rate_long)


def after_tax(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    trades = closed_trades(inputs, "entry_ts", "exit_ts", "realized_pnl")
    if trades is None:
        return unavailable(TAX_OUTPUTS, OLD_TRADES, BASIS)
    if not trades.height:
        return unavailable(TAX_OUTPUTS, NO_TRADES, BASIS)
    rows = list(trades.select("entry_ts", "exit_ts", "realized_pnl").iter_rows())
    wash = timedelta(days=30)
    years: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    washed = long_term = 0
    for i, (entry, exit_ts, pnl) in enumerate(rows):
        long_held = exit_ts - entry > timedelta(days=365)
        long_term += long_held
        if pnl < 0 and any(
            j != i and exit_ts - wash <= e <= exit_ts + wash for j, (e, _, _) in enumerate(rows)
        ):
            washed += 1  # the loss is not allowed this year
            continue
        years[exit_ts.year][long_held] += pnl
    tax = math.fsum(
        _year_tax(st, lt, params["short_rate_pct"] / 100, params["long_rate_pct"] / 100)
        for st, lt in years.values()
    )
    profit = math.fsum(pnl for _, _, pnl in rows)
    return Result(
        {
            "pre_tax_profit": profit,
            "tax": tax,
            "after_tax_profit": profit - tax,
            "wash_losses": washed,
        },
        {},
        basis=BASIS,
    )


AFTER_TAX = make(
    "after_tax",
    "What does the owner keep after tax?",
    ("run_trades",),
    (
        Param(
            "short_rate_pct",
            float,
            30.0,
            None,
            "Tax rate on trades held a year or less, in percent.",
        ),
        Param(
            "long_rate_pct", float, 15.0, None, "Tax rate on trades held over a year, in percent."
        ),
    ),
    TAX_OUTPUTS,
    "Profit of {pre_tax_profit:.2f} leaves {after_tax_profit:.2f} after {tax:.2f} of tax "
    "({wash_losses} losses fell under the wash-sale rule).",
    "The rates are assumptions you set, not tax advice. Net losses are not carried to other years, "
    "and a wash-sale loss is dropped, not deferred into the cost of the new trade.",
    after_tax,
)

CHECKS: tuple[ToolSpec, ...] = (FINANCING, AFTER_TAX)
