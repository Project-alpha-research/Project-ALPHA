"""Closed, recorded-only RD-Agent responses; absent facts retain an explicit reason."""

from __future__ import annotations

from pydantic import ConfigDict

from alpha_web.api.models import StrictModel


class RecordedFact(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    value: str | int | float | bool | list[str] | None
    reason: str | None = None
    basis: str | None = None


class RdAgentRun(StrictModel):
    run_id: str
    folder: str
    started_at: RecordedFact
    ended_at: RecordedFact
    outcome: RecordedFact
    rounds_completed: RecordedFact
    counted_calls: RecordedFact
    local_embedding_calls: RecordedFact
    provider_embedding_calls: RecordedFact
    cost_usd: RecordedFact
    factors_proposed: RecordedFact
    stages: dict[str, RecordedFact]
    universe_size: RecordedFact
    universe_includes_delisted: RecordedFact


class RdAgentRunList(StrictModel):
    items: list[RdAgentRun]
    reason: str | None = None
    ledger_reason: str | None = None


class RdAgentCap(StrictModel):
    used: RecordedFact
    limit: RecordedFact


class RdAgentClock(StrictModel):
    figures: dict[str, RecordedFact]
    screen: dict[str, RecordedFact]
    spread: dict[str, RecordedFact]
    replay: dict[str, RecordedFact]
    deflation: dict[str, RecordedFact]
    family_deflation: dict[str, RecordedFact]


class RdAgentFactor(StrictModel):
    name: RecordedFact
    description: RecordedFact
    idea_families: RecordedFact
    status: str
    sentence: str
    failure_reason: RecordedFact
    figures: dict[str, RecordedFact]
    clocks: dict[str, RdAgentClock]


class RdAgentDetail(StrictModel):
    run: RdAgentRun
    funnel: dict[str, RecordedFact]
    factors: list[RdAgentFactor]
    factor_reason: str | None = None
    refusals: list[dict[str, RecordedFact]]
    refusal_reason: str | None = None
    timing: list[dict[str, RecordedFact]]
    timing_reason: str | None = None
    caps: dict[str, RdAgentCap]
    months: dict[str, dict[str, RecordedFact]]
    cache: dict[str, RecordedFact]
    providers: dict[str, RecordedFact]
    universe: dict[str, RecordedFact]
    identity_splits: list[dict[str, RecordedFact]]
    identity_rescales: list[dict[str, RecordedFact]]
    notes: list[str]
