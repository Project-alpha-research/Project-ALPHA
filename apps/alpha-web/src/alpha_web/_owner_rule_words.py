"""A stored owner rule as one plain sentence, built from the stored JSON only.

The run's manifest holds the canonical rule spec (``spine.rule.spec``). Nothing here imports the
strategy package. An operand or operator this table does not know is shown as its exact stored
text with the words "not yet described": it is never dropped and never guessed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

NOT_DESCRIBED = "not yet described"
_OPS = {">": "is above", "<": "is below", ">=": "is at or above", "<=": "is at or below"}
_SOURCES = ("close", "high", "low")


def _num(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _stored(value: Any) -> str:
    return f"{json.dumps(value, sort_keys=True, default=str)} ({NOT_DESCRIBED})"


def _days(count: str) -> str:
    return f"{count} day" if count == "1" else f"{count} days"


def _source(operand: Mapping[str, Any]) -> str | None:
    name = operand.get("source")
    if name not in _SOURCES or set(operand) - {"source", "lag"}:
        return None
    lag = operand.get("lag", 0)
    if lag == 0:
        return f"the {name}"
    text = _num(lag)
    if text is None or float(lag) < 0 or not float(lag).is_integer():
        return None
    return f"the {name} {_days(text)} ago"


def _indicator(operand: Mapping[str, Any]) -> str | None:
    name, field = operand.get("indicator"), operand.get("field")
    raw = operand.get("params")
    if not isinstance(raw, list) or set(operand) - {"indicator", "params", "field"}:
        return None
    numbers = [_num(item) for item in raw]
    p = [text for text in numbers if text is not None]
    if len(p) != len(numbers):
        return None
    n = p[0] if p else ""
    if (
        name in ("sma", "ema", "rsi", "atr", "runs_z", "reversibility")
        and len(p) == 1
        and field is None
    ):
        return {
            "sma": f"the {n}-day average",
            "ema": f"the {n}-day exponential average",
            "rsi": f"the {n}-day RSI",
            "atr": f"the {n}-day ATR",
            "runs_z": f"the {n}-day runs z-score",
            "reversibility": f"the {n}-day time reversibility",
        }[name]
    if name == "bbands" and len(p) == 2 and field in ("upper", "middle", "lower"):
        return f"the {field} Bollinger band ({_days(p[0])}, {p[1]} deviations)"
    if name == "macd" and len(p) == 3 and field in ("line", "signal", "histogram"):
        word = {"line": "line", "signal": "signal line", "histogram": "histogram"}[field]
        return f"the MACD {word} ({', '.join(p)})"
    if name == "hawkes" and len(p) == 2 and field is None:
        return f"the Hawkes activity measure (decay {p[0]}, {_days(p[1])})"
    if name == "cmma" and len(p) == 2 and field is None:
        return (
            f"the close minus the {n}-day average, divided by the {p[1]}-day ATR "
            f"times the square root of {n}"
        )
    if name == "perm_entropy" and len(p) == 2 and field is None:
        order = float(raw[0])
        if order.is_integer() and 1 <= order <= 12:
            patterns = math.factorial(int(order))
            return f"the permutation entropy (order {n}, {p[1]} times {patterns} patterns)"
    if name == "vg_path" and len(p) == 1 and field in ("price", "inverse"):
        on = "price" if field == "price" else "inverted price"
        return f"the {n}-day visibility-graph path length on {on}"
    return None


def _operand(operand: Any) -> str:
    if isinstance(operand, Mapping):
        words = None
        if "value" in operand and set(operand) == {"value"}:
            words = _num(operand["value"])
        elif "source" in operand:
            words = _source(operand)
        elif "indicator" in operand:
            words = _indicator(operand)
        if words is not None:
            return words
    return _stored(operand)


def _condition(condition: Any) -> str:
    if not isinstance(condition, Mapping) or set(condition) != {"left", "op", "right"}:
        return _stored(condition)
    op = condition["op"]
    verb = _OPS.get(op) if isinstance(op, str) else None
    return f"{_operand(condition['left'])} {verb or _stored(op)} {_operand(condition['right'])}"


def owner_rule_sentence(spec: Any) -> str | None:
    """One plain sentence for a stored canonical rule spec; ``None`` when no spec was stored."""
    if not isinstance(spec, Mapping) or not isinstance(spec.get("long_when"), list):
        return None
    shorts = spec.get("short_when")
    tail = " The stored short side is not run by alpha test." if shorts else ""
    longs = spec["long_when"]
    if not longs:
        return f"The stored rule has no buy conditions.{tail} Long or flat."
    when = " and ".join(_condition(item) for item in longs)
    return (
        f"Buy at the next open when {when}. Sell at the next open when that stops being true."
        f"{tail} Long or flat."
    )
