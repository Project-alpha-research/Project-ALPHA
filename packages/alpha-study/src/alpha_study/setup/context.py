"""Context aliases in a setup spec: validation of the `[context]` table and honest counts.

An alias names one context series (`series@key`). The CLI attaches the series to the bars as
`ctx_<alias>` columns; this module never reads a table. A condition is true only where its value is
not null, so a missing context value never makes a setup match.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_study.setup.expr import FUNCTIONS, SOURCES, compile_expr

ALIAS = re.compile(r"[a-z][a-z0-9_]{0,31}")
BINDING = re.compile(r"([a-z0-9_]+)@([A-Za-z0-9._^=-]+)")


def parse_binding(alias: str, text: str) -> tuple[str, str]:
    """Split `series@key`; the key is declared, never inferred."""
    match = BINDING.fullmatch(text)
    if match is None:
        raise ValueError(
            f"context.{alias}: {text!r} must read series@key, for example cot_x@13874A"
        )
    return match[1], match[2]


def check_aliases(context: Mapping[str, str], taken: Iterable[str]) -> None:
    """Fail loud on a name that clashes with a source, a function or another spec name."""
    reserved = {*SOURCES, *FUNCTIONS, *taken}
    for alias, text in context.items():
        if ALIAS.fullmatch(alias) is None:
            raise ValueError(f"context alias {alias!r}: use lowercase letters, digits and _")
        if alias in reserved:
            raise ValueError(f"context alias {alias!r}: already a price source, function or name")
        parse_binding(alias, text)


def used_aliases(text: str, aliases: frozenset[str]) -> frozenset[str]:
    """The declared aliases an expression reads."""
    names = {n.id for n in ast.walk(ast.parse(text, mode="eval")) if isinstance(n, ast.Name)}
    return frozenset(names & aliases)


def condition_texts(spec: Any) -> dict[str, str]:
    """Boolean expressions of the spec that read a context alias, by name."""
    aliases = frozenset(spec.context)
    named = {"event": spec.setup.event, **{f"filter:{n}": t for n, t in spec.filters.items()}}
    if spec.trigger is not None:
        named["trigger"] = spec.trigger.when
    return {n: t for n, t in named.items() if used_aliases(t, aliases)}


def spells(flags: list[bool | None]) -> int:
    """Separate runs of consecutive true bars: a weekly value repeats on daily bars."""
    return sum(1 for i, f in enumerate(flags) if f is True and (i == 0 or flags[i - 1] is not True))


def condition_counts(spec: Any, frame: pl.DataFrame) -> dict[str, dict[str, int]]:
    """Bars where each context condition was true, and its separate spells."""
    aliases = frozenset(spec.context)
    counts: dict[str, dict[str, int]] = {}
    for name, text in condition_texts(spec).items():
        compiled = compile_expr(text, aliases)
        flags = frame.select(compiled.expr.alias("flag"))["flag"].to_list()
        counts[name] = dict(true_bars=sum(f is True for f in flags), spells=spells(flags))
    return counts


def check_frame(spec: Any, frame: pl.DataFrame) -> None:
    missing = [f"ctx_{a}" for a in spec.context if f"ctx_{a}" not in frame.columns]
    if missing:
        raise DataError(f"bars lack the context columns {missing}: attach the series first")
