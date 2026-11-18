"""Closed, recorded-only RD-Agent responses; absent facts retain an explicit reason."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

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


class RdAgentIdea(StrictModel):
    id: str
    round: RecordedFact
    round_kind: Literal["evaluation", "loop", "unknown"]
    name: RecordedFact
    description: RecordedFact
    direction: RecordedFact
    clock: RecordedFact
    reason: RecordedFact
    system_statuses: list[str]
    refusal: RecordedFact
    feedback: RecordedFact
    feedback_scope: Literal["round", "unknown"]
    trial: RdAgentFactor | None
    stages: dict[str, bool | None]
    labels: list[str]
    code_file: RecordedFact
    raw: str


class RdAgentStory(StrictModel):
    ideas: list[RdAgentIdea]
    journey: dict[str, RecordedFact]
    missing_links: list[str]
    ending: str
    ending_reason: RecordedFact
    minutes: RecordedFact
    events: list[str] = Field(default_factory=list)


class JourneyIdea(StrictModel):
    id: str
    iteration: int | None
    name: str
    verdict: str | None
    built: bool


class JourneyMissing(StrictModel):
    reason: Literal["Journey not built yet"] = "Journey not built yet"
    command: str


class JourneyNumber(StrictModel):
    model_config = ConfigDict(allow_inf_nan=False)
    value: int | float | None = None
    display: str | None = None
    label: str | None = None
    gloss: str | None = None


class JourneyStep(StrictModel):
    title: str | None = None
    who: Literal["RD-Agent (AI)", "ALPHA rule"] | None = None
    text: str | None = None
    numbers: list[JourneyNumber] = Field(default_factory=list)
    what_this_means: str | None = None
    figure: str | None = None
    figure_reason: str | None = None
    figures: list[str] = Field(default_factory=list)
    source: list[str] = Field(default_factory=list)
    own_words: str | None = None
    code: str | None = None
    file: str | None = None
    facts: list[str] = Field(default_factory=list)


class JourneyFigure(StrictModel):
    file: str | None = None
    data: str | None = None
    reason: str | None = None
    source: list[str] = Field(default_factory=list)


class StoredJourney(StrictModel):
    iteration: int
    name: str
    code_sha256: str
    steps: list[JourneyStep] = Field(min_length=7, max_length=7)
    figures: dict[str, JourneyFigure] = Field(default_factory=dict)


class RdAgentDetail(StrictModel):
    journeys: list[JourneyIdea] = Field(default_factory=list)
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
    story: RdAgentStory | None = None
