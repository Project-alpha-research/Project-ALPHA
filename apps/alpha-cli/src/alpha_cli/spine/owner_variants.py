"""Parameter variants of an owner rule, for the sensitivity table of a rule test.

Each window and each non-zero constant is tried at 0.8 and 1.2 times its value, one change at a
time. Windows round to whole bars (at least 2; a lag at least 1). A variant equal to the original,
or one the rule language refuses, is left out. At most ``MAX_VARIANTS`` are kept, in the order the
numbers appear in the rule. Nothing here ranks or picks a variant.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from alpha_cli.spine.owner_rule import CONSTANT_NAME, canonical_spec
from alpha_core import DataError
from alpha_strategies.rules import parse_rule_spec

MAX_VARIANTS = 8
FACTORS = (0.8, 1.2)
# Indicators whose params are all window lengths, and the params that are windows in the others.
# Bollinger's second param is a width in standard deviations and the research indicators' params
# are not all windows, so those stay as written.
_WINDOW_INDEXES: dict[str, tuple[int, ...]] = {
    "sma": (0,),
    "ema": (0,),
    "rsi": (0,),
    "atr": (0,),
    "bbands": (0,),
    "macd": (0, 1, 2),
    "highest": (0,),
    "lowest": (0,),
}
_SIDES = ("left", "right")


def _round_number(value: float) -> float:
    return float(f"{value:.10g}")


def _slots(spec: Mapping[str, Any]) -> list[tuple[tuple[int, str], str, int, float]]:
    """Every number that may vary: (condition, side), kind, param index, value."""
    found: list[tuple[tuple[int, str], str, int, float]] = []
    for index, condition in enumerate(spec["long_when"]):
        for side in _SIDES:
            operand = condition[side]
            where = (index, side)
            if "value" in operand:
                if float(operand["value"]) != 0.0:
                    found.append((where, "constant", 0, float(operand["value"])))
            elif operand.get("lag"):
                found.append((where, "lag", 0, float(operand["lag"])))
            for position in _WINDOW_INDEXES.get(str(operand.get("indicator")), ()):
                found.append((where, "window", position, float(operand["params"][position])))
    return found


def _changed(
    spec: Mapping[str, Any],
    where: tuple[int, str],
    kind: str,
    position: int,
    new: float,
) -> dict[str, Any] | None:
    """The spec with one number changed, or None when the rule language refuses it."""
    edit = copy.deepcopy(dict(spec))
    operand = edit["long_when"][where[0]][where[1]]
    if kind == "constant":
        operand["value"] = new
    elif kind == "lag":
        operand["lag"] = int(new)
    else:
        operand["params"][position] = int(new)
    try:
        return canonical_spec(edit)
    except ValueError:
        # The window outgrew the history: widen it only as far as the changed rule needs.
        bare = {key: val for key, val in edit.items() if key != "history"}
    try:
        warmup = parse_rule_spec({**bare, "name": CONSTANT_NAME}).warmup
        return canonical_spec({**bare, "history": max(int(spec["history"]), warmup)})
    except (DataError, ValueError):
        return None


_MACD_NAMES = ("fast", "slow", "signal")


def _label(
    spec: Mapping[str, Any],
    where: tuple[int, str],
    kind: str,
    position: int,
    old: float,
    new: float,
) -> str:
    def text(number: float) -> str:
        return str(int(number)) if float(number).is_integer() else repr(float(number))

    operand = spec["long_when"][where[0]][where[1]]
    if kind == "window" and operand.get("indicator") == "macd":
        kind = f"{_MACD_NAMES[position]} window"
    return f"condition {where[0] + 1} {where[1]} {kind} {text(old)} to {text(new)}"


def owner_variants(spec: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Named neighbour specs of a canonical owner-rule spec, at most ``MAX_VARIANTS``."""
    seen = {repr(sorted(spec.items()))}
    found: list[tuple[str, dict[str, Any]]] = []
    for where, kind, position, value in _slots(spec):
        for factor in FACTORS:
            if kind == "constant":
                new = _round_number(value * factor)
            else:
                new = float(max(1 if kind == "lag" else 2, round(value * factor)))
            if new == value:
                continue
            variant = _changed(spec, where, kind, position, new)
            if variant is None or variant == dict(spec) or repr(sorted(variant.items())) in seen:
                continue
            seen.add(repr(sorted(variant.items())))
            found.append((_label(spec, where, kind, position, value, new), variant))
            if len(found) == MAX_VARIANTS:
                return found
    return found
