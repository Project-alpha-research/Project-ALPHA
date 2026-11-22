"""``lag`` on indicators and the ``highest`` / ``lowest`` channels: values, warm-up, look-ahead."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from alpha_core import DataError
from alpha_strategies.rules import (
    canonical_json,
    operand_series,
    parse_operand,
    parse_rule_spec,
    rule_signal,
    spec_sha256,
    trailing_ohlcv,
)


def _bars(seed: int, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n))
    return close * 1.004, close * 0.996, close


def _rule(long_when: list[dict[str, Any]], history: int | None = None) -> Any:
    doc: dict[str, Any] = {"name": "t", "long_when": long_when, "short_when": []}
    if history is not None:
        doc["history"] = history
    return parse_rule_spec(doc)


def _channel(which: str, window: int, field: str, lag: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {"indicator": which, "params": [window], "field": field}
    return {**out, "lag": lag} if lag else out


def test_highest_includes_the_current_bar_and_lag_one_excludes_it() -> None:
    high = np.array([5.0, 7.0, 6.0, 9.0, 8.0])
    series = trailing_ohlcv(high, high - 1.0, high - 0.5, history=5)
    now = operand_series(series, parse_operand(_channel("highest", 3, "high"), "o"))
    assert np.isnan(now[:2]).all()
    assert list(now[2:]) == [7.0, 9.0, 9.0]  # bar 3 sees itself (9)
    before = operand_series(series, parse_operand(_channel("highest", 3, "high", 1), "o"))
    assert np.isnan(before[:3]).all()
    assert list(before[3:]) == [7.0, 9.0]  # bar 3 sees bars 0-2 only (7)


def test_lowest_mirrors_highest() -> None:
    low = np.array([5.0, 3.0, 4.0, 2.0, 6.0])
    series = trailing_ohlcv(low + 1.0, low, low + 0.5, history=5)
    now = operand_series(series, parse_operand(_channel("lowest", 3, "low"), "o"))
    assert list(now[2:]) == [3.0, 2.0, 2.0]
    before = operand_series(series, parse_operand(_channel("lowest", 3, "low", 1), "o"))
    assert list(before[3:]) == [3.0, 2.0]


def test_breakout_never_compares_a_bar_with_itself() -> None:
    # Close can never exceed its own highest(20, close) without lag, so the lagged form is the test.
    close = [10.0] * 20 + [11.0]
    own = _rule(
        [{"left": {"source": "close"}, "op": ">", "right": _channel("highest", 20, "close")}],
        history=21,
    )
    brk = _rule(
        [{"left": {"source": "close"}, "op": ">", "right": _channel("highest", 20, "close", 1)}],
        history=21,
    )
    assert rule_signal(own, close, close, close) == 0
    assert rule_signal(brk, close, close, close) == 1


def test_indicator_lag_reads_the_value_n_bars_ago() -> None:
    _, _, close = _bars(3, 60)
    series = trailing_ohlcv(close * 1.004, close * 0.996, close, history=60)
    base = operand_series(series, parse_operand({"indicator": "rsi", "params": [14]}, "o"))
    lagged = operand_series(
        series, parse_operand({"indicator": "rsi", "params": [14], "lag": 2}, "o")
    )
    assert np.isnan(lagged[: 14 + 2]).all()
    assert lagged[16:] == pytest.approx(base[14:-2], rel=1e-9, abs=1e-12)


def test_crossed_above_is_two_conditions() -> None:
    rsi = {"indicator": "rsi", "params": [2]}
    spec = _rule(
        [
            {"left": rsi, "op": ">", "right": {"value": 30}},
            {"left": {**rsi, "lag": 1}, "op": "<=", "right": {"value": 30}},
        ],
        history=60,
    )
    falling = [100.0 - 0.5 * i for i in range(59)]  # RSI is 0 on every bar
    crossing = [*falling, falling[-1] + 3.0]  # last bar: RSI jumps above 30, bar before was 0
    assert rule_signal(spec, crossing, crossing, crossing) == 1
    still_up = [*crossing, crossing[-1] + 3.0][-60:]  # a second up bar: yesterday is already above
    assert rule_signal(spec, still_up, still_up, still_up) == 0


def test_warmup_grows_by_lag_and_window_and_undefined_means_false() -> None:
    assert parse_operand({"indicator": "rsi", "params": [14], "lag": 3}, "o").bars_needed == 18
    assert parse_operand(_channel("highest", 20, "high", 1), "o").bars_needed == 21
    assert (
        parse_operand(
            {"indicator": "macd", "params": [12, 26, 9], "field": "signal", "lag": 2}, "o"
        ).bars_needed
        == 26 + 9 - 1 + 2
    )
    spec = _rule(
        [{"left": {"source": "close"}, "op": ">", "right": _channel("highest", 5, "high", 2)}]
    )
    assert spec.warmup == 7
    with pytest.raises(DataError, match="between 7"):
        _rule(
            [{"left": {"source": "close"}, "op": ">", "right": _channel("highest", 5, "high", 2)}],
            history=6,
        )
    # Warm-up bars are NaN, never 0 and never true.
    high, low, close = _bars(1, 6)
    values = operand_series(
        trailing_ohlcv(high, low, close, history=6),
        parse_operand(_channel("highest", 5, "high", 2), "o"),
    )
    assert np.isnan(values).all()


def test_undefined_value_raises_instead_of_being_true() -> None:
    spec = _rule(
        [{"left": {"source": "close"}, "op": ">", "right": _channel("highest", 5, "high", 2)}],
        history=7,
    )
    high, low, close = _bars(2, 7)
    assert rule_signal(spec, high, low, close) in (0, 1)  # 7 bars: defined
    with pytest.raises(DataError, match="between 16"):
        _rule(
            [
                {
                    "left": {"source": "close"},
                    "op": ">",
                    "right": {"indicator": "rsi", "params": [14], "lag": 1},
                }
            ],
            history=15,
        )


@pytest.mark.bias_guard
@pytest.mark.parametrize(
    "operand",
    [
        {"indicator": "rsi", "params": [5], "lag": 2},
        {"indicator": "sma", "params": [5], "lag": 1},
        _channel("highest", 6, "high"),
        _channel("lowest", 6, "low", 1),
    ],
)
def test_changing_bars_after_t_does_not_change_the_value_at_t(operand: dict[str, Any]) -> None:
    high, low, close = _bars(4, 40)
    op = parse_operand(operand, "o")
    t = 25
    clean = operand_series(trailing_ohlcv(high, low, close, history=40), op)
    h2, l2, c2 = high.copy(), low.copy(), close.copy()
    c2[t + 1 :] *= 3.0
    h2[t + 1 :] *= 3.0
    l2[t + 1 :] *= 3.0
    poisoned = operand_series(trailing_ohlcv(h2, l2, c2, history=40), op)
    np.testing.assert_array_equal(clean[: t + 1], poisoned[: t + 1])
    assert not np.array_equal(clean, poisoned)  # the control: later values do move


def test_lag_zero_is_byte_identical_and_non_zero_lag_is_distinct() -> None:
    plain = {"indicator": "rsi", "params": [14]}
    doc = {
        "name": "x",
        "history": 60,
        "long_when": [{"left": plain, "op": "<", "right": {"value": 30}}],
    }
    zero = {**doc, "long_when": [{"left": {**plain, "lag": 0}, "op": "<", "right": {"value": 30}}]}
    one = {**doc, "long_when": [{"left": {**plain, "lag": 1}, "op": "<", "right": {"value": 30}}]}
    assert canonical_json(parse_rule_spec(doc)) == canonical_json(parse_rule_spec(zero))
    assert '"lag"' not in canonical_json(parse_rule_spec(zero))
    assert spec_sha256(parse_rule_spec(doc)) != spec_sha256(parse_rule_spec(one))
    assert parse_operand({**plain, "lag": 1}, "o").label == "rsi:14:lag:1"


@pytest.mark.parametrize(
    "operand",
    [
        {"indicator": "highest", "params": [20]},
        {"indicator": "highest", "params": [20], "field": "volume"},
        {"indicator": "sma", "params": [20], "field": "high"},
        {"indicator": "highest", "params": [1], "field": "high"},
        {"indicator": "highest", "params": [20], "field": "high", "lag": -1},
        {"indicator": "highest", "params": [20], "field": "high", "lag": True},
    ],
)
def test_malformed_channels_fail_loud(operand: dict[str, Any]) -> None:
    with pytest.raises(DataError):
        parse_operand(operand, "o")
