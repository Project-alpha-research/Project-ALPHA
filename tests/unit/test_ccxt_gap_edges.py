"""Requested-range coverage must include the edges, with no live-provider calls."""

import sys
from datetime import UTC, datetime, timedelta, tzinfo
from types import SimpleNamespace
from typing import Self

import pytest

from alpha_core import DataError
from alpha_data.adapters.ccxt_adapter import CCXTAdapter

START = datetime(2024, 1, 1, tzinfo=UTC)


def provider(monkeypatch: pytest.MonkeyPatch, stamps: list[datetime]) -> None:
    rows = [[stamp.timestamp() * 1000, 100, 101, 99, 100, 10] for stamp in stamps]
    exchange = SimpleNamespace(
        fetch_ohlcv=lambda *args, **kw: [r for r in rows if r[0] >= kw["since"]]
    )
    monkeypatch.setitem(sys.modules, "ccxt", SimpleNamespace(coinbase=lambda options: exchange))


@pytest.mark.parametrize("edge,indices", [("leading", [2, 3, 4]), ("trailing", [0, 1, 2])])
def test_requested_range_reports_edge_gaps(
    monkeypatch: pytest.MonkeyPatch, edge: str, indices: list[int]
) -> None:
    provider(monkeypatch, [START + timedelta(hours=i) for i in indices])
    with pytest.raises(DataError, match=rf"{edge}.*missing bar start"):
        CCXTAdapter().fetch_timeframe("BTC/USD", START, START + timedelta(hours=4), timeframe="1h")


def test_complete_requested_range_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    provider(monkeypatch, [START + timedelta(hours=i) for i in range(5)])
    assert (
        CCXTAdapter()
        .fetch_timeframe(
            "BTC/USD",
            START,
            START + timedelta(hours=4),
            timeframe="1h",
        )
        .bars.height
        == 5
    )


@pytest.mark.parametrize(
    "start,end,stamps,timeframe",
    [
        (
            START + timedelta(minutes=15),
            START + timedelta(hours=3, minutes=30),
            [START + timedelta(hours=i) for i in range(1, 4)],
            "1h",
        ),
        (
            START + timedelta(hours=21),
            START + timedelta(days=1, hours=7),
            [START + timedelta(hours=i) for i in (21, 24, 31)],
            "7h",
        ),
    ],
)
def test_range_edges_follow_midnight_grid(
    monkeypatch: pytest.MonkeyPatch,
    start: datetime,
    end: datetime,
    stamps: list[datetime],
    timeframe: str,
) -> None:
    provider(monkeypatch, stamps)
    assert CCXTAdapter().fetch_timeframe(
        "BTC/USD", start, end, timeframe=timeframe
    ).bars.height == len(stamps)


def test_live_interval_is_not_a_trailing_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_data.adapters import ccxt_adapter

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls(2024, 1, 1, 4, 30, tzinfo=UTC)

    monkeypatch.setattr(ccxt_adapter, "datetime", Clock)
    provider(monkeypatch, [START + timedelta(hours=i) for i in range(5)])
    assert (
        CCXTAdapter()
        .fetch_timeframe(
            "BTC/USD",
            START,
            START + timedelta(hours=6),
            timeframe="1h",
        )
        .bars.height
        == 4
    )
