"""`follow update` asks the market calendar only about the forward window, and says so in plain
words when the calendar cannot answer. Synthetic store: daily bars from 1940, a follow from 2026."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_cli import follow_store, follow_update
from alpha_cli.spine.errors import SpineError
from alpha_data.sessions import supported_range
from alpha_data.store import ParquetStore
from tests.fixtures.follow_fixtures import F0, World

OLD_FIRST = date(1940, 1, 2)  # before the widened window: the labelled fallback


def _old_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    day = OLD_FIRST
    while day < date(2026, 6, 1):
        if day.weekday() < 5:
            rows.append(
                {
                    "ts": datetime(day.year, day.month, day.day, tzinfo=UTC),
                    "open": 100.0,
                    "high": 100.0,
                    "low": 100.0,
                    "close": 100.0,
                    "volume": 1000.0,
                }
            )
        day += timedelta(days=1)
    return rows


def _long_world(tmp_path: Path) -> World:
    world = World(tmp_path, -0.2, [3.0, 3.0, 3.0, -8.0])
    frame = pl.DataFrame(_old_rows() + world.rows[: F0 + 2])
    ParquetStore(world.home / "store").write_bars("SPY", frame)
    return world


def test_a_store_from_1940_updates_a_follow_started_in_2026(tmp_path: Path) -> None:
    world = _long_world(tmp_path)
    follow = world.start()
    now = world.close_of(0)
    result = follow_update.update_follow(world.home, follow, clock=lambda: now)
    assert result["status"] == "written"
    assert [row["session"] for row in result["written"]] == ["2026-11-19"]
    assert follow_store.state_of(follow_store.entries_of(world.home, follow)) == "active"


def test_a_clock_beyond_the_calendar_gives_a_plain_words_error(tmp_path: Path) -> None:
    world = _long_world(tmp_path)
    follow = world.start()
    with pytest.raises(SpineError) as caught:
        follow_update.update_follow(
            world.home, follow, clock=lambda: datetime(2100, 1, 2, 12, tzinfo=UTC)
        )
    first, last = supported_range("XNYS")
    text = str(caught.value)
    assert "XNYS cannot answer" in text
    assert f"supported range {first} to {last}" in text
    assert caught.value.payload["code"] == "FOLLOW_CALENDAR_RANGE"


def test_a_session_long_before_today_now_has_a_close() -> None:
    # the library window moves; the project widens it, so an old session still answers
    first, _ = supported_range("XNYS")
    assert follow_update.close_of("XNYS", date(1999, 3, 1)) == datetime(1999, 3, 1, 21, tzinfo=UTC)
    assert follow_update.next_open("XNYS", date(1999, 3, 1)).date() == date(1999, 3, 2)
    assert first <= date(1999, 3, 1)


def test_a_session_after_the_calendar_gives_the_same_plain_words_error() -> None:
    _, last = supported_range("XNYS")
    with pytest.raises(SpineError) as caught:
        follow_update.next_open("XNYS", last)
    assert caught.value.payload["code"] == "FOLLOW_CALENDAR_RANGE"
    with pytest.raises(SpineError):
        follow_update.close_of("XNYS", last + timedelta(days=400))
