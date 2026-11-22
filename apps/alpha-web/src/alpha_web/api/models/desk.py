"""The Workstation desk reads: recent tests with a sparkline, and the frame's status facts."""

from __future__ import annotations

from ._base import StrictModel


class DeskRun(StrictModel):
    run_id: str
    kind: str
    mtime: float
    display_name: str
    symbol: str | None
    idea: str | None
    rule_name: str | None
    first_ts: str | None
    last_ts: str | None
    trades: int | None
    tries: int | None
    oos_sharpe: float | None
    evidence: str | None
    # The stored equity curve thinned for display; empty when the run wrote none.
    spark: list[float]


class DeskRunList(StrictModel):
    total: int
    items: list[DeskRun]


class DeskNightly(StrictModel):
    date: str
    run_number: int | None
    complete: str
    blocking: int
    minor: int
    ready: bool
    reasons: list[str]


class DeskStatus(StrictModel):
    reserved_start: str
    nightly: DeskNightly | None
    nightly_problem: str | None
