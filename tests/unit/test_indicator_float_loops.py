"""RSI and EMA run their recursions on plain floats: the outputs equal the numpy-scalar loops bit
for bit (a speed change only; every stored rule run and chart keeps its numbers)."""

from __future__ import annotations

import numpy as np
import pytest

from alpha_patterns import ema, rsi
from alpha_patterns.indicators import _rsi_value


def numpy_scalar_rsi(closes: np.ndarray, window: int) -> np.ndarray:
    """The loop as it was, reading numpy scalars."""
    n = closes.size
    out = np.full(n, 50.0, dtype=np.float64)
    if n <= window:
        return out
    delta = np.diff(closes)
    gains, losses = np.maximum(delta, 0.0), np.maximum(-delta, 0.0)
    avg_gain, avg_loss = float(np.mean(gains[:window])), float(np.mean(losses[:window]))
    out[window] = _rsi_value(avg_gain, avg_loss)
    for i in range(window + 1, n):
        avg_gain = (avg_gain * (window - 1) + gains[i - 1]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i - 1]) / window
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def numpy_scalar_ema(values: np.ndarray, window: int) -> np.ndarray:
    alpha = 2.0 / (window + 1.0)
    out = np.empty(values.size, dtype=np.float64)
    acc = float(values[0])
    for i in range(values.size):
        acc = alpha * float(values[i]) + (1.0 - alpha) * acc if i else float(values[0])
        out[i] = acc
    return out


@pytest.mark.parametrize("seed", range(4))
def test_rsi_equals_the_numpy_scalar_loop(seed: int) -> None:
    rng = np.random.default_rng(seed)
    closes = np.asarray(123.456789 * np.cumprod(1.0 + rng.normal(0.0, 0.02, 600)), dtype=np.float64)
    closes[100:110] = closes[100]  # flat stretch: zero gains and losses
    for window in (2, 14, 50):
        assert np.array_equal(rsi(closes, window), numpy_scalar_rsi(closes, window))


@pytest.mark.parametrize("seed", range(4))
def test_ema_equals_the_numpy_scalar_loop(seed: int) -> None:
    rng = np.random.default_rng(seed)
    values = 123.456789 * np.cumprod(1.0 + rng.normal(0.0, 0.02, 600))
    for raw in (values, values.astype(np.float32), np.round(values).astype(np.int64)):
        series = np.asarray(raw, dtype=np.float64)  # the declared input; the cast is exact
        for window in (2, 12, 200):
            assert np.array_equal(ema(series, window), numpy_scalar_ema(series, window))
