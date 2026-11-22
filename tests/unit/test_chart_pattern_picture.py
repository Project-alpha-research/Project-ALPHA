"""`alpha chart overlays -p <pattern>` also writes a picture and prints a plain summary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.chart_cmds import ALL_PATTERNS, chart_app, parse_picture_pattern
from alpha_cli.chart_pattern_picture import PatternPicture, draw_pattern_pictures
from alpha_cli.pattern_events import FAMILIES, VISIBLE_ONLY
from alpha_core import Bar, DataError
from alpha_patterns import geometric_brownian_series

PNG = b"\x89PNG"


def _bars(n: int = 900, seed: int = 11) -> list[Bar]:
    s = geometric_brownian_series(n, start=100.0, vol_per_bar=0.02, seed=seed, symbol="ZZ")
    start = datetime(2021, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol="ZZ",
            ts=start + timedelta(days=i),
            open=float(s.open[i]),
            high=float(s.high[i]),
            low=float(s.low[i]),
            close=float(s.close[i]),
            volume=1000.0,
        )
        for i in range(n)
    ]


def test_every_family_is_offered() -> None:
    offered = set(ALL_PATTERNS)
    assert set(FAMILIES) <= offered
    assert set(VISIBLE_ONLY) <= offered
    for name in offered:
        assert parse_picture_pattern(name) == name


def test_unknown_pattern_error_lists_every_family() -> None:
    with pytest.raises(DataError) as err:
        parse_picture_pattern("nope")
    for name in ALL_PATTERNS:
        assert name in str(err.value)


@pytest.mark.parametrize("pattern", sorted(ALL_PATTERNS))
def test_picture_pair_is_written(tmp_path: Path, pattern: str) -> None:
    out = draw_pattern_pictures(_bars(), pattern, since=None, out_dir=tmp_path)
    assert isinstance(out, PatternPicture)
    assert out.plain.read_bytes()[:4] == PNG
    assert out.annotated.read_bytes()[:4] == PNG
    assert out.plain != out.annotated
    lines = out.summary.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith(f"Found {out.count} ")


def test_default_window_is_the_last_two_years(tmp_path: Path) -> None:
    out = draw_pattern_pictures(_bars(), "swings", since=None, out_dir=tmp_path)
    assert out.window_end == date(2021, 1, 1) + timedelta(days=899)
    assert out.window_start == out.window_end - timedelta(days=730)
    assert out.count > 0
    assert "Most recent" in out.summary


def test_chosen_window_limits_the_count(tmp_path: Path) -> None:
    whole = draw_pattern_pictures(_bars(), "swings", since=date(2021, 1, 1), out_dir=tmp_path)
    short = draw_pattern_pictures(_bars(), "swings", since=date(2023, 4, 1), out_dir=tmp_path)
    assert 0 < short.count < whole.count


def test_a_pattern_never_found_says_so_plainly(tmp_path: Path) -> None:
    flat = [
        b.model_copy(update={"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0})
        for b in _bars(200)
    ]
    out = draw_pattern_pictures(flat, "head_shoulders", since=None, out_dir=tmp_path)
    assert out.count == 0
    assert out.summary.splitlines()[1] == "No event in this window."


def test_the_same_bars_give_the_same_picture_bytes(tmp_path: Path) -> None:
    a = draw_pattern_pictures(_bars(), "swings", since=None, out_dir=tmp_path / "a")
    b = draw_pattern_pictures(_bars(), "swings", since=None, out_dir=tmp_path / "b")
    assert a.plain.read_bytes() == b.plain.read_bytes()
    assert a.annotated.read_bytes() == b.annotated.read_bytes()


def test_a_tangle_of_lines_is_not_drawn() -> None:
    from alpha_cli.chart_cmds import to_ohlcv
    from alpha_cli.chart_pattern_picture import MAX_DRAWN, _figure, _shapes

    series = to_ohlcv(_bars())
    shapes = _shapes(series, "trendlines")
    assert len(shapes) > MAX_DRAWN
    window = (date(2021, 1, 1), date(2023, 6, 18))
    figure = _figure(series, shapes, "trendlines", window, annotated=True)
    legend = figure.axes[0].get_legend()
    assert legend is not None
    numbered = [t for t in legend.get_texts() if t.get_text()[:1].isdigit()]
    assert 0 < len(numbered) <= MAX_DRAWN


def test_help_lists_every_pattern() -> None:
    result = CliRunner().invoke(chart_app, ["overlays", "--help"], terminal_width=400)
    flat = " ".join(result.output.split())
    for name in ALL_PATTERNS:
        assert name in flat
