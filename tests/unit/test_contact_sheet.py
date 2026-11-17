"""Drawing receives only pre-entry candles and the entry open."""

import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli.spine.contact_sheet import Panel, draw_sheet
from alpha_cli.spine.setup_find import panel_window, sample_rejected
from alpha_research.figures.theme import load_theme
from tests.unit.test_setup_find import spec_file, worked_store


def candidate(tmp_path: Path) -> tuple[pl.DataFrame, dict[str, Any]]:
    from alpha_study.setup.evaluate import find_candidates
    from alpha_study.setup.spec import SetupSpec

    frame = worked_store(tmp_path)
    spec = SetupSpec.load(spec_file(tmp_path, worked=True))
    row = find_candidates(spec, frame, symbol="SPY").row(0, named=True)
    return frame, row


def png(panel: Panel) -> bytes:
    return draw_sheet([panel], title="Synthetic", footer="Entry open only", theme=load_theme())


def test_outcome_blindness_dimensions_and_determinism(tmp_path: Path) -> None:
    frame, row = candidate(tmp_path)
    panel = panel_window(frame, row, 5, mode="accepted")
    assert len(panel.candles) == 7  # event 10, trigger 11; starts at 5
    assert panel.event_x == 0 and panel.trigger_x == 1
    assert panel.entry_x == 2 and panel.entry_price == 100.0
    changed = (
        frame.with_row_index("i")
        .with_columns(
            pl.when(pl.col("i") > 11).then(999999.0).otherwise(pl.col(col)).alias(col)
            for col in ("high", "low", "close", "volume")
        )
        .with_columns(pl.when(pl.col("i") > 12).then(777.0).otherwise(pl.col("open")).alias("open"))
    )
    other = panel_window(changed, row, 5, mode="accepted")
    assert other == panel
    original = png(panel)
    assert png(other) == original == png(panel)
    assert struct.unpack(">II", original[16:24]) == (1600, 1200)
    assert b"Matplotlib" not in original
    # Sensitive control: a candle that is allowed to be seen changes the drawing.
    changed = frame.with_columns((pl.col("high") + 1).alias("high"))
    assert png(panel_window(changed, row, 5, mode="accepted")) != original


@pytest.mark.parametrize("count,expected", [(1, [0]), (4, [0, 1, 2, 3]), (9, [0, 3, 5, 8])])
def test_rejected_sampling(count: int, expected: list[int]) -> None:
    rows: list[dict[str, Any]] = [
        {"reason": "filter", "status": "rejected", "candidate_id": i} for i in range(count)
    ]
    assert [r["candidate_id"] for r in sample_rejected(rows)] == expected
    assert sample_rejected([{"reason": "warm-up", "status": "rejected"}]) == []
    assert sample_rejected([{"reason": "pending-trigger", "status": "pending"}]) == []


@pytest.mark.parametrize("reason,end", [("uptrend", 10), ("no-trigger", 13), ("no-next-bar", 11)])
def test_rejected_boundary(tmp_path: Path, reason: str, end: int) -> None:
    frame, row = candidate(tmp_path)
    row.update(reason=reason, status="rejected", within=3)
    panel = panel_window(frame, row, 5, mode="rejected")
    assert len(panel.candles) == end - 5 + 1
    assert panel.entry_price is None and reason in panel.title


@pytest.mark.parametrize(
    "more,suffix", [(0, "2026-01-02"), (1, "(+1 more day)"), (2, "(+2 more days)")]
)
def test_panel_title_counts_other_days_of_the_cluster(more: int, suffix: str) -> None:
    ts = [datetime(2026, 1, d, tzinfo=UTC) for d in (1, 2, 3)]
    frame = pl.DataFrame(
        {"ts": ts, "open": [1.0] * 3, "high": [2.0] * 3, "low": [0.5] * 3, "close": [1.5] * 3}
    )
    row = dict(
        symbol="SPY",
        candidate_id=7,
        event_ts=ts[1],
        trigger_ts=ts[1],
        entry_price=1.0,
        status="accepted",
        reason=None,
        more_days=more,
    )
    panel = panel_window(frame, row, 5, mode="accepted")
    assert panel.title.startswith("SPY #7 2026-01-02") and panel.title.endswith(suffix)
    assert [c[0] for c in panel.candles] == [-1, 0] and panel.entry_x == 1
