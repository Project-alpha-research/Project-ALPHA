"""Hand-built fills, frozen causal levels and occupancy."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from alpha_cli.spine.setup_exits import MAX_HOLD_BARS, prepare_exits, simulate, trade_candidates
from alpha_study.setup.spec import SetupSpec


def spec(**exits: Any) -> SetupSpec:
    return SetupSpec.load(
        dict(
            setup=dict(name="Test", idea="Test", assets=["X"], timeframe="1D", event="close > 0"),
            exit=exits,
        )
    )


def bars(values: Sequence[tuple[float, float, float, float]]) -> list[Any]:
    from types import SimpleNamespace

    return [
        SimpleNamespace(
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=o,
            high=h,
            low=low,
            close=c,
            volume=1.0,
        )
        for i, (o, h, low, c) in enumerate(values)
    ]


def run(values: Sequence[tuple[float, float, float, float]], **exits: Any) -> dict[str, Any]:
    return simulate(prepare_exits(spec(**exits), bars(values)), 1, 0.0006)


@pytest.mark.parametrize(
    "tail,reason,price,both",
    [
        ([(100, 103, 94, 100)], "stop", 95, 0),
        ([(100, 106, 94, 100)], "stop", 95, 1),
        ([(100, 106, 99, 104)], "target", 105, 0),
        ([(100, 101, 99, 100), (90, 106, 89, 100)], "stop-gap", 90, 1),
        ([(100, 101, 99, 100), (110, 112, 109, 111)], "target", 105, 0),
    ],
)
def test_price_exits(
    tail: list[tuple[float, float, float, float]], reason: str, price: float, both: int
) -> None:
    row = run([(100, 101, 99, 100), *tail], stop="5 %", target="5 %")
    assert row["reason"] == reason
    assert row["exit_price"] == pytest.approx(price)
    assert row["net_return"] == pytest.approx(price / 100 - 1 - 0.0006)
    assert row["r_multiple"] == pytest.approx(row["net_return"] / 0.05)
    assert row["both_touched"] == both


def test_time_opposite_and_open_end() -> None:
    values = [(100, 102, 99, 101), (100, 103, 99, 102), (104, 105, 103, 104)]
    row = run(values, time_bars=1)
    assert row["reason"] == "time" and row["bars_held"] == 1
    assert row["exit_price"] == pytest.approx(102)
    row = run(values, opposite="close > 101", time_bars=1)
    assert row["reason"] == "opposite"
    assert row["exit_price"] == pytest.approx(104)
    assert row["worst_adverse_move"] == pytest.approx(-0.01)
    row = run(values[:2], opposite="close > 101", time_bars=1)
    assert row["reason"] == "open-at-end" and not row["complete"]
    assert run(values, time_bars=10)["reason"] == "open-at-end"
    row = run([values[0]] * (MAX_HOLD_BARS + 2), stop="50 %")
    assert row["reason"] == "max-hold" and row["bars_held"] == MAX_HOLD_BARS


def test_frozen_atr_levels_and_future_poison() -> None:
    values = [(100, 102, 98, 100)] * 4 + [(100, 101, 99, 100)] * 4
    settings = spec(stop="2 atr(2)", target="high", time_bars=1)
    original = simulate(prepare_exits(settings, bars(values)), 4, 0.0006)
    assert original["stop"] == pytest.approx(92)
    assert original["target"] == pytest.approx(102)
    poison = values[:5] + [(200, 500, 1, 400)] * 3
    assert simulate(prepare_exits(settings, bars(poison)), 4, 0.0006) == original
    poison[4] = (100, 500, 1, 400)
    changed = simulate(prepare_exits(settings, bars(poison)), 4, 0.0006)
    assert changed["stop"] == pytest.approx(original["stop"])
    assert changed["target"] == pytest.approx(original["target"])


@pytest.mark.parametrize("exits", [dict(stop="100"), dict(target="100"), dict(stop="atr(2)")])
def test_invalid_levels(exits: dict[str, Any]) -> None:
    row = run([(100, 101, 99, 100)] * 2, **exits)
    assert row["reason"] == "invalid-levels" and not row["complete"]


def test_one_at_a_time_per_asset() -> None:
    series = bars([(100, 101, 99, 100)] * 8)
    prepared = prepare_exits(spec(time_bars=3), series)
    candidates = [
        dict(
            symbol="X",
            candidate_id=i,
            cluster_id=i,
            entry_ts=series[i].ts,
            entry_price=100.0,
            status="accepted",
            cluster_first=True,
        )
        for i in (1, 2, 3, 4)
    ]
    rows = trade_candidates(candidates, {"X": prepared}, {"X": 0.0006})
    assert [r["reason"] for r in rows] == ["time", "skipped-in-trade", "skipped-in-trade", "time"]


def test_target_gap_adverse_move_ends_at_open() -> None:
    row = run(
        [(100, 101, 99, 100), (100, 101, 99, 100), (110, 112, 96, 100)], stop="5 %", target="5 %"
    )
    assert row["reason"] == "target"
    assert row["worst_adverse_move"] == pytest.approx(-0.01)
