"""Calendar regime checks: weekday, month, turn of month and the Halloween split."""

from __future__ import annotations

import calendar
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result
from alpha_cli.toolbox.families.regimes_base import (
    BASIS,
    MIN_GROUP,
    dated_returns,
    spec,
    two_group_outputs,
    two_group_result,
    unavailable,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

LABEL_KEYS = ("best_label", "best_mean", "worst_label", "worst_mean", "p_value", "groups")
MIN_LABELLED_BARS = 50
WEEKDAYS = tuple(calendar.day_name)
MONTHS = tuple(calendar.month_name)[1:]


def _by_label(inputs: Inputs, label: Callable[[datetime], int], names: tuple[str, ...]) -> Result:
    import numpy as np
    from scipy import stats

    dates, returns = dated_returns(inputs)
    if returns.size < MIN_LABELLED_BARS:
        return unavailable(
            LABEL_KEYS, f"Needs at least {MIN_LABELLED_BARS} scored bars; found {returns.size}."
        )
    marks = np.array([label(ts) for ts in dates])
    groups = {
        names[mark]: returns[marks == mark]
        for mark in sorted(set(marks.tolist()))
        if (marks == mark).sum() >= MIN_GROUP
    }
    if len(groups) < 2:
        return unavailable(
            LABEL_KEYS,
            f"Needs at least 2 groups with {MIN_GROUP} bars each; found {len(groups)}.",
        )
    means = {name: float(group.mean()) for name, group in groups.items()}
    best, worst = max(means, key=lambda n: means[n]), min(means, key=lambda n: means[n])
    pooled = np.concatenate(list(groups.values()))
    p_value = None if np.ptp(pooled) == 0 else float(stats.kruskal(*groups.values()).pvalue)
    rows = [{"group": n, "bars": int(groups[n].size), "mean_return": means[n]} for n in groups]
    return Result(
        {
            "best_label": best,
            "best_mean": means[best],
            "worst_label": worst,
            "worst_mean": means[worst],
            "p_value": p_value,
            "groups": len(groups),
        },
        {} if p_value is not None else {"p_value": "Returns do not vary, so no test applies."},
        details={"groups": rows},
        basis=BASIS,
    )


def _label_outputs(noun: str) -> tuple[Output, ...]:
    return (
        Output(
            "best_label", f"Best {noun}", f"The {noun} with the highest mean bar return.", "text"
        ),
        Output(
            "best_mean",
            f"Mean bar return, best {noun}",
            f"Average return per bar in the best {noun}.",
            "fraction",
        ),
        Output(
            "worst_label", f"Worst {noun}", f"The {noun} with the lowest mean bar return.", "text"
        ),
        Output(
            "worst_mean",
            f"Mean bar return, worst {noun}",
            f"Average return per bar in the worst {noun}.",
            "fraction",
        ),
        Output(
            "p_value",
            "Kruskal-Wallis p-value",
            f"Chance of {noun} means this far apart if every {noun} had the same return pattern"
            " (rank test, Kruskal and Wallis 1952).",
            "p_value",
        ),
        Output(
            "groups",
            f"{noun.capitalize()}s read",
            f"Number of {noun}s with enough bars to read.",
            "count",
        ),
    )


def day_of_week(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    return _by_label(inputs, lambda ts: ts.weekday(), WEEKDAYS)


def month_of_year(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    return _by_label(inputs, lambda ts: ts.month - 1, MONTHS)


DAY_OF_WEEK = spec(
    "regimes.day_of_week",
    "Do certain weekdays earn more than the others?",
    ("stored_equity",),
    _label_outputs("weekday"),
    "Across {groups} weekdays the best was {best_label} ({best_mean:.4%} per bar) and the worst"
    " {worst_label} ({worst_mean:.4%}); the rank test p-value for any difference is {p_value:.3f}.",
    "With several weekdays the best and worst will always differ a little; read the p-value, not"
    " the ranking. The weekday is that of the open that starts the bar.",
    "test_day_of_week_known_answer",
    day_of_week,
)
MONTH_OF_YEAR = spec(
    "regimes.calendar_month",
    "Do certain calendar months earn more than the others?",
    ("stored_equity",),
    _label_outputs("month"),
    "Across {groups} calendar months the best was {best_label} ({best_mean:.4%} per bar) and the"
    " worst {worst_label} ({worst_mean:.4%}); the rank test p-value for any difference is"
    " {p_value:.3f}.",
    "Each month pools its bars from every year, so a few strong years can fill one month. The"
    " best and worst month always differ a little; read the p-value.",
    "test_month_of_year_known_answer",
    month_of_year,
)

TURN_FIRST_BARS = 3


def turn_of_month(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    dates, returns = dated_returns(inputs)
    keys = ("turn_mean", "rest_mean", "gap", "p_value", "turn_bars", "rest_bars")
    ranks: dict[tuple[int, int], list[int]] = {}
    for index, ts in enumerate(dates):
        ranks.setdefault((ts.year, ts.month), []).append(index)
    turn = np.zeros(returns.size, dtype=bool)
    for members in ranks.values():
        turn[members[:TURN_FIRST_BARS]] = True
        turn[members[-1]] = True
    first, rest = returns[turn], returns[~turn]
    if first.size < MIN_GROUP or rest.size < MIN_GROUP:
        return unavailable(
            keys,
            f"Needs at least {MIN_GROUP} bars in each group; found {first.size} at the turn and"
            f" {rest.size} elsewhere.",
        )
    return two_group_result(first, rest, ("turn", "rest"))


TURN_OF_MONTH = spec(
    "regimes.turn_of_month",
    "Do the bars around the turn of the month earn more than the others?",
    ("stored_equity",),
    two_group_outputs(("turn", "rest"), ("month turn", "other bars"), "in that group"),
    "Bars at the turn of the month earned {turn_mean:.4%} each against {rest_mean:.4%} for the"
    " rest (p-value of the gap {p_value:.3f}).",
    "The turn is the last bar of a month and the first three of the next (the window in Lakonishok"
    " and Smidt 1988). A month the history only partly covers still counts.",
    "test_turn_of_month_known_answer",
    turn_of_month,
    kind="test",
)

WINTER = frozenset((11, 12, 1, 2, 3, 4))


def halloween(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    dates, returns = dated_returns(inputs)
    keys = ("winter_mean", "summer_mean", "gap", "p_value", "winter_bars", "summer_bars")
    winter = np.array([ts.month in WINTER for ts in dates], dtype=bool)
    first, second = returns[winter], returns[~winter]
    if first.size < MIN_GROUP or second.size < MIN_GROUP:
        return unavailable(
            keys,
            f"Needs at least {MIN_GROUP} bars in each half-year; found {first.size} from November"
            f" to April and {second.size} from May to October.",
        )
    return two_group_result(first, second, ("winter", "summer"))


HALLOWEEN = spec(
    "regimes.halloween",
    "Does it earn more from November to April than from May to October?",
    ("stored_equity",),
    two_group_outputs(("winter", "summer"), ("Nov-Apr", "May-Oct"), "in that half-year"),
    "Bars from November to April earned {winter_mean:.4%} each against {summer_mean:.4%} from May"
    " to October (p-value of the gap {p_value:.3f}).",
    "The split follows the Halloween effect in Bouman and Jacobsen (2002). It is one of many"
    " calendar splits, so a small p-value among several tries proves little.",
    "test_halloween_known_answer",
    halloween,
    kind="test",
)
