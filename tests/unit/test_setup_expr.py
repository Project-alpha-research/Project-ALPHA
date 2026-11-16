"""Hand-computed trailing expressions and the closed syntax boundary."""

import math
from typing import Any

import polars as pl
import pytest

from alpha_core import DataError
from alpha_study.setup import compile_expr


def frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "open": list(range(12)),
            "close": list(range(1, 13)),
            "high": list(range(2, 14)),
            "low": list(range(12)),
            "volume": [10] * 12,
        }
    )


@pytest.mark.parametrize(
    "text, expected, warmup",
    [
        ("open", list(range(12)), 0),
        ("high", list(range(2, 14)), 0),
        ("low", list(range(12)), 0),
        ("close", list(range(1, 13)), 0),
        ("volume", [10] * 12, 0),
        ("2", [2] * 12, 0),
        ("close + 2", list(range(3, 15)), 0),
        ("close - 2", list(range(-1, 11)), 0),
        ("close * 2", list(range(2, 25, 2)), 0),
        ("-close", list(range(-1, -13, -1)), 0),
        ("abs(-close)", list(range(1, 13)), 0),
        ("close / open", [None] + [(i + 1) / i for i in range(1, 12)], 0),
        ("prev(close)", [None] + list(range(1, 12)), 1),
        ("prev(close, n=2)", [None] * 2 + list(range(1, 11)), 2),
        ("sma(close, 3)", [None] * 2 + list(range(2, 12)), 2),
        ("highest(close, 3)", [None] * 2 + list(range(3, 13)), 2),
        ("lowest(close, 3)", [None] * 2 + list(range(1, 11)), 2),
        ("ema(close, 3)", [None] * 2 + [i + 2**-i for i in range(2, 12)], 2),
        ("atr(3)", [None] * 3 + [2] * 9, 3),
        ("pct_change(close)", [None] + [1 / i for i in range(1, 12)], 1),
        ("pct_change(close, n=2)", [None] * 2 + [2 / i for i in range(1, 11)], 2),
        ("close > 6", [False] * 6 + [True] * 6, 0),
        ("close >= 6", [False] * 5 + [True] * 7, 0),
        ("close < 6", [True] * 5 + [False] * 7, 0),
        ("close <= 6", [True] * 6 + [False] * 6, 0),
        ("close == 6", [False] * 5 + [True] + [False] * 6, 0),
        ("close != 6", [True] * 5 + [False] + [True] * 6, 0),
        ("close > 3 and close < 7", [False] * 3 + [True] * 3 + [False] * 6, 0),
        ("close < 3 or close > 10", [True] * 2 + [False] * 8 + [True] * 2, 0),
        ("not (close > 6)", [True] * 6 + [False] * 6, 0),
        ("crosses_above(close, 6)", [None] + [False] * 5 + [True] + [False] * 5, 1),
        ("crosses_below(-close, -6)", [None] + [False] * 5 + [True] + [False] * 5, 1),
        ("for_bars(close > 3, 3)", [None] * 2 + [False] * 3 + [True] * 7, 2),
        ("within_bars(close == 4, 3)", [None] * 2 + [False] + [True] * 3 + [False] * 6, 2),
        ("prev(close > 3)", [None] + [False] * 3 + [True] * 8, 1),
        ("sma(prev(close, 2), 3)", [None] * 4 + list(range(2, 10)), 4),
    ],
)
def test_values(text: str, expected: list[Any], warmup: int) -> None:
    compiled = compile_expr(text)
    actual = frame().with_columns(compiled.expr.alias("value"))["value"].to_list()
    assert compiled.warmup == warmup
    assert [x is None for x in actual] == [x is None for x in expected]
    assert [x for x in actual if x is not None] == pytest.approx(
        [x for x in expected if x is not None], abs=1e-12
    )
    assert compiled.kind == ("boolean" if any(type(x) is bool for x in expected) else "number")


@pytest.mark.parametrize(
    "text",
    [
        "close.real",
        "__import__('os')",
        "close[0]",
        "lambda: close",
        "unknown",
        "prev(close, -1)",
        "sma(close, volume)",
        "prev(close, nope=2)",
        "'close'",
        "1 < close < 3",
        "sma(close, 5001)",
        "prev(close, 0)",
        "sma(close, 1.5)",
        "[x for x in close]",
        "close ** 2",
        "close // 2",
        "True",
        "sma(close)",
        "abs(close, 2)",
        "prev(close, 2, n=3)",
        "close and volume",
        "not close",
        "for_bars(close, 2)",
        "sma(close > 2, 3)",
        "close + (high > low)",
        "atr(n=2)",
        "close >",
        "1e999",
        "f'{close}'",
        "[close]",
        "abs(x=close)",
    ],
)
def test_rejected_syntax(text: str) -> None:
    with pytest.raises(DataError, match="allowed"):
        compile_expr(text)


