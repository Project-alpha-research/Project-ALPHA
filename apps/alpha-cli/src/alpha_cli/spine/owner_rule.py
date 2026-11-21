"""The owner's rule language inside an idea spec.

One canonical form (always inline, parsed by the rule language's own parser, then dumped), the
refusals that keep a test honest, the family shape that groups tries of one idea, and plain words.
The rule language itself lives in ``alpha_strategies.rules``; this module only adapts it to the
spine. Long and flat only: the short side is refused until the engine can run it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from alpha_core import DataError
from alpha_strategies.rules import (
    Condition,
    Operand,
    RuleSpec,
    canonical_json,
    parse_rule_spec,
)

#: The display name lives on ``IdeaSpec.name``; inside the hash the rule name is this constant.
CONSTANT_NAME = "owner-rule"
SHORT_REFUSED = (
    "the short side is not built yet in alpha test: remove short_when "
    "(a rule here is long while its conditions hold, flat otherwise)"
)
VOLUME_REFUSED = (
    "the indicator vsa reads volume, which the rule window does not keep: "
    "alpha test cannot use it yet"
)
PRICE_LEVEL_REFUSED = (
    "'{label}' compares a price level with a fixed number or an unscaled indicator: the "
    "random-price test rebuilds prices from returns, so a fixed price level has no meaning there. "
    "Compare a price with an average, a lagged price or another price, or use rsi"
)
NULL_CLOSES = "null-closes-for-high-low"
VARIANTS_NOTE = (
    "Parameter variants are not built for owner rules yet; only the doubled-cost variant ran."
)

_PRICE_SCALED = frozenset({"sma", "ema", "atr", "bbands", "macd"})
_READS_RANGE = frozenset({"atr", "hawkes", "cmma"})
_NAMES = {
    "sma": "SMA",
    "ema": "EMA",
    "rsi": "RSI",
    "atr": "ATR",
    "bbands": "Bollinger",
    "macd": "MACD",
    "hawkes": "Hawkes",
    "cmma": "CMMA",
    "runs_z": "runs z",
    "perm_entropy": "permutation entropy",
    "vg_path": "visibility-graph path",
    "reversibility": "reversibility",
}


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _scale(operand: Operand) -> str:
    if operand.kind == "value":
        return "const"
    if operand.kind == "source" or operand.indicator in _PRICE_SCALED:
        return "price"
    return "free"


def _check_scale(condition: Condition) -> None:
    left, right = _scale(condition.left), _scale(condition.right)
    zero = (condition.left.value == 0) or (condition.right.value == 0)
    if left == right or (zero and "const" in (left, right)):
        return
    if "const" in (left, right) and "free" in (left, right):
        return
    raise ValueError(PRICE_LEVEL_REFUSED.format(label=condition.label))


def _parsed(spec: Mapping[str, Any]) -> RuleSpec:
    return parse_rule_spec(spec)


def canonical_spec(value: object) -> dict[str, Any]:
    """The one inline form of a rule spec; every refusal is a ``ValueError`` with its reason."""
    if not isinstance(value, Mapping):
        raise ValueError("an owner rule needs a spec table (the rule language's RuleSpec)")
    if value.get("short_when"):
        raise ValueError(SHORT_REFUSED)
    try:
        parsed = _parsed({**value, "name": CONSTANT_NAME})
    except DataError as exc:
        raise ValueError(str(exc)) from exc
    if any(operand.indicator == "vsa" for operand in parsed.operands):
        raise ValueError(VOLUME_REFUSED)
    for condition in (*parsed.long_when, *parsed.short_when):
        _check_scale(condition)
    plain: dict[str, Any] = json.loads(canonical_json(parsed))
    return plain


def _operand_shape(operand: Operand) -> str:
    if operand.kind == "value":
        return "#"
    if operand.kind == "source":
        return f"{operand.source}:lag:#" if operand.lag else str(operand.source)
    parts = [str(operand.indicator), *("#" for _ in operand.params)]
    return ":".join([*parts, operand.field] if operand.field else parts)


def _condition_shape(condition: Condition) -> str:
    left, right = _operand_shape(condition.left), _operand_shape(condition.right)
    op = ">=" if condition.op in (">", ">=") else "<="
    keys = ((condition.left.kind == "value", left), (condition.right.kind == "value", right))
    if keys[0] > keys[1] or (keys[0] == keys[1] and op == "<="):
        left, right = right, left
        op = "<=" if op == ">=" else ">="
    return f"{left} {op} {right}"


def shape_digest(spec: Mapping[str, Any]) -> str:
    """Hash of a rule's structure: no name, no history, every number as a hole, ``<`` as ``<=``,
    a constant on the right, conditions sorted. Thirty RSI thresholds are one shape."""
    parsed = _parsed(spec)
    shape = {
        "long_when": sorted(_condition_shape(c) for c in parsed.long_when),
        "short_when": sorted(_condition_shape(c) for c in parsed.short_when),
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


def _operand_words(operand: Operand) -> str:
    if operand.kind == "value":
        return _number(float(operand.value or 0.0))
    if operand.kind == "source":
        return f"{operand.source} {operand.lag} bars ago" if operand.lag else str(operand.source)
    name = _NAMES[str(operand.indicator)]
    text = f"{name}({', '.join(_number(p) for p in operand.params)})"
    return f"{text} {operand.field}" if operand.field else text


def rule_words(spec: Mapping[str, Any]) -> str:
    """The rule in plain words, for readers; it states the rule and nothing about its worth."""
    conditions = " and ".join(
        f"{_operand_words(c.left)} {c.op} {_operand_words(c.right)}"
        for c in _parsed(spec).long_when
    )
    return f"Long while {conditions}, flat otherwise."


def _flat_numbers(spec: Mapping[str, Any]) -> dict[str, float]:
    numbers: dict[str, float] = {}
    for side in ("long_when", "short_when"):
        for index, condition in enumerate(spec[side]):
            for end in ("left", "right"):
                operand = condition[end]
                where = f"{side}[{index}].{end}"
                if "value" in operand:
                    numbers[f"{where}.value"] = float(operand["value"])
                elif operand.get("lag"):
                    numbers[f"{where}.lag"] = float(operand["lag"])
                for j, param in enumerate(operand.get("params", [])):
                    numbers[f"{where}.params[{j}]"] = float(param)
    return numbers


class OwnerRule(BaseModel):
    """``rule = {kind = "owner", spec = {...RuleSpec...}}``: the rule language, long/flat only."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    kind: Literal["owner"]
    spec: dict[str, Any]

    @field_validator("spec", mode="before")
    @classmethod
    def _canonical(cls, value: object) -> dict[str, Any]:
        return canonical_spec(value)

    @property
    def strategy(self) -> str:
        return "rules"

    @property
    def params(self) -> dict[str, float]:
        return _flat_numbers(self.spec)

    @property
    def family_key(self) -> str:
        return f"owner:{shape_digest(self.spec)[:12]}"

    @property
    def default_name(self) -> str:
        return f"owner-{shape_digest(self.spec)[:8]}"

    @property
    def labels(self) -> tuple[str, ...]:
        reads_range = any(
            operand.kind == "source"
            and operand.source in {"high", "low"}
            or operand.indicator in _READS_RANGE
            for operand in _parsed(self.spec).operands
        )
        return (NULL_CLOSES,) if reads_range else ()

    @property
    def words(self) -> str:
        return rule_words(self.spec)

    @property
    def rules_json(self) -> str:
        """The exact bytes the engine's ``RunSpec.rules_spec`` carries."""
        return canonical_json(_parsed(self.spec))


def manifest_fields(rule: object) -> dict[str, str]:
    """Extra words stored with a run of an owner rule; nothing for the three old kinds."""
    if isinstance(rule, OwnerRule):
        return {"family": rule.family_key, "rule_words": rule.words}
    return {}
