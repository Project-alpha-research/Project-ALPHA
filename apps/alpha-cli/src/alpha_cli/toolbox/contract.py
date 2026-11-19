"""The declarative contract for a toolbox entry and its stored reading."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from string import Formatter
from typing import TYPE_CHECKING, Any, Literal

from alpha_cli.toolbox.gates import GATES
from alpha_cli.toolbox.situations import Situation

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

InputKind = Literal[
    "run_returns",
    "run_positions",
    "stored_equity",
    "stored_benchmark",
    "run_trades",
    "run_bars",
    "study_events",
    "factor_panel",
    "run_set",
    "asset_bars",
]
Value = float | str | None


@dataclass(frozen=True)
class Param:
    name: str
    type: type
    default: Any
    allowed: tuple[Any, ...] | range | None
    gloss: str

    def __post_init__(self) -> None:
        if not self.gloss or (self.default is not None and type(self.default) is not self.type):
            raise ValueError(f"invalid parameter {self.name}")
        if self.allowed is not None and self.default not in self.allowed:
            raise ValueError(f"default outside allowed values for {self.name}")


@dataclass(frozen=True)
class Output:
    key: str
    label: str
    gloss: str
    unit: Literal["ratio", "fraction", "count", "p_value", "date", "bps", "currency", "text"]
    legacy_metric: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class Result:
    values: dict[str, Value]
    reasons: dict[str, str]
    series: dict[str, list[Any]] | None = None
    labels: tuple[str, ...] = ()
    figure: str | None = None
    # Preserve the original market reports and their source addresses.
    details: dict[str, Any] = field(default_factory=dict)
    basis: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key, value in self.values.items():
            if value is None and not self.reasons.get(key):
                raise ValueError(f"missing reason for unavailable output {key}")
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError(f"non-finite output {key}")


@dataclass(frozen=True)
class ToolSpec:
    id: str
    question: str
    needs: tuple[InputKind, ...]
    params: tuple[Param, ...]
    outputs: tuple[Output, ...]
    reading: str
    caveats: tuple[str, ...]
    reference: str
    compute: Callable[[Inputs, dict[str, Any], Generator | None], Result] | None
    answers: tuple[str, ...] = ()
    situations: tuple[Situation, ...] = ()
    version: int = 1
    kind: Literal["diagnostic", "test", "control", "gate"] = "diagnostic"
    family: str = "market"
    cost: Literal["instant", "seconds", "minutes"] = "seconds"
    seeded: bool = False
    time_safety: Literal["order_free", "causal", "needs_pit_guard", "hindsight"] = "order_free"
    look: Literal["describe", "test", "search"] = "describe"
    evaluations: Callable[[dict[str, Any]], int] | None = None
    poison_test: str | None = None
    legacy_seed: int | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", self.id) or self.version < 1:
            raise ValueError("invalid tool id or version")
        if self.kind == "gate" and (self.id not in GATES or self.compute or self.params):
            raise ValueError("gate must be frozen, stored and parameter-free")
        if self.look == "search" and self.evaluations is None:
            raise ValueError("search requires evaluations")
        if self.time_safety != "order_free" and not self.poison_test:
            raise ValueError("ordered inputs require a poison test")
        keys = {o.key for o in self.outputs}
        if len(keys) != len(self.outputs) or not all(o.gloss for o in self.outputs):
            raise ValueError("outputs require unique keys and glosses")
        if len({p.name for p in self.params}) != len(self.params):
            raise ValueError("duplicate parameter")
        for _, name, fmt, _ in Formatter().parse(self.reading):
            if name is not None and (name not in keys or "{" in (fmt or "")):
                raise ValueError("reading must reference only stored outputs")

    def render(self, values: dict[str, Value]) -> str:
        if set(values) != {o.key for o in self.outputs}:
            raise ValueError("result keys differ from declared outputs")
        parts = []
        for literal, name, fmt, _ in Formatter().parse(self.reading):
            parts.append(literal)
            if name is not None:
                value = values[name]
                parts.append("unavailable" if value is None else format(value, fmt or ""))
        return "".join(parts)
