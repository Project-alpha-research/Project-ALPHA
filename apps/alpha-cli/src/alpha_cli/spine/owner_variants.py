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
    return _edited(spec, [(where, kind, position, new)])


def _edited(
    spec: Mapping[str, Any], edits: list[tuple[tuple[int, str], str, int, float]]
) -> dict[str, Any] | None:
    """The spec with each number changed at once, or None when the rule language refuses it."""
    edit = copy.deepcopy(dict(spec))
    for where, kind, position, new in edits:
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


def _moved(kind: str, value: float, factor: float) -> float:
    if kind == "constant":
        return _round_number(value * factor)
    return float(max(1 if kind == "lag" else 2, round(value * factor)))


def owner_variants(
    spec: Mapping[str, Any], *, factors: tuple[float, ...] = FACTORS
) -> list[tuple[str, dict[str, Any]]]:
    """Named neighbour specs of a canonical owner-rule spec, at most ``MAX_VARIANTS`` per factor
    pair (so 8 at the two default factors)."""
    limit = MAX_VARIANTS * max(1, len(factors) // len(FACTORS))
    seen = {repr(sorted(spec.items()))}
    found: list[tuple[str, dict[str, Any]]] = []
    for where, kind, position, value in _slots(spec):
        for factor in factors:
            new = _moved(kind, value, factor)
            if new == value:
                continue
            variant = _changed(spec, where, kind, position, new)
            if variant is None or variant == dict(spec) or repr(sorted(variant.items())) in seen:
                continue
            seen.add(repr(sorted(variant.items())))
            found.append((_label(spec, where, kind, position, value, new), variant))
            if len(found) == limit:
                return found
    return found


def owner_grid(
    spec: Mapping[str, Any], factors: tuple[float, ...]
) -> tuple[int, list[tuple[str, dict[str, Any] | None]]]:
    """Every pair of ``factors`` on the first two numbers of the rule (one number: a line).

    Returns how many numbers the grid moves and one (label, spec) per grid point other than the
    rule itself; the spec is None where the rule language refuses that point.
    """
    slots = _slots(spec)[:2]
    points: list[tuple[str, dict[str, Any] | None]] = []
    combos: list[tuple[float, ...]] = [()]
    for _ in slots:
        combos = [(*combo, factor) for combo in combos for factor in factors]
    for combo in combos:
        if all(factor == 1.0 for factor in combo):
            continue
        edits = []
        labels = []
        for (where, kind, position, value), factor in zip(slots, combo, strict=True):
            new = _moved(kind, value, factor)
            labels.append(_label(spec, where, kind, position, value, new))
            if new != value:
                edits.append((where, kind, position, new))
        changed = _edited(spec, edits) if edits else None
        points.append(("; ".join(labels), None if changed == dict(spec) else changed))
    return len(slots), points
