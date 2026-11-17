"""Synthetic UTC settlement boundaries and immutable funding sources."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context.binance_bulk import table_path
from alpha_data.context.events import FUNDING_SCHEMA, store_events


def write_funding(root: Path, symbol: str, rows: Sequence[tuple[str, float, int | None]]) -> Path:
    stamps = [datetime.fromisoformat(row[0]).replace(tzinfo=UTC) for row in rows]
    frame = pl.DataFrame(
        {
            "symbol": [symbol] * len(rows),
            "funding_time": stamps,
            "funding_rate": [row[1] for row in rows],
            "interval_hours": [row[2] for row in rows],
            "known_from": stamps,
        },
        schema=FUNDING_SCHEMA,
    )
    path = table_path(root, "funding", symbol)
    store_events(
        path,
        frame,
        {"source": "binance", "fetched_at": "2023-12-31T00:00:00+00:00"},
        schema=FUNDING_SCHEMA,
    )
    return path


def test_midnight_poison_and_variable_intervals(tmp_path: Path) -> None:
    from alpha_data.context.daily_funding import daily_funding_with_sources

    path = write_funding(
        tmp_path,
        "BTCUSDT",
        [
            ("2023-01-01T08:00:00.008", 0.01, 8),
            ("2023-01-01T12:00:00.008", 0.02, 4),
            ("2023-01-01T14:00:00.008", 0.03, 2),
            ("2023-01-01T16:00:00.008", 0.04, None),
            ("2023-01-02T00:00:00.008", 9.0, 8),
        ],
    )
    frame, sources = daily_funding_with_sources(
        tmp_path, ["BTCUSDT", "NONEUSDT"], date(2023, 1, 1), date(2023, 1, 3)
    )
    assert frame.columns == ["date", "symbol", "funding_sum", "funding_last", "funding_count"]
    assert frame["date"].to_list() == [date(2023, 1, 1), date(2023, 1, 2)]
    assert frame["funding_sum"].to_list() == pytest.approx([0.10, 9.0])
    assert frame["funding_last"].to_list() == [0.04, 9.0]
    assert frame["funding_count"].to_list() == [4, 1]
    assert sources == {"BTCUSDT": hashlib.sha256(path.read_bytes()).hexdigest()}
    # Leaky control: including the next midnight settlement changes the earlier sum.
    assert sum(pl.read_parquet(path)["funding_rate"]) != frame["funding_sum"][0]


def test_every_daily_prefix_is_invariant(tmp_path: Path) -> None:
    from alpha_data.context.daily_funding import daily_funding

    rows = [(f"2023-01-{day:02d}T00:00:00.008", float(day), None) for day in range(1, 5)]
    write_funding(tmp_path / "full", "BTCUSDT", rows)
    full = daily_funding(tmp_path / "full", ["BTCUSDT"], date(2023, 1, 1), date(2023, 1, 4))
    for cut in range(1, 5):
        root = tmp_path / str(cut)
        write_funding(root, "BTCUSDT", rows[:cut])
        truncated = daily_funding(root, ["BTCUSDT"], date(2023, 1, 1), date(2023, 1, cut))
        assert truncated.equals(full.filter(pl.col("date") <= date(2023, 1, cut)))


def test_reserved_rows_refused_even_outside_requested_range(tmp_path: Path) -> None:
    from alpha_data.context.daily_funding import daily_funding

    write_funding(tmp_path, "BTCUSDT", [("2024-01-01T00:00:00.008", 9.0, None)])
    with pytest.raises(DataError, match="reserved"):
        daily_funding(tmp_path, ["BTCUSDT"], date(2023, 1, 1), date(2023, 12, 31))


def test_source_hash_mismatch_fails(tmp_path: Path) -> None:
    from alpha_data.context.daily_funding import daily_funding

    path = write_funding(tmp_path, "BTCUSDT", [("2023-01-01T00:00:00.008", 0.01, None)])
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(DataError, match="sha256"):
        daily_funding(tmp_path, ["BTCUSDT"], date(2023, 1, 1), date(2023, 1, 2))
