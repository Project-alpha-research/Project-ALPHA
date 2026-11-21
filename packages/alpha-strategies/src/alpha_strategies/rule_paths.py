"""Rule signals for every bar of one price path at once, equal bit for bit to ``rule_signal``.

``rule_signal`` evaluates one trailing window of exactly ``history`` bars. The Tier-1 null asks it
for every bar of every resampled path, so the indicators are recomputed over the whole window on
each bar in Python. This module gives the same numbers faster: it builds every trailing window of a
path and runs the same arithmetic on all windows at once (one numpy operation per step of a
recursion, across windows). Every window still starts its own EMA/RSI recursion and its own
cumulative sum, so the value on bar ``t`` is exactly the value ``rule_signal`` gives over
``closes[t - history + 1 : t + 1]``. Elementwise float64 operations in the same order round the
same way, so the results are equal, not close: ``tests/unit/test_rule_paths.py`` checks equality
over random paths for every indicator. Indicators without a fast form here fall back to
``operand_series`` on each window, which is the definition itself.

It is for the surrogate only: the engine keeps ``evaluate_rules`` on its own trailing window.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from alpha_core import DataError
from alpha_strategies.rules import (
    Condition,
    FloatArray,
    Operand,
    RuleSpec,
    no_value_message,
    operand_series,
    rule_signal,
    trailing_ohlcv,
)

#: windows per block, so a long history on a long path stays inside a fixed memory budget
_CELLS = 2_000_000


class _Windows:
    """Every trailing window of ``history`` bars that ends at or after ``start``."""

    def __init__(self, highs: FloatArray, lows: FloatArray, closes: FloatArray, history: int):
        self.history = history
        self.high, self.low, self.close = highs, lows, closes

    def blocks(self, start: int) -> list[tuple[int, int]]:
        first = max(start, self.history - 1)
        size = max(1, _CELLS // self.history)
        return [(a, min(a + size, self.close.size)) for a in range(first, self.close.size, size)]

    def rows(self, values: FloatArray, a: int, b: int) -> FloatArray:
        view = sliding_window_view(values, self.history)[a - self.history + 1 : b - self.history + 1]
        return np.ascontiguousarray(view)


def _last_mean(rows: FloatArray, window: int) -> FloatArray:
    """``rolling_mean(row, window)[-1]`` for every row: its cumulative sum, then one difference."""
    csum = np.cumsum(rows, axis=1, dtype=np.float64)
    head = csum[:, -window - 1] if window < rows.shape[1] else 0.0
    return np.asarray((csum[:, -1] - head) / float(window))


def _ema_steps(rows: FloatArray, window: int) -> FloatArray:
    """``ema(row, window)`` for every row, as a (rows, history) array."""
    alpha = 2.0 / (window + 1.0)
    out = np.empty_like(rows)
    acc = rows[:, 0].copy()
    out[:, 0] = acc
    for i in range(1, rows.shape[1]):
        acc = alpha * rows[:, i] + (1.0 - alpha) * acc
        out[:, i] = acc
    return out


def _last_ema(rows: FloatArray, window: int) -> FloatArray:
    alpha = 2.0 / (window + 1.0)
    acc = rows[:, 0].copy()
    for i in range(1, rows.shape[1]):
        acc = alpha * rows[:, i] + (1.0 - alpha) * acc
    return acc


def _last_rsi(rows: FloatArray, window: int) -> FloatArray:
    delta = np.diff(rows, axis=1)
    gains = np.maximum(delta, 0.0)
    losses = np.maximum(-delta, 0.0)
    # np.mean of each row's first ``window`` values, called per row: the 1-D summation order.
    avg_gain = np.array([float(np.mean(row[:window])) for row in gains], dtype=np.float64)
    avg_loss = np.array([float(np.mean(row[:window])) for row in losses], dtype=np.float64)
    for i in range(window + 1, rows.shape[1]):
        avg_gain = (avg_gain * (window - 1) + gains[:, i - 1]) / window
        avg_loss = (avg_loss * (window - 1) + losses[:, i - 1]) / window
    ratio = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss > 0.0)
    flat = np.where(avg_gain > 0.0, 100.0, 50.0)
    return np.where(avg_loss <= 0.0, flat, 100.0 - 100.0 / (1.0 + ratio))


def _last_atr(highs: FloatArray, lows: FloatArray, closes: FloatArray, window: int) -> FloatArray:
    previous = np.concatenate((closes[:, :1], closes[:, :-1]), axis=1)
    true_range = np.maximum(
        highs - lows, np.maximum(np.abs(highs - previous), np.abs(lows - previous))
    )
    return _last_mean(true_range, window)


def _last_std(close: FloatArray, a: int, b: int, window: int) -> FloatArray:
    return np.array([float(np.std(close[t - window + 1 : t + 1])) for t in range(a, b)])


def _last_macd(rows: FloatArray, operand: Operand) -> FloatArray:
    fast, slow, signal = (int(v) for v in operand.params)
    line = _ema_steps(rows, fast) - _ema_steps(rows, slow)
    if operand.field == "line":
        return np.asarray(line[:, -1])
    sig = _last_ema(line, signal)
    return np.asarray(sig if operand.field == "signal" else line[:, -1] - sig)


def _fallback(w: _Windows, operand: Operand, a: int, b: int) -> FloatArray:
    h = w.history
    return np.array(
        [
            float(
                operand_series(
                    trailing_ohlcv(
                        w.high[t - h + 1 : t + 1],
                        w.low[t - h + 1 : t + 1],
                        w.close[t - h + 1 : t + 1],
                        history=h,
                    ),
                    operand,
                )[-1]
            )
            for t in range(a, b)
        ],
        dtype=np.float64,
    )


def _block_values(w: _Windows, operand: Operand, a: int, b: int) -> FloatArray:
    """The operand's last-bar value on each window ending at ``a .. b - 1``."""
    if operand.kind == "value":
        return np.full(b - a, float(operand.value or 0.0), dtype=np.float64)
    if operand.kind == "source":
        source = {"high": w.high, "low": w.low, "close": w.close}[str(operand.source)]
        return np.asarray(source[a - operand.lag : b - operand.lag], dtype=np.float64)
    p = operand.params
    name = operand.indicator
    if w.history < operand.bars_needed:  # still warming up on the last bar: the definition says
        return _fallback(w, operand, a, b)
    if name == "sma":
        return _last_mean(w.rows(w.close, a, b), int(p[0]))
    if name == "ema":
        return _last_ema(w.rows(w.close, a, b), int(p[0]))
    if name == "rsi":
        return _last_rsi(w.rows(w.close, a, b), int(p[0]))
    if name == "atr":
        rows = (w.rows(w.high, a, b), w.rows(w.low, a, b), w.rows(w.close, a, b))
        return _last_atr(*rows, int(p[0]))
    if name == "macd":
        return _last_macd(w.rows(w.close, a, b), operand)
    if name == "bbands" and operand.field is not None:
        mid = _last_mean(w.rows(w.close, a, b), int(p[0]))
        if operand.field == "middle":
            return mid
        sd = _last_std(w.close, a, b, int(p[0]))
        return np.asarray(mid + float(p[1]) * sd if operand.field == "upper" else mid - float(p[1]) * sd)
    return _fallback(w, operand, a, b)


