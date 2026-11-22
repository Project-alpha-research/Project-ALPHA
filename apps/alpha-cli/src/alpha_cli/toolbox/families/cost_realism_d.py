"""Cost realism of the run's trades against the run's own bars: size, impact and limit fills."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, NamedTuple

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec
from alpha_cli.toolbox.families.cost_realism_common import (
    NO_BARS,
    NO_TRADES,
    OLD_TRADES,
    closed_trades,
    make,
    run_bars,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

BASIS = "Closed trades with the volume and range of the bars just before each entry."
SIDES = ("quantity", "entry_price", "entry_ts", "exit_ts", "realized_pnl", "side")
WINDOW = Param(
    "window", int, 20, range(5, 121), "Bars before each entry used for volume and volatility."
)
COEFF = Param(
    "coefficient", float, 1.0, None, "Impact coefficient Y in Y x volatility x sqrt(size / volume)."
)


class Entry(NamedTuple):
    notional: float
    participation: float
    impact: float  # square-root impact of one side, as a fraction of price
    pnl: float


def entries(inputs: Inputs, window: int, coefficient: float) -> tuple[list[Entry], int, str | None]:
    """Each entry's size against the volume and volatility of the `window` bars before it."""
    import numpy as np

    trades = closed_trades(inputs, *SIDES)
    if trades is None:
        return [], 0, OLD_TRADES
    if not trades.height:
        return [], 0, NO_TRADES
    bars = run_bars(inputs)
    if not bars:
        return [], 0, NO_BARS
    index = {b.ts: i for i, b in enumerate(bars)}
    close = np.array([b.close for b in bars])
    volume = np.array([b.volume for b in bars])
    found: list[Entry] = []
    for ts, qty, price, pnl in zip(
        trades["entry_ts"],
        trades["quantity"],
        trades["entry_price"],
        trades["realized_pnl"],
        strict=True,
    ):
        i = index.get(ts)
        if i is None or i < window + 1:
            continue
        adv = float(volume[i - window : i].mean())
        sigma = float(np.std(np.diff(np.log(close[i - window - 1 : i])), ddof=1))
        if adv > 0 and math.isfinite(sigma):
            share = qty / adv
            found.append(Entry(qty * price, share, coefficient * sigma * math.sqrt(share), pnl))
    return found, trades.height - len(found), None


def _none(outputs: tuple[Output, ...], reason: str) -> Result:
    return unavailable(outputs, reason, BASIS)


def _nothing() -> str:
    return "Too little to read: no entry has enough volume history in the bars before it."


IMPACT_OUTPUTS = (
    Output(
        "measured", "Trades measured", "Entries with a full window of bars before them.", "count"
    ),
    Output("mean_impact_bps", "Average impact", "Mean square-root impact of one side.", "bps"),
    Output(
        "impact_cost",
        "Impact cost",
        "Impact on the opening and the closing order of every measured trade.",
        "currency",
    ),
)


def impact(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Square-root law: impact = Y sigma sqrt(Q / V) (Almgren and Chriss 2000;
    Almgren, Thum, Hauptmann and Li 2005)."""
    found, _, why = entries(inputs, params["window"], params["coefficient"])
    if why or not found:
        return _none(IMPACT_OUTPUTS, why or _nothing())
    bps = [e.impact * 1e4 for e in found]
    return Result(
        {
            "measured": len(found),
            "mean_impact_bps": math.fsum(bps) / len(bps),
            "impact_cost": 2 * math.fsum(e.notional * e.impact for e in found),
        },
        {},
        basis=BASIS,
    )


IMPACT = make(
    "market_impact",
    "How much would the size of these orders move the price?",
    ("run_trades", "run_bars"),
    (WINDOW, COEFF),
    IMPACT_OUTPUTS,
    "Across {measured} trades the square-root model puts impact at {mean_impact_bps:.1f} basis "
    "points a side {impact_cost:.2f} in total.",
    "The square-root law is a rough average over many large orders. For small orders it is an "
    "upper-bound guess, and the coefficient is an assumption you set.",
    impact,
)

CAPACITY_OUTPUTS = (
    *(
        Output(
            f"return_x{m}",
            f"Return at {m} times the money",
            f"Profit less impact with {m} times the capital, over that capital.",
            "fraction",
        )
        for m in (1, 10, 100)
    ),
    Output(
        "zero_profit_multiple",
        "Capital multiple at zero",
        "Multiple of the run's capital where impact uses up all profit.",
        "ratio",
    ),
)


def capacity(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Profit(m) = m P - 2 m^1.5 C, where C sums notional x impact of one side at m = 1."""
    from alpha_cli.toolbox.families.cost_realism_common import equity_at

    found, skipped, why = entries(inputs, params["window"], params["coefficient"])
    if why or not found:
        return _none(CAPACITY_OUTPUTS, why or _nothing())
    if skipped:
        return _none(
            CAPACITY_OUTPUTS,
            f"Too little to read: {skipped} trades lack volume history, so profit is partial.",
        )
    first = min(inputs.stored.table("run_trades", "entry_ts")["entry_ts"])
    start = float(equity_at(inputs, [first])[0])
    profit = math.fsum(e.pnl for e in found)
    cost = math.fsum(e.notional * e.impact for e in found)
    values: dict[str, Any] = {}
    for m in (1, 10, 100):
        values[f"return_x{m}"] = (m * profit - 2 * m**1.5 * cost) / (m * start)
    reasons = {}
    if profit > 0 and cost > 0:
        values["zero_profit_multiple"] = (profit / (2 * cost)) ** 2
    else:
        values["zero_profit_multiple"] = None
        reasons["zero_profit_multiple"] = "Profit is not positive, or no impact was measured."
    return Result(values, reasons, basis=BASIS)


CAPACITY = make(
    "capacity_curve",
    "How does the return change as more capital is deployed?",
    ("stored_equity", "run_trades", "run_bars"),
    (WINDOW, COEFF),
    CAPACITY_OUTPUTS,
    "After market impact the return is {return_x1:.1%} on the run's capital, {return_x10:.1%} with "
    "ten times the money and {return_x100:.1%} with a hundred times.",
    "Profit is scaled in proportion to size and impact follows the square-root law, so it counts "
    "the run's own slippage twice. It is a rough ceiling guide, not a capacity limit.",
    capacity,
)

CHECKS: tuple[ToolSpec, ...] = (IMPACT, CAPACITY)