@pytest.mark.parametrize(
    "text",
    [
        "(close / 0) > 1",
        "(close > 0) or (close / 0 > 1)",
        "(close < 0) and (close / 0 > 1)",
        "abs(close / 0)",
        "sma(close / 0, 2)",
    ],
)
def test_null_operands_propagate(text: str) -> None:
    assert frame().with_columns(compile_expr(text).expr.alias("v"))["v"].null_count() == 12


def test_nonfinite_sources_and_overflow_are_null() -> None:
    bars = frame().with_columns(pl.Series("close", [math.nan, math.inf] + [1e308] * 10))
    values = bars.select(compile_expr("close * 2").expr)["close"].to_list()
    assert values == [None] * 12


@pytest.mark.parametrize(
    "text, expected",
    [
        ("prev(2)", [None] + [2] * 11),
        ("sma(2, 3)", [None] * 2 + [2] * 10),
        ("ema(2, 3)", [None] * 2 + [2] * 10),
        ("for_bars(2 > 1, 3)", [None] * 2 + [True] * 10),
    ],
)
def test_windowed_literals_broadcast_per_bar(text: str, expected: list[Any]) -> None:
    assert frame().with_columns(compile_expr(text).expr.alias("v"))["v"].to_list() == expected


def test_atr_accounts_for_gaps_and_nested_warmup() -> None:
    source = frame().with_columns(
        pl.Series("close", [10, 20, 5] + [10] * 9),
        pl.Series("high", [12, 22, 7] + [12] * 9),
        pl.Series("low", [8, 18, 3] + [8] * 9),
    )
    # TR begins null, then 12 (gap up), 17 (gap down), 7, then 4 thereafter.
    values = source.select(compile_expr("atr(2)").expr.alias("v"))["v"].to_list()
    assert values[:2] == [None, None]
    assert values[2:] == pytest.approx([14.5, 12, 5.5] + [4] * 7)
    assert compile_expr("prev(ema(sma(close, 4), 3), 2)").warmup == 7


def test_rolling_null_window_does_not_skip_missing_values() -> None:
    source = frame().with_columns(pl.Series("volume", [1, 2, None, 4, 5, 6] + [7] * 6))
    for fn in ["sma", "highest", "lowest"]:
        values = source.select(compile_expr(f"{fn}(volume, 3)").expr.alias("v"))["v"].to_list()
        assert values[:5] == [None] * 5
        assert values[5] is not None


def test_null_inside_a_window_counts_as_false_not_unknown() -> None:
    # Review finding: one missing volume must not turn within_bars/for_bars null for n bars.
    source = frame().with_columns(pl.Series("volume", [60.0] * 6 + [None] + [60.0] * 5))
    within = source.select(compile_expr("within_bars(volume > 50, 5)").expr)["volume"]
    assert within.to_list()[6:] == [True] * 6
    for_all = source.select(compile_expr("for_bars(volume > 50, 2)").expr)["volume"]
    assert for_all.to_list()[5:9] == [True, False, False, True]


@pytest.mark.parametrize(
    "text",
    [
        "-" * 5000 + "close",
        "not " * 3000 + "(close > 1)",
        "close" + " + close" * 5000,
        "close" + " + close" * 200,
        "sma(" * 40 + "close" + ", 2)" * 40,
    ],
)
def test_oversized_expressions_fail_loud_not_hang(text: str) -> None:
    with pytest.raises(DataError, match="too large|too deep"):
        compile_expr(text)


def test_largest_allowed_expression_evaluates_quickly() -> None:
    import time

    # Every wrapped node is cheap: the tree must not double per level.
    text = "close" + " + close" * 30
    started = time.perf_counter()
    values = frame().select(compile_expr(text).expr)["close"].to_list()
    assert time.perf_counter() - started < 2
    assert values[0] == 31


def test_event_operators_count_a_null_condition_as_false() -> None:
    # The decision: a null boolean counts as false. Only the static window warm-up is null.
    for text in ["within_bars(close / 0 > 1, 2)", "for_bars(close / 0 > 1, 2)"]:
        values = frame().with_columns(compile_expr(text).expr.alias("v"))["v"].to_list()
        assert values == [None] + [False] * 11
