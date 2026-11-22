"""The data-health block covers the rows a test may read; held-back rows are only stated."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_cli.spine.data_health import run_health_record
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.stores import resolve_asset
from alpha_data.store import ParquetStore

DAYS = [
    date(2023, 12, 22),
    date(2023, 12, 26),
    date(2023, 12, 27),
    date(2023, 12, 28),
    date(2023, 12, 29),
    date(2024, 1, 2),
    date(2024, 1, 3),
    date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 8),
]


def _home(root: Path, spike: date) -> Path:
    """Flat bars at 100 with one price spike that reverses on the next bar, on ``spike``."""
    closes = [150.0 if day == spike else 100.0 + 0.3 * (i % 3) for i, day in enumerate(DAYS)]
    store = ParquetStore(root / "store")
    store.write_bars(
        "ABC",
        pl.DataFrame(
            {
                "ts": [datetime.combine(day, datetime.min.time(), tzinfo=UTC) for day in DAYS],
                "open": closes,
                "high": [c + 1 for c in closes],
                "low": [c - 1 for c in closes],
                "close": closes,
                "volume": [1000.0 + i for i in range(len(DAYS))],
            }
        ),
    )
    store.write_provenance("ABC", source="alpaca", adapter_version="1", parser_version="1")
    return root


def _record(root: Path, **kwargs: str) -> dict[str, object]:
    asset = resolve_asset("ABC", data_dir=root)
    return run_health_record(
        [asset], check_data=True, report_time=datetime(2024, 1, 10, tzinfo=UTC), **kwargs
    )


def test_a_bad_row_after_the_boundary_does_not_block_and_is_stated(tmp_path: Path) -> None:
    record = _record(_home(tmp_path, date(2024, 1, 4)))
    assert record["verdict"] == "pass"
    assert re.search(r"\d+ problems? in held-back rows, not used\.", str(record["sentence"]))


def test_a_bad_row_before_the_boundary_still_blocks(tmp_path: Path) -> None:
    with pytest.raises(SpineError) as stopped:
        _record(_home(tmp_path, date(2023, 12, 27)))
    assert stopped.value.payload["code"] == "DATA_HEALTH_FAILED"
    assert "2023-12-27" in str(stopped.value)
    # The override still works as before.
    assert _record(_home(tmp_path, date(2023, 12, 27)), accept_bad_data="checked")["verdict"] == (
        "fail"
    )