def _one(spec: RuleSpec, h: FloatArray, lo: FloatArray, c: FloatArray) -> int | str:
    try:
        return rule_signal(spec, h, lo, c)
    except DataError as exc:
        return str(exc)


def _side(
    conditions: Sequence[Condition], values: Callable[[Operand], FloatArray], size: int, h: int
) -> tuple[FloatArray, list[str | None]]:
    """Whether every condition holds on each bar, in order, stopping at the first that fails.

    A condition that is reached and has no finite value is an error on that bar, as in
    ``evaluate_rules``; a condition after a failed one is never read, so it raises nothing.
    """
    alive = np.full(size, bool(conditions))
    errors: list[str | None] = [None] * size
    for condition in conditions:
        left, right = values(condition.left), values(condition.right)
        finite = np.isfinite(left) & np.isfinite(right)
        for index in np.flatnonzero(alive & ~finite):
            errors[int(index)] = errors[int(index)] or no_value_message(condition, h)
        alive &= finite
        op = condition.op
        passed = (
            left > right
            if op == ">"
            else left < right
            if op == "<"
            else left >= right
            if op == ">="
            else left <= right
        )
        alive &= passed
    return alive, errors


def path_signals(
    spec: RuleSpec,
    highs: Sequence[float] | FloatArray,
    lows: Sequence[float] | FloatArray,
    closes: Sequence[float] | FloatArray,
    *,
    start: int = 0,
) -> list[int | str | None]:
    """``rule_signal`` over ``closes[: t + 1]`` for every bar ``t`` from ``start`` on.

    The entry is the signal, or the ``DataError`` message ``rule_signal`` would raise on that bar
    (a string), or None before the first full window. Nothing raises here, so a bar the caller never
    reads cannot fail its run.
    """
    h, lo, c = (np.asarray(x, dtype=np.float64) for x in (highs, lows, closes))
    if not (h.shape == lo.shape == c.shape) or c.ndim != 1:
        raise DataError("highs, lows and closes must have the same length")
    out: list[int | str | None] = [None] * c.size
    with np.errstate(invalid="ignore"):
        valid = np.isfinite(h) & np.isfinite(lo) & np.isfinite(c) & (h >= lo)
        valid &= (c <= h) & (c >= lo) & (c > 0.0)
    if spec.history < 2 or not bool(np.all(valid)):
        # A bar that trailing_ohlcv refuses: take each window the slow way, with its own error.
        for t in range(max(start, spec.history - 1), c.size):
            out[t] = _one(spec, h[: t + 1], lo[: t + 1], c[: t + 1])
        return out
    w = _Windows(h, lo, c, spec.history)
    for a, b in w.blocks(start):
        cache: dict[Operand, FloatArray] = {}

        def values(operand: Operand, a: int = a, b: int = b) -> FloatArray:
            if operand not in cache:
                cache[operand] = _block_values(w, operand, a, b)
            return cache[operand]

        long, long_errors = _side(spec.long_when, values, b - a, spec.history)
        short, short_errors = _side(spec.short_when, values, b - a, spec.history)
        for i in range(b - a):
            error = long_errors[i] or short_errors[i]
            out[a + i] = error or (0 if long[i] == short[i] else 1 if long[i] else -1)
    return out
