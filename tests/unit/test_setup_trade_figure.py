"""Deterministic presentation of completed trades and controls."""

from io import BytesIO

from PIL import Image

from alpha_cli.spine.setup_trade_figure import draw_trades
from alpha_research.figures.theme import load_theme


def test_identical_bytes_and_dimensions() -> None:
    rows = [
        dict(entry_ts=i, asset="X", candidate_id=i, net_return=v, reason=reason, complete=True)
        for i, (v, reason) in enumerate(
            [(-0.05, "stop"), (0.1, "target"), (0.02, "time"), (-0.02, "opposite")]
        )
    ]
    primary = dict(
        mean=0.0125,
        drift_mean=0.001,
        random_date_5=-0.02,
        random_date_95=0.03,
        trades=4,
        hit_rate=0.5,
    )
    first = draw_trades(
        rows=rows,
        primary=primary,
        theme=load_theme(),
        title="Synthetic: 4 trades from 4 separate occurrences",
    )
    assert first == draw_trades(
        rows=rows,
        primary=primary,
        theme=load_theme(),
        title="Synthetic: 4 trades from 4 separate occurrences",
    )
    assert Image.open(BytesIO(first)).size == (1600, 900)


def test_year_ticks_mark_first_trade_of_each_year_and_thin_out() -> None:
    from datetime import UTC, datetime

    from alpha_cli.spine.setup_trade_figure import _year_ticks

    stamps = [datetime(2000 + i // 2, 1, 1 + i % 2, tzinfo=UTC) for i in range(60)]
    ticks = _year_ticks(stamps)
    assert ticks[0] == (0, "2000") and len(ticks) <= 12
    assert all(stamps[i].year == int(label) for i, label in ticks)
    assert _year_ticks([1, 2]) == []


def test_open_at_end_is_shown_separately_from_completed_mean() -> None:
    primary = dict(
        mean=None, drift_mean=None, random_date_5=None, random_date_95=None, trades=0, hit_rate=None
    )
    marked = [
        dict(
            entry_ts=1,
            asset="X",
            candidate_id=1,
            net_return=-0.03,
            reason="open-at-end",
            complete=False,
        )
    ]
    empty = draw_trades(rows=[], primary=primary, theme=load_theme(), title="Open")
    assert draw_trades(rows=marked, primary=primary, theme=load_theme(), title="Open") != empty
