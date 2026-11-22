"""Cost realism of closed trades: a commission schedule and whole-share rounding."""

from __future__ import annotations

import math
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

SCHEDULE_OUTPUTS = (
    Output("commission", "Commission", "Total commission under the schedule.", "currency"),
    Output("commission_bps", "Commission rate", "Commission over total traded value.", "bps"),
    Output(
        "min_ticket_share",
        "Tickets at the minimum",
        "Share of tickets charged the minimum fee.",
        "fraction",
    ),
)


def schedule(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    trades = closed_trades(inputs, "quantity", "entry_price", "exit_price")
    if trades is None:
        return unavailable(SCHEDULE_OUTPUTS, OLD_TRADES, BASIS)
    if not trades.height:
        return unavailable(SCHEDULE_OUTPUTS, NO_TRADES, BASIS)
    qty = trades["quantity"].to_numpy()
    fees = (qty * params["per_unit"]).clip(min=params["min_ticket"])
    traded = math.fsum(qty * (trades["entry_price"] + trades["exit_price"]).to_numpy())
    return Result(
        {
            "commission": 2 * math.fsum(fees),
            "commission_bps": 2 * math.fsum(fees) / traded * 1e4,
            "min_ticket_share": float((qty * params["per_unit"] <= params["min_ticket"]).mean()),
        },
        {},
        basis=BASIS,
    )


SCHEDULE = make(
    "commission_schedule",
    "Do small orders pay realistic commission fees?",
    ("run_trades",),
    (
        Param("per_unit", float, 0.005, None, "Commission per share or unit on each order."),
        Param("min_ticket", float, 1.0, None, "Smallest commission charged on one order."),
    ),
    SCHEDULE_OUTPUTS,
    "Commission would be {commission:.2f} {commission_bps:.1f} basis points "
    "of traded value; {min_ticket_share:.0%} of orders pay the minimum.",
    "The schedule is an assumption you set. It replaces, not adds to, the fee in the run, and "
    "leaves out exchange and regulatory fees and slippage. It counts two orders for each closed "
    "trade, so it is a lower bound when a position was scaled in or out.",
    schedule,
)

ROUND_OUTPUTS = (
    Output("trades", "Trades", "Closed trades read.", "count"),
    Output(
        "zero_share_trades",
        "Trades that round to nothing",
        "Trades where the account buys no whole share.",
        "count",
    ),
    Output(
        "ideal_profit",
        "Profit with exact sizes",
        "Profit if each trade kept its share of equity exactly.",
        "currency",
    ),
    Output(
        "rounded_profit",
        "Profit with whole shares",
        "Profit when each position is rounded down to whole shares.",
        "currency",
    ),
)


def rounding(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    trades = closed_trades(inputs, *SIZED)
    if trades is None:
        return unavailable(ROUND_OUTPUTS, OLD_TRADES, BASIS)
    if not trades.height:
        return unavailable(ROUND_OUTPUTS, NO_TRADES, BASIS)
    import numpy as np

    price = trades["entry_price"].to_numpy()
    value = trades["quantity"].to_numpy() * price
    equity = equity_at(inputs, trades["entry_ts"].to_list())
    unit_return = trades["realized_pnl"].to_numpy() / value
    target = value / equity * params["account_size"]
    held = np.floor(target / price) * price
    ideal, rounded = math.fsum(unit_return * target), math.fsum(unit_return * held)
    return Result(
        {
            "trades": trades.height,
            "zero_share_trades": int((held == 0).sum()),
            "ideal_profit": ideal,
            "rounded_profit": rounded,
        },
        {},
        basis=BASIS,
    )


ROUNDING = make(
    "share_rounding",
    "Does a small account's whole-share rounding change the trades?",
    ("stored_equity", "run_trades"),
    (Param("account_size", float, 10000.0, None, "Account value to size the trades for."),),
    ROUND_OUTPUTS,
    "{zero_share_trades} of {trades} trades would round to no shares; whole shares change the "
    "profit from {ideal_profit:.2f} to {rounded_profit:.2f}.",
    "Each position keeps the share of equity the run used, rounded down. Costs are taken as the "
    "same rate of the traded value, so a flat fee on a small order is not captured.",
    rounding,
)

CHECKS: tuple[ToolSpec, ...] = (
    SCHEDULE,
    ROUNDING,
)
