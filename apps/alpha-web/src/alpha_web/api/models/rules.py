"""Rules."""

from __future__ import annotations

from typing import Any, Literal

from ._base import StrictModel


class RuleSummary(StrictModel):
    name: str
    path: str
    sha256: str | None = None
    spec_name: str | None = None
    history: int | None = None
    warmup: int | None = None
    long_conditions: list[str] | None = None
    short_conditions: list[str] | None = None
    spec: dict[str, Any] | None = None
    error: str | None = None


class RuleList(StrictModel):
    rules: list[RuleSummary]
    authority: Literal["none"]
