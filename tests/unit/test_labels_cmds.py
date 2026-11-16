"""The factor join behind `alpha labels importance` (no worker needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_cli.labels_cmds import _factor_table

START = datetime(2024, 1, 1, tzinfo=UTC)


def _folders(tmp_path: Path, n: int = 40) -> tuple[Path, Path, pl.Series]:
    parent, staging = tmp_path / "parent", tmp_path / "staging"
    parent.mkdir()
    staging.mkdir()
    ts = pl.Series([START + timedelta(days=i) for i in range(n)], dtype=pl.Datetime("us", "UTC"))
    pos = list(range(0, n, 2))
    pl.DataFrame({
        "ts": ts.gather(pos), "pos": pos, "end_pos": [p + 1 for p in pos],
        "meta_label": [float(i % 2) for i in range(len(pos))],
    }).write_parquet(parent / "events.parquet")  # fmt: skip
    weights = {"start": ts.gather(pos), "end": ts.gather([p + 1 for p in pos])}
    pl.DataFrame({**weights, "avg_uniqueness": [1.0] * len(pos)}).write_parquet(
        staging / "weights.parquet"
    )
    return parent, staging, ts


def _factors(ts: pl.Series, path: Path, **columns: list[float | None]) -> Path:
    pl.DataFrame({"ts": ts, **columns}).write_parquet(path)
    return path


def test_every_decided_event_must_find_its_factor_row(tmp_path: Path) -> None:
    parent, staging, ts = _folders(tmp_path)
    half = _factors(ts.head(20), tmp_path / "half.parquet", f=[1.0 * i for i in range(20)])
    with pytest.raises(ValueError, match="10 of 20 events"):
        _factor_table(parent, half, staging)
    gaps = [None if i % 3 == 0 else float(i) for i in range(40)]
    with pytest.raises(ValueError, match="of 20 events"):
        _factor_table(parent, _factors(ts, tmp_path / "gaps.parquet", f=gaps), staging)


def test_shifted_or_naive_local_times_fail_with_the_match_count(tmp_path: Path) -> None:
    parent, staging, ts = _folders(tmp_path)
    shifted = ts.dt.offset_by("5h")
    with pytest.raises(ValueError, match="0 of 20 events"):
        _factor_table(parent, _factors(shifted, tmp_path / "s.parquet", f=[1.0] * 40), staging)


def test_an_unsorted_factor_file_is_accepted_and_rows_stay_in_time_order(tmp_path: Path) -> None:
    parent, staging, ts = _folders(tmp_path)
    frame = pl.DataFrame({"ts": ts, "f": [float(i) for i in range(40)]}).sample(
        fraction=1.0, shuffle=True, seed=3
    )
    frame.write_parquet(tmp_path / "shuffled.parquet")
    path, names = _factor_table(parent, tmp_path / "shuffled.parquet", staging)
    table = pl.read_parquet(path)
    assert names == ["f"] and table.height == 20
    assert table["start"].to_list() == sorted(table["start"].to_list())
    assert table["f"].to_list() == [float(p) for p in table["start"].to_list()]
