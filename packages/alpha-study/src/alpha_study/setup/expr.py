"""Closed daily expression language: nothing reads a later row.

Only columns, literals, arithmetic, comparisons, nonnegative shifts, trailing full
windows, causal EWM, abs, boolean logic and current-row null/finite checks/casts
are emitted. No sorting, centred windows, whole-column aggregates or backfills.
Expressions are bounded in text length, nesting depth and emitted tree size, so a
pathological input fails loud instead of exhausting memory or time.
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
MAX_TEXT = 2000
MAX_DEPTH = 40
MAX_SIZE = 4000
NON_FINITE = [math.inf, -math.inf, math.nan]


@dataclass(frozen=True)
class CompiledExpr:
    expr: pl.Expr
    kind: Kind
    warmup: int
    size: int = 1  # emitted Polars tree nodes, bounded by MAX_SIZE


def _error(node: ast.AST, allowed: str) -> DataError:
    return DataError(f"offending token {ast.unparse(node)!r}: allowed {allowed}")


Aliases = frozenset[str]
NO_ALIASES: Aliases = frozenset()


def _finite(expr: pl.Expr) -> pl.Expr:
    # One reference to `expr`: a when/then wrapper would double the tree at every level.
    return expr.replace(NON_FINITE, None)


def _all(operands: list[pl.Expr]) -> pl.Expr:
    """Null-propagating AND: the product of 0/1 integers is null if any operand is."""
    return reduce(operator.mul, (x.cast(pl.Int8) for x in operands)) == 1


def _any(operands: list[pl.Expr]) -> pl.Expr:
    """Null-propagating OR."""
    return reduce(operator.add, (x.cast(pl.Int16) for x in operands)) > 0


def _sized(node: ast.AST, expr: pl.Expr, kind: Kind, warmup: int, size: int) -> CompiledExpr:
    if size > MAX_SIZE:
        raise _error(node, f"expressions no larger than {MAX_SIZE} emitted nodes (too large)")
    return CompiledExpr(expr, kind, warmup, size)


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


def _call(node: ast.Call, aliases: Aliases) -> CompiledExpr:
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
        return _sized(node, _finite(tr.rolling_mean(n, min_samples=n)), "number", n, 60)
    x = _walk(args[0], aliases)
    if name == "abs":
        _require(node, [x], "number")
        return _sized(node, x.expr.abs(), "number", x.warmup, x.size + 1)
    if not windowed:
        y = _walk(args[1], aliases)
        _require(node, [x, y], "number")
        a, b, pa, pb = x.expr, y.expr, x.expr.shift(1), y.expr.shift(1)
        crossing = _all([a > b, pa <= pb] if name == "crosses_above" else [a < b, pa >= pb])
        warmup = max(x.warmup, y.warmup) + 1
        return _sized(node, crossing, "boolean", warmup, 2 * (x.size + y.size) + 8)
    n = _window(args[1])
    if name == "prev":
        return _sized(node, x.expr.shift(n), x.kind, x.warmup + n, x.size + 1)
    if name in {"for_bars", "within_bars"}:
        _require(node, [x], "boolean")
        # A missing value inside the window counts as false, never as "unknown for n bars".
        total = x.expr.fill_null(False).cast(pl.Int64).rolling_sum(n, min_samples=n)
        result = total == n if name == "for_bars" else total > 0
        return _sized(node, result, "boolean", x.warmup + n - 1, x.size + 5)
    _require(node, [x], "number")
    if name == "pct_change":
        result = x.expr / x.expr.shift(n) - 1
        return _sized(node, _finite(result), "number", x.warmup + n, 2 * x.size + 5)
    if name == "ema":
        # ignore_nulls=False: a null input gives a null output on that row (tested).
        result = x.expr.ewm_mean(span=n, adjust=False, min_samples=n, ignore_nulls=False)
    else:
        rolling = {
            "sma": x.expr.rolling_mean,
            "highest": x.expr.rolling_max,
            "lowest": x.expr.rolling_min,
        }
        result = rolling[name](n, min_samples=n)
    return _sized(node, _finite(result), "number", x.warmup + n - 1, x.size + 2)


def _walk(node: ast.AST, aliases: Aliases) -> CompiledExpr:
    if isinstance(node, ast.Name) and node.id in SOURCES:
        return CompiledExpr(_finite(pl.col(node.id).cast(pl.Float64)), "number", 0, 3)
    if isinstance(node, ast.Name) and node.id in aliases:
        # A context series: it carries its own warm-up as null, so the static warm-up is 0.
        return CompiledExpr(_finite(pl.col(f"ctx_{node.id}").cast(pl.Float64)), "number", 0, 3)
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
        return CompiledExpr(literal, "number", 0, 6)
    if isinstance(node, ast.Call):
        return _call(node, aliases)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.Not)):
        value = _walk(node.operand, aliases)
        kind: Kind = "number" if isinstance(node.op, ast.USub) else "boolean"
        _require(node, [value], kind)
        result = -value.expr if kind == "number" else ~value.expr
        return _sized(node, result, kind, value.warmup, value.size + 1)
    if isinstance(node, ast.BinOp) and type(node.op) in ARITHMETIC:
        a, b = _walk(node.left, aliases), _walk(node.right, aliases)
        _require(node, [a, b], "number")
        result = _finite(ARITHMETIC[type(node.op)](a.expr, b.expr))
        return _sized(node, result, "number", max(a.warmup, b.warmup), a.size + b.size + 2)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARISONS:
        a, b = _walk(node.left, aliases), _walk(node.comparators[0], aliases)
        _require(node, [a, b], "number")
        result = COMPARISONS[type(node.ops[0])](a.expr, b.expr)
        return _sized(node, result, "boolean", max(a.warmup, b.warmup), a.size + b.size + 1)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        values = [_walk(value, aliases) for value in node.values]
        _require(node, values, "boolean")
        operands = [value.expr for value in values]
        # Any null operand gives null (no Kleene short-circuit): the decision's null rule.
        result = _all(operands) if isinstance(node.op, ast.And) else _any(operands)
        warmup = max(value.warmup for value in values)
        return _sized(node, result, "boolean", warmup, sum(v.size + 2 for v in values) + 1)
    raise _error(
        node,
        f"sources {', '.join([*SOURCES, *sorted(aliases)])}; functions {', '.join(FUNCTIONS)}; "
        "+ - * /, unary -, single comparisons, and/or/not, finite numbers",
    )


def _depth(root: ast.AST) -> int:
    """Nesting depth without recursion, so a deep input cannot overflow the stack."""
    deepest, stack = 0, [(root, 1)]
    while stack:
        node, depth = stack.pop()
        deepest = max(deepest, depth)
        if deepest > MAX_DEPTH:
            break
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return deepest


def compile_expr(text: str, aliases: Aliases = NO_ALIASES) -> CompiledExpr:
    """Parse a closed vocabulary into an expression with a causal warm-up bound.

    `aliases` are the spec's declared context names: each reads the `ctx_<alias>` column.
    """
    if len(text) > MAX_TEXT:
        raise DataError(
            f"expression of {len(text)} characters: allowed at most {MAX_TEXT} (too large)"
        )
    try:
        node = ast.parse(text, mode="eval").body
    except (SyntaxError, RecursionError, MemoryError) as exc:
        raise DataError(f"offending token in {text!r}: allowed a valid setup expression") from exc
    if _depth(node) > MAX_DEPTH:
        raise DataError(
            f"expression nests deeper than {MAX_DEPTH} levels (too deep): {text[:60]!r}"
        )
    return _walk(node, aliases)
