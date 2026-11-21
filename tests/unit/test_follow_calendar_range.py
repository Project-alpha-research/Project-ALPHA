"""`follow update` asks the market calendar only about the forward window, and says so in plain
words when the calendar cannot answer. Synthetic store: daily bars from 1995, a follow from 2026."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_cli import follow_source, follow_store, follow_update
from alpha_cli.spine.errors import SpineError
from alpha_data.store import ParquetStore
from tests.fixtures.follow_fixtures import F0, World

OLD_FIRST = date(1995, 1, 2)


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


def test_a_store_from_1995_updates_a_follow_started_in_2026(tmp_path: Path) -> None:
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
            world.home, follow, clock=lambda: datetime(2040, 1, 2, 12, tzinfo=UTC)
        )
    text = str(caught.value)
    assert "XNYS has no sessions for" in text
    # the calendar library starts 20 years before today, so the first day moves each day
    assert f"supported range {follow_source.calendar_range('XNYS')[0]} to" in text
    assert caught.value.payload["code"] == "FOLLOW_CALENDAR_RANGE"


def test_a_session_before_the_calendar_gives_the_same_plain_words_error() -> None:
    with pytest.raises(SpineError) as caught:
        follow_update.close_of("XNYS", date(1999, 3, 1))
    assert "XNYS has no sessions for 1999-03-01" in str(caught.value)
    with pytest.raises(SpineError):
        follow_update.next_open("XNYS", date(1999, 3, 1))


def test_a_session_after_the_calendar_gives_the_same_plain_words_error() -> None:
    with pytest.raises(SpineError) as caught:
        follow_update.next_open("XNYS", date(2040, 3, 1))
    assert caught.value.payload["code"] == "FOLLOW_CALENDAR_RANGE"
    assert date.today().year - follow_source.calendar_range("XNYS")[0].year in {19, 20, 21}
