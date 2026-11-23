"""The Kronos time estimate comes from a short timed warm-up on this machine, rounded up."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from alpha_cli import _forecast
from alpha_core import Bar


def _bars(count: int) -> list[Bar]:
    first = datetime(2022, 1, 3, tzinfo=UTC)
    return [
        Bar(
            symbol="X",
            ts=first + timedelta(days=i),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1.0,
        )
        for i in range(count)
    ]


class _Stub:
    """Sleeps in proportion to the bars it reads, as Kronos does; the first call also loads."""

    def __init__(self, per_read: float, load: float = 0.0) -> None:
        self.per_read = per_read
        self.load = load
        self.calls = 0

    def forecast(
        self, bars: Sequence[Bar], *, horizon: int, sample_count: int, **_: object
    ) -> object:
        if self.calls == 0:
            time.sleep(self.load)
        self.calls += 1
        reads = sum(min(len(bars) + step, _forecast.MAX_WINDOW) for step in range(horizon))
        time.sleep(reads * sample_count * self.per_read)
        return object()


@pytest.mark.parametrize("per_read", [1e-4, 3e-4])
def test_the_estimate_is_within_thirty_percent_on_a_slower_or_faster_machine(
    per_read: float,
) -> None:
    stub = _Stub(per_read, load=0.05)
    bars = _bars(300)
    expected = _forecast.calibrated_seconds(
        cast(Any, stub), bars, context=120, horizon=6, rows=10, model="kronos"
    )
    started = time.monotonic()
    stub.forecast(bars[-120:], horizon=6, sample_count=10)
    real = time.monotonic() - started + 0.05  # the load the warm-up already paid
    assert 0.7 * real <= expected <= 1.3 * real + 1.0, (expected, real)  # +1: rounded up


def test_the_estimate_is_rounded_up_to_a_whole_second() -> None:
    stub = _Stub(2e-5)
    seconds = _forecast.calibrated_seconds(
        cast(Any, stub), _bars(300), context=120, horizon=12, rows=30, model="kronos"
    )
    assert seconds == int(seconds) and seconds >= 1


def test_the_offline_double_is_never_timed() -> None:
    stub = _Stub(1.0)
    seconds = _forecast.calibrated_seconds(
        cast(Any, stub), _bars(300), context=120, horizon=12, rows=30, model="fake"
    )
    assert stub.calls == 0
    assert seconds == pytest.approx(
        _forecast.estimate_seconds(context=120, horizon=12, rows=30), rel=1e-9, abs=1e-12
    )


def test_minutes_are_rounded_up() -> None:
    assert _forecast.say_time(100.0) == "about 2 minutes"
    assert _forecast.say_time(121.0) == "about 3 minutes"


def _timed(ticks: Any, per_step: Any) -> Any:
    """A stubbed Kronos on a stubbed clock: a batch costs per path, per step, by window size."""

    class Timed:
        calls = 0
        steps: list[int] = []

        def forecast(
            self, bars: Sequence[Bar], *, horizon: int, sample_count: int, **_: object
        ) -> object:
            load = 5.0 if self.calls == 0 else 0.0
            work = sum(per_step(len(bars) + step) for step in range(horizon))
            ticks.now += load + 0.1 + sample_count * work
            self.calls += 1
            self.steps.append(horizon)
            return object()

    return Timed()


class _Ticks:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def _real(per_step: Any, *, context: int, horizon: int, rows: int) -> float:
    ticks = _Ticks()
    stub = _timed(ticks, per_step)
    stub.calls = 1  # loaded
    stub.forecast(_bars(context), horizon=horizon, sample_count=rows)
    return ticks.now + 5.0


@pytest.mark.parametrize("rows", [8, 32, 64])
def test_a_batch_costs_by_its_paths_on_a_cpu(rows: int) -> None:
    """Measured on a desktop CPU: 32 paths in one batch take about four times 8 paths. The
    estimate and the "--paths N" tip both come from one warm-up and the same formula."""
    ticks = _Ticks()
    per_step = lambda window: 1e-3 * window  # noqa: E731
    found = _forecast.calibrate(
        cast(Any, _timed(ticks, per_step)), _bars(300), context=30, rows=8, horizon=362,
        model="kronos", clock=ticks,
    )  # fmt: skip
    real = _real(per_step, context=30, horizon=362, rows=rows)
    assert 0.7 * real <= found.seconds(horizon=362, rows=rows) <= 1.3 * real + 1.0


def test_the_warm_up_reaches_past_two_steps_on_a_long_horizon() -> None:
    """A step costs more as the window grows; two steps from a short window miss that."""
    ticks = _Ticks()
    per_step = lambda window: 1e-4 * window**1.2  # noqa: E731  # a step costs more than its window
    stub = _timed(ticks, per_step)
    found = _forecast.calibrate(
        cast(Any, stub), _bars(300), context=30, rows=32, horizon=362, model="kronos",
        clock=ticks,
    )  # fmt: skip
    assert max(stub.steps) > 2
    assert sum(stub.steps) < 362 // 2  # the warm-up stays short beside the run
    real = _real(per_step, context=30, horizon=362, rows=32)
    assert 0.7 * real <= found.seconds(horizon=362, rows=32) <= 1.3 * real + 1.0
