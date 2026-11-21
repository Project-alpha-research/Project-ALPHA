"""Frozen daily setup specifications; validation does not simulate exits."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from alpha_core import DataError
from alpha_study.setup.context import check_aliases
from alpha_study.setup.expr import Aliases, Kind, compile_expr

RESERVED = frozenset({"warm-up", "no-trigger", "no-next-bar", "pending-trigger"})

PositiveInt = Annotated[int, Field(strict=True, ge=1)]
Text = Annotated[str, Field(strict=True, min_length=1)]


def _expression(text: str, kind: Kind, aliases: Aliases = frozenset()) -> str:
    if compile_expr(text, aliases).kind != kind:
        raise DataError(f"{text!r}: expected {kind} expression")
    return text


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _keys(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            for key in value:
                if key in {"dates", "session"}:
                    raise ValueError(f"{key}: supported in the next piece")
                if key not in cls.model_fields:
                    raise ValueError(
                        f"{key!r}: unknown key; known keys: {', '.join(cls.model_fields)}"
                    )
        return value


class Setup(_Frozen):
    name: Text
    idea: Text
    assets: tuple[Text, ...] = Field(min_length=1)
    timeframe: Literal["1D"]
    event: Text  # checked by SetupSpec, which knows the context aliases


class Trigger(_Frozen):
    when: Text
    within: Annotated[int, Field(strict=True, ge=0)]


@dataclass(frozen=True)
class ExitValue:
    kind: Literal["atr", "percent", "level"]
    multiplier: float | None = None
    period: int | None = None
    level: str | None = None


def parse_exit(text: str) -> ExitValue:
    """Validate an ATR distance, percentage distance or numeric level expression."""
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+(atr\((\d+)\)|%)\s*", text
    )
    if match:
        multiplier = float(match[1])
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise DataError(f"{text!r}: exit distance must be positive and finite")
        if match[3] is not None:
            period = int(match[3])
            compile_expr(f"atr({period})")
            return ExitValue("atr", multiplier, period)
        return ExitValue("percent", multiplier)
    return ExitValue("level", level=_expression(text, "number"))


class Exit(_Frozen):
    # The default spelling must serialize exactly like a pre-direction spec.
    direction: Literal["long", "short"] = Field("long", exclude_if=lambda side: side == "long")
    time_bars: PositiveInt | None = None
    stop: Text | None = None
    target: Text | None = None
    opposite: Text | None = None

    @field_validator("stop", "target")
    @classmethod
    def _distance(cls, value: str | None) -> str | None:
        if value is not None:
            parse_exit(value)
        return value

    @field_validator("opposite")
    @classmethod
    def _opposite(cls, value: str | None) -> str | None:
        return _expression(value, "boolean") if value is not None else None


class Study(_Frozen):
    horizons: tuple[PositiveInt, ...] = Field(min_length=1)
    primary: PositiveInt

    @model_validator(mode="after")
    def _primary(self) -> Self:
        if self.primary not in self.horizons:
            raise ValueError("study.primary must be one of horizons")
        return self


class SetupSpec(_Frozen):
    """Identity ignores key order everywhere except `[filters]`, whose order is hashed."""

    setup: Setup
    filters: Mapping[str, str] = Field(default_factory=dict)
    trigger: Trigger | None = None
    reference: Mapping[str, str] = Field(default_factory=dict)
    exit: Exit | None = None
    study: Study | None = None
    # alias -> "series@key". Part of the identity only when present, so a spec without it keeps
    # its old bytes and ids.
    context: Mapping[str, str] = Field(default_factory=dict, exclude_if=lambda value: not value)
    # A link to an idea card. Excluded from dumps, so it is in no hash and no stored spec.
    idea_card: str = Field(default="", exclude=True)

    @field_validator("filters", "reference", mode="after")
    @classmethod
    def _freeze(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        if any(not key.strip() for key in value):
            raise ValueError("filter/reference names must not be empty")
        if clash := RESERVED.intersection(value):
            raise ValueError(f"{sorted(clash)}: reserved for built-in rejection reasons")
        return MappingProxyType(dict(value))

    @model_validator(mode="after")
    def _expressions(self) -> Self:
        check_aliases(self.context, [*self.filters, *self.reference])
        names = frozenset(self.context)
        _expression(self.setup.event, "boolean", names)
        if self.trigger is not None:
            _expression(self.trigger.when, "boolean", names)
        for text in self.filters.values():
            _expression(text, "boolean", names)
        for text in self.reference.values():
            _expression(text, "number", names)
        # Defaults must be immutable too, without sharing a mutable empty dictionary.
        for name in ("filters", "reference", "context"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        return self

    @field_serializer("filters", "reference", "context")
    def _mapping(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    @property
    def spec_sha256(self) -> str:
        # Filter order decides the rejection reason, so it is part of the identity:
        # filters are hashed as an ordered list of [name, expression] pairs.
        payload = self.model_dump(mode="json")
        payload["filters"] = [[name, text] for name, text in self.filters.items()]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def load(cls, source: str | Path | Mapping[str, object]) -> Self:
        """Load a dict, .toml file or .json file; unknown suffixes fail loud."""
        if isinstance(source, Mapping):
            return cls.model_validate(source)
        path = Path(source)
        if path.suffix.lower() not in {".toml", ".json"}:
            raise DataError(f"{path}: allowed suffix .toml or .json")
        with path.open("rb") as stream:
            data = tomllib.load(stream) if path.suffix.lower() == ".toml" else json.load(stream)
        return cls.model_validate(data)
