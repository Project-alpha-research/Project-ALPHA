"""Value, unit, sign, precision and number-word rules for `alpha results check`."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from alpha_cli.spine.compare import Fact, numeric_fact
from alpha_cli.spine.facts import METRIC_UNITS, NEGATIVE_BY_CONVENTION

THRESHOLDS = {"dsr": 0.95, "trial_dsr": 0.95}
# A positive magnitude for a drawdown is accepted only after one of these words, in its sentence.
MAGNITUDE_WORDS = (
    r"\b(?:drawdown of|loss of|fall of|fell|fallen|lost|losing|dropped|declined?|down)\b"
)
_UNIT_NAMES = {"ratio": "a ratio", "count": "a count", "other": "not a number"}
_FINANCIAL = re.compile(
    r"\b(?:sharpe|dsr|cagr|returns?|drawdowns?|beta|exposure|profits?|volatility)\b",
    re.IGNORECASE,
)
_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|million|point)"
)
NUMBER_WORDS = re.compile(rf"\b{_WORD}(?:[\s-]+(?:and[\s-]+)?{_WORD})*\b", re.IGNORECASE)
_UNIT_AFTER = r"\s+(?:trades?|percent|per cent|bps|basis points)\b"


def financial_context(visible: str, start: int, end: int, window: int = 40) -> bool:
    """True when a metric word precedes (same line, within window characters) or a unit follows."""
    before = visible[visible.rfind("\n", 0, start) + 1 : start]
    return any(len(before) - word.end() <= window for word in _FINANCIAL.finditer(before)) or bool(
        re.match(_UNIT_AFTER, visible[end:], re.IGNORECASE)
    )


def spelled_numbers(visible: str) -> list[re.Match[str]]:
    """Numbers written in words next to a metric word; bare "one" and ordinary counts pass."""
    found = []
    for match in NUMBER_WORDS.finditer(visible):
        words = re.findall(r"[a-z]+", match.group().lower())
        if all(word in ("point", "and") for word in words):
            continue
        if words == ["one"] and not re.match(_UNIT_AFTER, visible[match.end() :], re.IGNORECASE):
            continue
        if financial_context(visible, match.start(), match.end(), window=20):
            found.append(match)
    return found


def unit_kind(metric: str, operation: str | None) -> str:
    return "ratio" if operation == "ratio" else METRIC_UNITS.get(metric, "other")


def match_value(
    written: str, fact: Fact, kind: str, sentence_before: str = ""
) -> tuple[str, str, Any] | None:
    fact = numeric_fact(fact)
    if fact["value"] is None:
        return "VALUE_NOT_COMPUTED", f"The record has no numeric value: {fact['reason']}", fact
    percent, times = written.endswith("%"), written[-1] in "x×"
    if (percent and kind != "fraction") or (times and kind != "ratio"):
        suffix = "a percentage" if percent else "a multiple"
        return (
            "UNIT_MISMATCH",
            f"Metric {fact['metric']} is {_UNIT_NAMES.get(kind, 'a fraction')}, not {suffix}; "
            f"written {written}.",
            {"value": fact["value"], "unit": kind},
        )
    number = written.rstrip("%x×").replace(",", "")
    decimals = len(number.partition(".")[2])
    stored = Decimal(str(fact["value"]))
    if (
        stored < 0
        and fact["metric"] in NEGATIVE_BY_CONVENTION
        and "run_ids" not in fact
        and not number.startswith("-")
        and re.search(MAGNITUDE_WORDS, sentence_before, re.IGNORECASE)
    ):
        stored = abs(stored)
    with localcontext() as context:
        context.prec = max(50, len(number) + 330)
        scaled = stored * (100 if percent else 1)
        rounded = scaled.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_EVEN)
    if rounded != Decimal(number):
        return (
            "VALUE_MISMATCH",
            f"Written {written}; stored {fact['value']}; at written precision {rounded}. "
            "Keep the sign, or write a magnitude after a word such as 'drawdown of'.",
            {"value": fact["value"], "rounded": str(rounded)},
        )
    needed = 1 if kind == "ratio" else 2 - 2 * percent
    if kind in ("ratio", "fraction") and decimals < needed and scaled != Decimal(number):
        unit = "one decimal for a ratio" if kind == "ratio" else "a whole percent for a fraction"
        return (
            "PRECISION_TOO_LOW",
            f"Written {written} rounds stored {fact['value']} too coarsely; write at least {unit}.",
            {"value": fact["value"]},
        )
    threshold = THRESHOLDS.get(fact.get("metric", ""))
    stated = Decimal(number) / (100 if percent else 1)
    if threshold is not None and stored < Decimal(str(threshold)) <= stated:
        return (
            "ROUNDED_ACROSS_THRESHOLD",
            f"Stored {fact['value']} is below the pass line {threshold}; written {written} "
            "reads as passing. Write at least three decimals.",
            {"value": fact["value"], "threshold": threshold},
        )
    return None
