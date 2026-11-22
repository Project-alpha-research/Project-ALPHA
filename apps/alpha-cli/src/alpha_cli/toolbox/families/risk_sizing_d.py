"""Attribution checks on closed trades: holding period and weekday."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.risk_common import (
    TRADE_BASIS,
    check,
    closed_trades,
    too_few_trades,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

TESTS = "test_toolbox_risk_sizing_d"
MIN_TRADES = 10
BUCKETS = ("short", "medium", "long")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
THIN = (
    "Closed trades cannot tell you what the open position earned, and few trades per group mean"
    " noise."
)


def hold_period(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = tuple(f"{b}_{stat}" for b in BUCKETS for stat in ("count", "win_rate", "average_pnl"))
    short, long = params["short_days"], params["long_days"]
    if long <= short:
        raise ValueError("long_days must be larger than short_days")
    trades = closed_trades(inputs)
    if (why := too_few_trades(len(trades.pnl), MIN_TRADES)) is not None:
        return unavailable(keys, why, TRADE_BASIS)
    held = np.array(
        [(e - s).total_seconds() / 86400 for s, e in zip(trades.entry, trades.exit, strict=True)]
    )
    masks = {"short": held <= short, "medium": (held > short) & (held <= long), "long": held > long}
    values: dict[str, Any] = {}
    reasons = {}
    for name, mask in masks.items():
        pnl = trades.pnl[mask]
        values[f"{name}_count"] = int(mask.sum())
        if mask.any():
            values[f"{name}_win_rate"] = float((pnl > 0).mean())
            values[f"{name}_average_pnl"] = float(pnl.mean())
        else:
            for stat in ("win_rate", "average_pnl"):
                values[f"{name}_{stat}"] = None
                reasons[f"{name}_{stat}"] = f"No closed trades held for the {name} period."
    return Result(values, reasons, basis=TRADE_BASIS)


def weekday(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np
    from scipy import stats

    keys = (
        "best_weekday",
        "p_value",
        *(f"{d}_{s}" for d in DAYS for s in ("count", "average_pnl")),
    )
    trades = closed_trades(inputs)
    if (why := too_few_trades(len(trades.pnl), MIN_TRADES)) is not None:
        return unavailable(keys, why, TRADE_BASIS)
    day = np.array([ts.weekday() for ts in trades.entry])
    values: dict[str, Any] = {}
    reasons = {}
    groups = []
    for index, name in enumerate(DAYS):
        pnl = trades.pnl[day == index]
        values[f"{name}_count"] = len(pnl)
        if len(pnl):
            values[f"{name}_average_pnl"] = float(pnl.mean())
            groups.append(pnl)
        else:
            values[f"{name}_average_pnl"] = None
            reasons[f"{name}_average_pnl"] = f"No trades were entered on a {name.title()}."
    firm = {n: values[f"{n}_average_pnl"] for n in DAYS if values[f"{n}_count"] >= 3}
    if firm:
        values["best_weekday"] = max(firm, key=lambda n: firm[n]).title()
    else:
        values["best_weekday"] = None
        reasons["best_weekday"] = "No weekday has three or more entries."
    if len(groups) < 2 or np.ptp(trades.pnl) == 0:
        values["p_value"] = None
        reasons["p_value"] = (
            "All profits are identical, so no difference can be read."
            if len(groups) >= 2
            else "Entries fall on a single weekday."
        )
    else:
        # Kruskal and Wallis (1952): rank test of whether the weekdays share one profit level.
        values["p_value"] = float(stats.kruskal(*groups).pvalue)
    return Result(values, reasons, basis=TRADE_BASIS)


def _hold_outputs() -> tuple[Output, ...]:
    labels = {
        "short": "held up to the short limit",
        "medium": "held between the limits",
        "long": "held beyond the long limit",
    }
    outputs = []
    for name in BUCKETS:
        outputs += [
            Output(
                f"{name}_count", f"{name.title()} holds", f"Closed trades {labels[name]}.", "count"
            ),
            Output(
                f"{name}_win_rate",
                f"{name.title()} win rate",
                f"Share of trades {labels[name]} with profit above zero.",
                "fraction",
            ),
            Output(
                f"{name}_average_pnl",
                f"{name.title()} average profit",
                f"Average after-cost profit of trades {labels[name]}.",
                "currency",
            ),
        ]
    return tuple(outputs)


def _weekday_outputs() -> tuple[Output, ...]:
    outputs = [
        Output(
            "best_weekday",
            "Best weekday",
            "Weekday of entry with the highest average profit among those with three or more"
            " entries.",
            "text",
        ),
        Output(
            "p_value",
            "Kruskal-Wallis p-value",
            "Chance of weekday profit gaps this large if the weekday did not matter.",
            "p_value",
        ),
    ]
    for name in DAYS:
        outputs += [
            Output(
                f"{name}_count",
                f"{name.title()} entries",
                f"Closed trades entered on a {name.title()}.",
                "count",
            ),
            Output(
                f"{name}_average_pnl",
                f"{name.title()} average profit",
                f"Average after-cost profit of trades entered on a {name.title()}.",
                "currency",
            ),
        ]
    return tuple(outputs)


CHECKS = (
    check(
        "attribution.hold_period",
        TESTS,
        question="Do short or long holds earn more per trade?",
        answers=("Do my short or my long trades earn more?",),
        situations=("lucky-trades", "few-trades"),
        needs=("run_trades",),
        params=(
            Param(
                "short_days", int, 5, range(1, 366), "Longest hold, in days, that counts as short."
            ),
            Param(
                "long_days", int, 20, range(2, 731), "Longest hold, in days, that counts as medium."
            ),
        ),
        outputs=_hold_outputs(),
        reading=(
            "Short holds ({short_count} trades) averaged {short_average_pnl:.2f}, medium holds"
            " ({medium_count}) {medium_average_pnl:.2f} and long holds ({long_count})"
            " {long_average_pnl:.2f}."
        ),
        caveats=(THIN,),
        compute=hold_period,
        family="attribution",
    ),
    check(
        "attribution.weekday",
        TESTS,
        question="Which weekday of entry earned the most per trade?",
        answers=("Does the day I enter matter?",),
        situations=("works-only-sometimes", "few-trades"),
        needs=("run_trades",),
        outputs=_weekday_outputs(),
        reading=(
            "Trades entered on a {best_weekday} earned most on average (p-value {p_value:.3f}; a"
            " large"
            " p-value means the weekday gaps are within chance)."
        ),
        caveats=(THIN,),
        compute=weekday,
        family="attribution",
    ),
)
