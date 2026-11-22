"""A chart-pattern event as a Setup Lab condition (`series@SELF`), on synthetic bars."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import pattern_events, setup_cmds
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.setup_recheck import recheck_study
from alpha_cli.spine.setup_study import run_study
from alpha_cli.spine.setup_trade import run_trade
from tests.unit.test_setup_context_find import seed_bars

SPEC = """[setup]
name = "Swing low seen"
idea = "Every time a swing low was confirmed"
timeframe = "1D"
assets = ["SPY"]
event = "low_seen == 1"
[context]
low_seen = "swing_low@SELF"
[exit]
time_bars = 10
[study]
horizons = [1, 5]
primary = 5
"""


@pytest.fixture(autouse=True)
def _no_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda rows, **kw: b"png")


def find(home: Path, text: str = SPEC) -> dict[str, Any]:
    path = home / "spec.toml"
    path.write_text(text)
    return setup_cmds.run_find(path, home=home)


def test_a_pattern_event_is_a_find_condition_with_honest_counts(tmp_path: Path) -> None:
    seed_bars(tmp_path)
    result = find(tmp_path)
    info = result["assets"][0]["context"]
    assert info["recipe"] == pattern_events.RECIPE
    assert info["series"] == {"low_seen": "swing_low@SELF"}
    assert info["null_by_reason"]["low_seen"] == {"series-warm-up": pattern_events.WARMUP}
    assert info["conditions"]["event"]["true_bars"] > 0
    assert result["totals"]["events"] == info["conditions"]["event"]["true_bars"]
    assert "short-context-history" not in result["labels"]


def test_the_event_bar_is_never_before_its_confirmation(tmp_path: Path) -> None:
    seed_bars(tmp_path)
    result = find(tmp_path)
    frame = pl.read_parquet(Path(result["folder"]) / "candidates.parquet")
    assert frame.height > 0
    bars = pl.read_parquet(next((tmp_path / "store").rglob("*.parquet")))
    closes = bars["ts"].to_list()
    from alpha_patterns import find_swings

    from alpha_cli.chart_cmds import to_ohlcv
    from alpha_core import Bar

    series = to_ohlcv(
        [
            Bar(symbol="SPY", ts=r["ts"], open=r["open"], high=r["high"], low=r["low"],
                close=r["close"], volume=r["volume"])
            for r in bars.iter_rows(named=True)
        ]
    )
    confirmed = {closes[s.confirmed_index] for s in find_swings(series, lookback=5, kind="low")}
    assert set(frame["event_ts"].to_list()) <= confirmed


def test_study_trade_and_recheck_work_on_a_pattern_condition(tmp_path: Path) -> None:
    seed_bars(tmp_path)
    found = find(tmp_path)
    study = run_study(found["find_id"], home=tmp_path)
    assert study["context"]["SPY"]["recipe"] == pattern_events.RECIPE
    assert recheck_study(found["find_id"], home=tmp_path)["recheck"]["match"] is True
    assert "reading" in run_trade(found["find_id"], home=tmp_path)


def test_an_unknown_pattern_series_fails_loud_with_the_names(tmp_path: Path) -> None:
    seed_bars(tmp_path)
    with pytest.raises(SpineError) as caught:
        find(tmp_path, SPEC.replace("swing_low@SELF", "swing_lows@SELF"))
    assert caught.value.payload["code"] == "SPEC_INVALID"
    assert "hs_top" in str(caught.value.payload)
    assert "cot_nc_net_oi" in str(caught.value.payload)
