"""Research compare report shape (checked by the reserve guard test)."""

from __future__ import annotations

from typing import Literal

from ._base import StrictModel


class ResearchRow(StrictModel):
    strategy: str
    total_return: float | None
    final_equity: float | None = None
    n_trades: int | None = None
    error: str | None


class ResearchReport(StrictModel):
    symbol: str
    n_bars: int
    ranked: list[ResearchRow]
    comparison_status: Literal["preferred", "tie", "no_trades", "not_comparable"]
    preferred_strategy: str | None
    preference_reason: str | None
    # Present only when stored bars from the reserved day on were held back.
    research_cutoff: str | None = None
    reserve: dict[str, str | int] | None = None
    reserve_sentence: str | None = None
