"""The Market overview: stored bars summarised per asset. A display, not a research result."""

from __future__ import annotations

from typing import Literal

from ._base import StrictModel


class MarketAsset(StrictModel):
    asset: str
    last_close: float
    change_1_pct: float
    change_7_pct: float
    change_window_pct: float
    last_volume: float
    volume_vs_median: float | None
    median_traded_value: float
    series: list[float]
    series_ts: list[int]
    last_bar: str
    bar_count: int


class MarketTooFewBars(StrictModel):
    asset: str
    bar_count: int
    needed: int


class MarketUnreadable(StrictModel):
    asset: str
    reason: str


class MarketOverview(StrictModel):
    store: str
    available_stores: list[str]
    bar_unit: Literal["day", "bar"]
    window: int
    limit: int
    assets_in_store: int
    assets_scanned: int
    scan_cap: int
    bars_cap: int
    eligible_assets: int
    data_to: str | None
    assets: list[MarketAsset]
    too_few_bars: list[MarketTooFewBars]
    unreadable: list[MarketUnreadable]
    generated_at: str
