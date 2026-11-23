"""The Kronos time estimate comes from a short timed warm-up on this machine, rounded up."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

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
        stub, bars, context=120, horizon=6, rows=10, model="kronos"
    )
    started = time.monotonic()
    stub.forecast(bars[-120:], horizon=6, sample_count=10)
    real = time.monotonic() - started + 0.05  # the load the warm-up already paid
    assert 0.7 * real <= expected <= 1.3 * real + 1.0, (expected, real)  # +1: rounded up


def test_the_estimate_is_rounded_up_to_a_whole_second() -> None:
    stub = _Stub(2e-5)
    seconds = _forecast.calibrated_seconds(
        stub, _bars(300), context=120, horizon=12, rows=30, model="kronos"
    )
    assert seconds == int(seconds) and seconds >= 1


def test_the_offline_double_is_never_timed() -> None:
    stub = _Stub(1.0)
    seconds = _forecast.calibrated_seconds(
        stub, _bars(300), context=120, horizon=12, rows=30, model="fake"
    )
    assert stub.calls == 0
    assert seconds == pytest.approx(
        _forecast.estimate_seconds(context=120, horizon=12, rows=30), rel=1e-9, abs=1e-12
    )


def test_minutes_are_rounded_up() -> None:
    assert _forecast.say_time(100.0) == "about 2 minutes"
    assert _forecast.say_time(121.0) == "about 3 minutes"


class _BatchedStub(_Stub):
    """Kronos draws samples in batches of 32: a batch costs about what one sample costs."""

    def forecast(
        self, bars: Sequence[Bar], *, horizon: int, sample_count: int, **_: object
    ) -> object:
        self.calls += 1
        reads = sum(min(len(bars) + step, _forecast.MAX_WINDOW) for step in range(horizon))
        time.sleep(reads * -(-sample_count // 32) * self.per_read)
        return object()


@pytest.mark.parametrize("rows", [32, 64])
def test_the_estimate_counts_batches_not_single_samples(rows: int) -> None:
    stub = _BatchedStub(1e-4)
    bars = _bars(300)
    expected = _forecast.calibrated_seconds(
        stub, bars, context=120, horizon=12, rows=rows, model="kronos"
    )
    started = time.monotonic()
    stub.forecast(bars[-120:], horizon=12, sample_count=rows)
    real = time.monotonic() - started
    assert expected <= 1.3 * real + 1.0, (expected, real)  # +1: rounded up
