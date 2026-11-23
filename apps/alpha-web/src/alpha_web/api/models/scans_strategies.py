"""Strategy definitions."""

from __future__ import annotations

from ._base import StrictModel


class ParamDefinition(StrictModel):
    name: str
    type: str
    default: float
    min: float | None
    max: float | None
    min_exclusive: bool
    max_exclusive: bool
    help: str


class StrategyDefinition(StrictModel):
    name: str
    params: list[ParamDefinition]
    has_tier1_surrogate: bool
