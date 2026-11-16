"""Closed daily expression language: nothing reads a later row.

Only columns, literals, arithmetic, comparisons, nonnegative shifts, trailing full
windows, causal EWM, abs, boolean logic and current-row null/finite checks/casts
are emitted. No sorting, centred windows, whole-column aggregates or backfills.
"""

from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass
from functools import reduce
from typing import Literal, cast

import polars as pl

from alpha_core import DataError

SOURCES = ("open", "high", "low", "close", "volume")
FUNCTIONS = (
    "prev",
    "sma",
    "ema",
    "atr",
    "highest",
    "lowest",
    "pct_change",
    "abs",
    "crosses_above",
    "crosses_below",
    "for_bars",
    "within_bars",
)
ARITHMETIC = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
COMPARISONS = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
Kind = Literal["number", "boolean"]


@dataclass(frozen=True)
class CompiledExpr:
    expr: pl.Expr
    kind: Kind
    warmup: int


def _error(node: ast.AST, allowed: str) -> DataError:
    return DataError(f"offending token {ast.unparse(node)!r}: allowed {allowed}")


def _finite(expr: pl.Expr) -> pl.Expr:
    return pl.when(expr.is_finite()).then(expr).otherwise(None)


def _boolean(expr: pl.Expr, *operands: pl.Expr) -> pl.Expr:
    valid = reduce(operator.and_, (x.is_not_null() for x in operands))
    return pl.when(valid).then(expr).otherwise(None)


def _require(node: ast.AST, values: list[CompiledExpr], kind: Kind) -> None:
    if any(value.kind != kind for value in values):
        raise _error(node, f"{kind} operands")


def _window(node: ast.AST) -> int:
    if not isinstance(node, ast.Constant) or type(node.value) is not int:
        raise _error(node, "integer literal window/shift in [1, 5000]")
    n: int = node.value
    if not 1 <= n <= 5000:
        raise _error(node, "integer literal window/shift in [1, 5000]")
    return n


def _call(node: ast.Call) -> CompiledExpr:
    if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
        raise _error(node, f"functions {', '.join(FUNCTIONS)}")
    name, args = node.func.id, list(node.args)
    default = name in {"prev", "pct_change"}
    windowed = name not in {"abs", "atr", "crosses_above", "crosses_below"}
    if node.keywords:
        if not (
            default and len(args) == 1 and len(node.keywords) == 1 and node.keywords[0].arg == "n"
        ):
            raise _error(node, "positional arguments; n= only for prev and pct_change")
        args.append(node.keywords[0].value)
    if default and len(args) == 1:
        args.append(ast.Constant(value=1))
    count = 1 if name in {"abs", "atr"} else 2
    if len(args) != count:
        raise _error(node, f"{name} with {count} arguments")
    if name == "atr":
        n = _window(args[0])
        high, low, previous = (
            _finite(pl.col(c).cast(pl.Float64)) for c in ("high", "low", "close")
        )
        previous = previous.shift(1)
        a, b, c = high - low, (high - previous).abs(), (low - previous).abs()
        maximum = pl.when(a >= b).then(a).otherwise(b)
        maximum = pl.when(maximum >= c).then(maximum).otherwise(c)
        tr = pl.when(previous.is_not_null() & high.is_not_null() & low.is_not_null()).then(maximum)
        return CompiledExpr(_finite(tr.rolling_mean(n, min_samples=n)), "number", n)
    x = _walk(args[0])
    if name == "abs":
        _require(node, [x], "number")
        return CompiledExpr(x.expr.abs(), "number", x.warmup)
    if not windowed:
        y = _walk(args[1])
        _require(node, [x, y], "number")
        a, b, pa, pb = x.expr, y.expr, x.expr.shift(1), y.expr.shift(1)
        crossing = (a > b) & (pa <= pb) if name == "crosses_above" else (a < b) & (pa >= pb)
        return CompiledExpr(
            _boolean(crossing, a, b, pa, pb), "boolean", max(x.warmup, y.warmup) + 1
        )
    n = _window(args[1])
    if name == "prev":
        return CompiledExpr(x.expr.shift(n), x.kind, x.warmup + n)
    if name in {"for_bars", "within_bars"}:
        _require(node, [x], "boolean")
        total = x.expr.cast(pl.Int64).rolling_sum(n, min_samples=n)
        result = total == n if name == "for_bars" else total > 0
        return CompiledExpr(result, "boolean", x.warmup + n - 1)
    _require(node, [x], "number")
    if name == "pct_change":
        result = x.expr / x.expr.shift(n) - 1
        return CompiledExpr(_finite(result), "number", x.warmup + n)
    if name == "ema":
        result = x.expr.ewm_mean(span=n, adjust=False, min_samples=n, ignore_nulls=False)
        result = pl.when(x.expr.is_not_null()).then(result).otherwise(None)
    else:
        rolling = {
            "sma": x.expr.rolling_mean,
            "highest": x.expr.rolling_max,
            "lowest": x.expr.rolling_min,
        }
        result = rolling[name](n, min_samples=n)
    return CompiledExpr(_finite(result), "number", x.warmup + n - 1)


def _walk(node: ast.AST) -> CompiledExpr:
    if isinstance(node, ast.Name) and node.id in SOURCES:
        return CompiledExpr(_finite(pl.col(node.id).cast(pl.Float64)), "number", 0)
    if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
        try:
            number = float(cast(int | float, node.value))
        except OverflowError as exc:
            raise _error(node, "finite numeric literals") from exc
        if not math.isfinite(number):
            raise _error(node, "finite numeric literals")
        # A scalar shift/window would operate on one row before broadcasting.
        # Anchor literals to row shape without depending on any price value.
        literal = pl.lit(number) + pl.col("close").is_null().cast(pl.Float64) * 0
        return CompiledExpr(literal, "number", 0)
    if isinstance(node, ast.Call):
        return _call(node)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.Not)):
        value = _walk(node.operand)
        kind: Kind = "number" if isinstance(node.op, ast.USub) else "boolean"
        _require(node, [value], kind)
        result = -value.expr if kind == "number" else ~value.expr
        return CompiledExpr(result, kind, value.warmup)
    if isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC:
        a, b = _walk(node.left), _walk(node.right)
        _require(node, [a, b], "number")
        return CompiledExpr(
            _finite(ARITHMETIC[type(node.op)](a.expr, b.expr)), "number", max(a.warmup, b.warmup)
        )
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARISONS:
        a, b = _walk(node.left), _walk(node.comparators[0])
        _require(node, [a, b], "number")
        result = COMPARISONS[type(node.ops[0])](a.expr, b.expr)
        return CompiledExpr(result, "boolean", max(a.warmup, b.warmup))
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        values = [_walk(value) for value in node.values]
        _require(node, values, "boolean")
        op = operator.and_ if isinstance(node.op, ast.And) else operator.or_
        operands = [value.expr for value in values]
        result = _boolean(reduce(op, operands), *operands)
        return CompiledExpr(result, "boolean", max(value.warmup for value in values))
    raise _error(
        node,
        f"sources {', '.join(SOURCES)}; functions {', '.join(FUNCTIONS)}; "
        "+ - * /, unary -, single comparisons, and/or/not, finite numbers",
    )


def compile_expr(text: str) -> CompiledExpr:
    """Parse a closed vocabulary into an expression with a causal warm-up bound."""
    try:
        node = ast.parse(text, mode="eval").body
    except SyntaxError as exc:
        raise DataError(f"offending token in {text!r}: allowed a valid setup expression") from exc
    return _walk(node)
