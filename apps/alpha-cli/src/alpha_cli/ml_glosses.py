"""Plain words for a stored model run: its reading word, who won, each number and held-back bars.

Pure functions of the manifest. Numbers in context, no verdict, no grade and no advice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from alpha_cli.spine import reading

NOT_RUN = "the returns did not vary"


def _value(metrics: Mapping[str, Any], key: str) -> float | None:
    found = metrics.get(key)
    return float(found) if isinstance(found, int | float) and not isinstance(found, bool) else None


def reading_word(manifest: Mapping[str, Any]) -> tuple[str, list[str]]:
    """The rule test's evidence word for a model run, and why.

    A model run holds no random-data test and no Sharpe interval, and a missing one reads
    "not clear of chance" (see `spine.reading.WORDS`). Few test days read "too little to read".
    """
    days = manifest.get("n_oos_periods")
    if isinstance(days, int) and days < reading.MIN_OOS_OBSERVATIONS:
        return reading.TOO_LITTLE, [
            f"{days} out-of-sample test days (fewer than {reading.MIN_OOS_OBSERVATIONS})."
        ]
    return reading.NOT_CLEAR, [
        "A model run is replayed once, so it holds no random-data test and no Sharpe interval.",
        "A missing one reads this way.",
    ]


def versus_basket(manifest: Mapping[str, Any]) -> str | None:
    """Which returned more over the test days, the model or the basket; None when not stored."""
    excess = _value(manifest.get("metrics") or {}, "costed_excess_total_return")
    if excess is None:
        return None
    if excess < 0:
        return "The model returned less than holding the basket."
    if excess > 0:
        return "The model returned more than holding the basket."
    return "The model returned the same as holding the basket."


def _pct(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:.1f}%"


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _ratio(value: float) -> str:
    return f"{value:.2f}"


def _times(value: float) -> str:
    return f"{value:.2f} times"


def _money(value: float) -> str:
    return f"{value:,.0f}"


# (name, stored key, format, gloss, why it can be missing)
_ROWS = (
    (
        "Return after costs",
        "total_return",
        _percent,
        "what the account gained or lost over the test days",
        "not stored",
    ),
    (
        "Return before costs",
        "gross_total_return",
        _percent,
        "compounded return over the same days with no fees or slippage",
        "not stored",
    ),
    (
        "Equal-weight basket return",
        "benchmark_total_return",
        _percent,
        "holding every asset in equal parts over the same days",
        "not stored",
    ),
    (
        "Return minus the basket",
        "costed_excess_total_return",
        _percent,
        "the model's return "
        "after costs less the basket's; below zero means the basket returned more",
        "not stored",
    ),
    (
        "Largest fall",
        "max_drawdown",
        _percent,
        "the biggest drop from a peak in the account",
        "not stored",
    ),
    (
        "Yearly growth rate",
        "cagr",
        _percent,
        "the return after costs, scaled to one year",
        "not stored",
    ),
    (
        "Yearly volatility",
        "annualized_volatility",
        _percent,
        "how much the daily returns swing, scaled to one year",
        NOT_RUN,
    ),
    (
        "Sharpe ratio",
        "sharpe",
        _ratio,
        "return per unit of risk, per year; above 0 is a gain",
        NOT_RUN,
    ),
    (
        "Probabilistic Sharpe",
        "psr",
        _ratio,
        "the chance the true Sharpe is above 0, judged from this sample",
        NOT_RUN,
    ),
    (
        "Deflated Sharpe",
        "dsr",
        _ratio,
        "the same chance after counting tries; this replay counts "
        "one try, so it equals the line above",
        NOT_RUN,
    ),
    (
        "Turnover per period",
        "mean_turnover",
        _times,
        "the amount traded each period, as a multiple of the account",
        "not stored",
    ),
    (
        "Fees paid",
        "total_fees",
        _money,
        "the fees charged on each trade over the test days, in account currency",
        "not stored",
    ),
    (
        "Slippage cost",
        "total_slippage_cost",
        _money,
        "the price lost to slippage over the test days, in account currency",
        "not stored",
    ),
)


def number_lines(manifest: Mapping[str, Any]) -> list[str]:
    """Each stored number with its plain name and a few words of gloss; a gap says why."""
    metrics = manifest.get("metrics") or {}
    lines = []
    for name, key, shown, gloss, why in _ROWS:
        value = _value(metrics, key)
        lines.append(
            f"{name}: {shown(value)} ({gloss})."
            if value is not None
            else f"{name}: not computed ({why})."
        )
    return lines


def held_back_sentence(block: Mapping[str, Any], assets: int) -> str:
    """The hold-back sentence for a basket: bars per asset, not the sum over all assets."""
    total = block["held_back_bars"]
    each = total / assets
    count = f"{each:.0f}" if total % assets == 0 else f"about {each:.0f}"
    return (
        f"Held back {count} bars for each of {assets} assets from {block['reserved_start']} on; "
        "they are kept for the owner's confirmation of an idea, so this test did not use them."
    )
