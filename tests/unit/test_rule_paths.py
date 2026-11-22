"""``path_signals`` equals ``rule_signal`` on every trailing window, bit for bit.

The fast path is only allowed because it changes no number: every operand value and every signal
is compared exactly (``==``, not a tolerance) with the window-by-window definition.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from alpha_core import DataError
from alpha_strategies.rule_paths import _block_values, _Windows, path_signals
from alpha_strategies.rules import (
    operand_series,
    parse_rule_spec,
    rule_signal,
    trailing_ohlcv,
)

OPERANDS: list[dict[str, Any]] = [
    {"source": "close"},
    {"source": "high", "lag": 3},
    {"source": "low", "lag": 1},
    {"indicator": "sma", "params": [20]},
    {"indicator": "sma", "params": [70]},
    {"indicator": "ema", "params": [12]},
    {"indicator": "ema", "params": [70]},
    {"indicator": "rsi", "params": [14]},
    {"indicator": "rsi", "params": [2]},
    {"indicator": "atr", "params": [14]},
    {"indicator": "atr", "params": [70]},
    {"indicator": "bbands", "params": [20, 2], "field": "upper"},
    {"indicator": "bbands", "params": [20, 1.5], "field": "lower"},
    {"indicator": "bbands", "params": [20, 2], "field": "middle"},
    {"indicator": "macd", "params": [12, 26, 9], "field": "line"},
    {"indicator": "macd", "params": [12, 26, 9], "field": "signal"},
    {"indicator": "macd", "params": [5, 35, 5], "field": "histogram"},
    {"indicator": "hawkes", "params": [0.1, 20]},
    {"indicator": "runs_z", "params": [20]},
    {"indicator": "perm_entropy", "params": [3, 5]},
    {"indicator": "cmma", "params": [10, 20]},
    {"indicator": "vg_path", "params": [12], "field": "price"},
    {"indicator": "reversibility", "params": [20]},
    {"value": 0.5},
    {"indicator": "sma", "params": [20], "lag": 1},
    {"indicator": "ema", "params": [12], "lag": 5},
    {"indicator": "rsi", "params": [14], "lag": 1},
    {"indicator": "rsi", "params": [2], "lag": 3},
    {"indicator": "atr", "params": [14], "lag": 2},
    {"indicator": "bbands", "params": [20, 2], "field": "upper", "lag": 1},
    {"indicator": "macd", "params": [12, 26, 9], "field": "signal", "lag": 2},
    {"indicator": "hawkes", "params": [0.1, 20], "lag": 1},
    {"indicator": "highest", "params": [20], "field": "high"},
    {"indicator": "highest", "params": [20], "field": "high", "lag": 1},
    {"indicator": "lowest", "params": [10], "field": "low", "lag": 1},
    {"indicator": "lowest", "params": [30], "field": "close", "lag": 4},
    {"indicator": "highest", "params": [69], "field": "close", "lag": 1},
]


def path(seed: int, n: int, level: float = 123.456789) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    close = level * np.cumprod(1.0 + rng.normal(0.0003, 0.012, n))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.004, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.004, n)))
    return high, low, close


def spec_of(long_when: list[dict[str, Any]], history: int = 70) -> Any:
    return parse_rule_spec(
        {"name": "t", "history": history, "long_when": long_when, "short_when": []}
    )


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_every_operand_value_equals_the_window_definition(seed: int) -> None:
    high, low, close = path(seed, 260)
    history = 70
    windows = _Windows(high, low, close, history)
    for raw in OPERANDS:
        rule = spec_of([{"left": raw, "op": ">", "right": {"source": "close"}}], history)
        operand = rule.long_when[0].left
        got = _block_values(windows, operand, history - 1, close.size)
        expected = np.array(
            [
                operand_series(
                    trailing_ohlcv(high[: t + 1], low[: t + 1], close[: t + 1], history=history),
                    operand,
                )[-1]
                for t in range(history - 1, close.size)
            ]
        )
        same = (got == expected) | (np.isnan(got) & np.isnan(expected))
        assert same.all(), (raw, int(np.flatnonzero(~same)[0]))


def _reference(rule: Any, high: Any, low: Any, close: Any, start: int) -> list[int | str | None]:
    out: list[int | str | None] = [None] * close.size
    for t in range(max(start, rule.history - 1), close.size):
        try:
            out[t] = rule_signal(rule, high[: t + 1], low[: t + 1], close[: t + 1])
        except DataError as exc:  # the message is part of what must match
            out[t] = str(exc)
    return out


RULES: list[list[dict[str, Any]]] = [
    [
        {"left": {"indicator": "rsi", "params": [14]}, "op": "<", "right": {"value": 45}},
        {"left": {"source": "close"}, "op": ">", "right": {"indicator": "sma", "params": [50]}},
    ],
    [
        {"left": {"source": "close"}, "op": ">=", "right": {"source": "close", "lag": 1}},
        {
            "left": {"indicator": "atr", "params": [5]},
            "op": "<=",
            "right": {"indicator": "atr", "params": [20]},
        },
    ],  # fmt: skip
    [
        {
            "left": {"indicator": "macd", "params": [12, 26, 9], "field": "histogram"},
            "op": ">",
            "right": {"value": 0},
        },
        {
            "left": {"source": "close"},
            "op": "<",
            "right": {"indicator": "bbands", "params": [20, 1], "field": "upper"},
        },
        {
            "left": {"indicator": "ema", "params": [10]},
            "op": ">",
            "right": {"indicator": "ema", "params": [30]},
        },
    ],  # fmt: skip
    [{"left": {"indicator": "runs_z", "params": [10]}, "op": "<", "right": {"value": 0.5}}],
    [  # crossed above 30, and a break above the prior 20-bar high
        {"left": {"indicator": "rsi", "params": [3]}, "op": ">", "right": {"value": 40}},
        {"left": {"indicator": "rsi", "params": [3], "lag": 1}, "op": "<=", "right": {"value": 40}},
    ],
    [
        {
            "left": {"source": "close"},
            "op": ">",
            "right": {"indicator": "highest", "params": [5], "field": "high", "lag": 1},
        }
    ],
]


@pytest.mark.parametrize("index", range(len(RULES)))
def test_signals_equal_rule_signal_on_every_bar(index: int) -> None:
    high, low, close = path(10 + index, 400)
    rule = spec_of(RULES[index])
    got = path_signals(rule, high, low, close, start=0)
    assert got == _reference(rule, high, low, close, 0)
    assert {0, 1} <= set(got[rule.history - 1 :]), "the fixture must exercise both states"


def test_closes_only_ties_and_a_start_after_the_first_window() -> None:
    """Prices on a coarse grid make exact ties; ``<`` and ``<=`` must split them identically."""
    _, _, close = path(4, 300)
    close = np.round(close, 0)
    for op in (">", ">="):
        rule = spec_of(
            [{"left": {"source": "close"}, "op": op, "right": {"source": "close", "lag": 1}}],
            history=5,
        )
        got = path_signals(rule, close, close, close, start=40)
        assert got == _reference(rule, close, close, close, 40)
        assert got[:40] == [None] * 40


def test_an_undefined_statistic_is_the_same_message_on_the_same_bars() -> None:
    close = np.full(200, 50.0)  # no range and no runs: runs_z is undefined everywhere
    rule = spec_of(
        [{"left": {"indicator": "runs_z", "params": [10]}, "op": "<", "right": {"value": 0}}]
    )
    got = path_signals(rule, close, close, close)
    assert got == _reference(rule, close, close, close, 0)
    assert isinstance(got[-1], str) and "no finite value" in got[-1]


def test_a_bar_the_window_refuses_falls_back_to_the_definition() -> None:
    high, low, close = path(5, 120)
    low[90] = high[90] * 1.01  # a high below its low
    rule = spec_of(RULES[0])
    assert path_signals(rule, high, low, close) == _reference(rule, high, low, close, 0)
