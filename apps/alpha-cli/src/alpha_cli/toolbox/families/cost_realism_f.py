"""Cost realism of entries against the bars: share of volume and limit-order fills."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from alpha_cli.toolbox.families.cost_realism_d import BASIS, WINDOW, entries

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs


def _none(outputs: tuple[Output, ...], reason: str) -> Result:
    return unavailable(outputs, reason, BASIS)


def _nothing() -> str:
    return "Too little to read: no entry has enough volume history in the bars before it."


PARTICIPATION_OUTPUTS = (
    Output(
        "measured", "Trades measured", "Entries with a full window of bars before them.", "count"
    ),
    Output(
        "over_cap",
        "Trades over the cap",
        "Entries larger than the cap share of average volume.",
        "count",
    ),
    Output(
        "max_participation",
        "Largest share of volume",
        "Largest order over the average volume.",
        "fraction",
    ),
)


def participation(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    found, _, why = entries(inputs, params["window"], 1.0)
    if why or not found:
        return _none(PARTICIPATION_OUTPUTS, why or _nothing())
    share = np.array([e.participation for e in found])
    return Result(
        {
            "measured": len(found),
            "over_cap": int((share > params["cap_pct"] / 100).sum()),
            "max_participation": float(share.max()),
        },
        {},
        basis=BASIS,
    )


PARTICIPATION = make(
    "volume_share",
    "Does any order take too large a share of the day's volume?",
    ("run_trades", "run_bars"),
    (
        WINDOW,
        Param(
            "cap_pct", float, 5.0, None, "Share of average volume, in percent, to count against."
        ),
    ),
    PARTICIPATION_OUTPUTS,
    "{over_cap} of {measured} orders were bigger than the cap; the largest took "
    "{max_participation:.2%} of average volume.",
    "Average volume before the entry is not the volume of the fill day. The cap is a level "
    "you set, not a rule of any venue.",
    participation,
)

LIMIT_OUTPUTS = (
    Output("measured", "Entries measured", "Entries whose bar is in the bars.", "count"),
    Output(
        "touch_share",
        "Reached by the range",
        "Share of entries where the bar's range touched the limit.",
        "fraction",
    ),
    Output(
        "through_share",
        "Traded through",
        "Share where the range went strictly past the limit.",
        "fraction",
    ),
)


def limit_fills(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    trades = closed_trades(inputs, "side", "entry_ts", "exit_ts")
    if trades is None:
        return _none(LIMIT_OUTPUTS, OLD_TRADES)
    bars = {b.ts: b for b in run_bars(inputs)}
    if not trades.height or not bars:
        return _none(LIMIT_OUTPUTS, NO_TRADES if bars else NO_BARS)
    offset = params["offset_bps"] / 1e4
    touch = through = measured = 0
    for ts, side in zip(trades["entry_ts"], trades["side"], strict=True):
        bar = bars.get(ts)
        if bar is None:
            continue
        measured += 1
        if side == "BUY":
            limit = bar.open * (1 - offset)
            touch, through = touch + (bar.low <= limit), through + (bar.low < limit)
        else:
            limit = bar.open * (1 + offset)
            touch, through = touch + (bar.high >= limit), through + (bar.high > limit)
    if not measured:
        return _none(LIMIT_OUTPUTS, "Too little to read: no entry date is in the bars.")
    return Result(
        {
            "measured": measured,
            "touch_share": touch / measured,
            "through_share": through / measured,
        },
        {},
        basis=BASIS,
    )


LIMIT_FILL = make(
    "limit_fill",
    "Would a limit order below or above the open have filled on the entry day?",
    ("run_trades", "run_bars"),
    (
        Param(
            "offset_bps",
            float,
            25.0,
            None,
            "How far from the open the limit rests, in basis points.",
        ),
    ),
    LIMIT_OUTPUTS,
    "Of {measured} entries a resting limit was touched on {touch_share:.0%} and traded through on "
    "{through_share:.0%}.",
    "A daily range cannot show queue position or order of events inside the day, so a touch may "
    "not be a fill. It ignores the trades a missed limit would have changed.",
    limit_fills,
)

CHECKS: tuple[ToolSpec, ...] = (
    PARTICIPATION,
    LIMIT_FILL,
)
