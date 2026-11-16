"""The judge's top-minus-bottom-third spread check (ADR-0055) is point-in-time.

Its verdict over decision days up to day k must not change when every bar after the last
forward window of day k, and every factor value after day k, is corrupted. The liquidity mask on
day k must not change when later volumes are corrupted.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from alpha_cli import _rdagent_universe as universes
from alpha_cli import rdagent_factor_eval as ev

pytestmark = pytest.mark.bias_guard

SYMBOLS = [f"C{i:02}USDT" for i in range(15)]


def _arrays() -> tuple[np.ndarray, np.ndarray, list[date], list[date]]:
    first, last = map(date.fromisoformat, ev.EXPLORATION)
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    open_days = [first + timedelta(days=i) for i in range(1095)]
    rng = np.random.default_rng(55)
    opens = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, (1095, 15)), axis=0))
    # A weak true signal, so verdicts are not trivially one-sided.
    future = np.vstack([opens[2:] / opens[1:-1] - 1, np.zeros((2, 15))])[: len(days)]
    signal = 0.2 * future + rng.normal(0, 0.02, (len(days), 15))
    return signal, opens, days, open_days


@pytest.mark.parametrize("clock", ["daily", "weekly", "monthly"])
@pytest.mark.parametrize("k", [300, 700])
def test_spread_at_day_k_ignores_later_bars_and_values(clock: str, k: int) -> None:
    signal, opens, days, open_days = _arrays()
    h = ev.CLOCKS[clock]
    clean = ev.spread_at_clock(
        signal[: k + 1], opens, days[: k + 1], "a" * 64, clock,
        open_days=open_days, direction=1, symbols=SYMBOLS, n_resamples=50,
    )  # fmt: skip
    poisoned_opens = opens.copy()
    poisoned_signal = signal.copy()
    rng = np.random.default_rng(1)
    poisoned_opens[k + 2 + h :] *= rng.uniform(0.2, 5.0, poisoned_opens[k + 2 + h :].shape)
    poisoned_signal[k + 1 :] = rng.normal(size=poisoned_signal[k + 1 :].shape) * 1e3
    poisoned = ev.spread_at_clock(
        poisoned_signal[: k + 1], poisoned_opens, days[: k + 1], "a" * 64, clock,
        open_days=open_days, direction=1, symbols=SYMBOLS, n_resamples=50,
    )  # fmt: skip
    assert poisoned == clean


def test_spread_uses_the_bar_after_the_window_never() -> None:
    """Corrupting the open one day after day k's exit changes nothing; the exit open itself does."""
    signal, opens, days, open_days = _arrays()
    k, clock = 280, "weekly"
    base = ev.spread_at_clock(
        signal[: k + 1], opens, days[: k + 1], "b" * 64, clock,
        open_days=open_days, direction=1, symbols=SYMBOLS, n_resamples=50,
    )  # fmt: skip
    last = max(i for i in range(k + 1) if i % 7 == 0)
    after = opens.copy()
    after[last + 1 + 7 + 1 :] *= 3.0
    same = ev.spread_at_clock(
        signal[: k + 1], after, days[: k + 1], "b" * 64, clock,
        open_days=open_days, direction=1, symbols=SYMBOLS, n_resamples=50,
    )  # fmt: skip
    assert same == base
    exit_poison = opens.copy()
    exit_poison[last + 1 + 7, :5] *= 3.0
    moved = ev.spread_at_clock(
        signal[: k + 1], exit_poison, days[: k + 1], "b" * 64, clock,
        open_days=open_days, direction=1, symbols=SYMBOLS, n_resamples=50,
    )  # fmt: skip
    assert moved["mean_spread"] != base["mean_spread"]  # the guard can see a real dependence


def test_liquidity_mask_on_day_k_ignores_later_volumes() -> None:
    rng = np.random.default_rng(7)
    start = date(2020, 6, 1)
    volume_days = [start + timedelta(days=i) for i in range(1300)]
    volume = rng.lognormal(15, 1.5, (1300, 15))
    first = date(2021, 1, 1)
    days = [first + timedelta(days=i) for i in range(900)]
    rule = {"lookback_days": 90, "min_median_quote_volume": 3e6, "max_names": 10}
    clean = universes.eligibility(volume, volume_days, days, rule)
    for k in (0, 250, 600):
        cut = volume_days.index(days[k]) + 1
        poisoned = volume.copy()
        poisoned[cut:] = rng.lognormal(25, 3, poisoned[cut:].shape)
        poisoned[cut + 3, 4] = np.nan
        assert (
            universes.eligibility(poisoned, volume_days, days, rule)[: k + 1] == clean[: k + 1]
        ).all()


def _leaky_spread(signal: np.ndarray, opens: np.ndarray, k: int, h: int) -> float:
    """An off-by-one twin: exits one open too late, so it reads the bar after the window."""
    rows = list(range(0, k + 1, h))
    outcome = np.array([opens[i + 2 + h] / opens[i + 1] - 1 for i in rows])
    result = ev.spread(signal[rows], outcome, 1, SYMBOLS, "c" * 64, horizon=h, n_resamples=20)
    return float(result["mean_spread"])


@pytest.mark.parametrize("h", [1, 7, 28])
def test_spread_leaky_twin_is_caught_by_the_same_poison(h: int) -> None:
    signal, opens, _, _ = _arrays()
    k = 280  # a decision day at every clock, so the twin's extra open is the first poisoned one
    poisoned = opens.copy()
    poisoned[k + 2 + h :] *= np.random.default_rng(1).uniform(0.2, 5.0, poisoned[k + 2 + h :].shape)
    assert _leaky_spread(signal, poisoned, k, h) != _leaky_spread(signal, opens, k, h)


def test_liquidity_leaky_twin_is_caught_by_the_same_poison() -> None:
    """A mask that reads the next 90 days' volume moves when later volumes are poisoned."""
    rng = np.random.default_rng(7)
    start = date(2020, 6, 1)
    volume_days = [start + timedelta(days=i) for i in range(1300)]
    volume = rng.lognormal(15, 1.5, (1300, 15))
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(400)]
    rule = {"lookback_days": 90, "min_median_quote_volume": 3e6, "max_names": 10}

    def leaky(values: np.ndarray) -> np.ndarray:
        shifted = np.vstack([values[90:], np.repeat(values[-1:], 90, axis=0)])  # sees d+90
        return universes.eligibility(shifted, volume_days, days, rule)

    k = 250
    cut = volume_days.index(days[k]) + 1
    poisoned = volume.copy()
    poisoned[cut:] = rng.lognormal(25, 3, poisoned[cut:].shape)
    assert (leaky(poisoned)[: k + 1] != leaky(volume)[: k + 1]).any()
