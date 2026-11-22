"""The Overview's recent tests: stored run facts with a sparkline."""

from __future__ import annotations

from ._base import StrictModel


class RecentRun(StrictModel):
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


class RecentRunList(StrictModel):
    total: int
    items: list[RecentRun]
