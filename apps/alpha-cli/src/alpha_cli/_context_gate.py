"""The per-bar context gate of a rule spec: canonical form, attach, evaluate `when`, by timestamp.

The spec's aliases are only names. For identity and evaluation they are replaced by canonical
names (`c0`, `c1`, ...), given in the sorted order of the bound `series@key` texts; `when` is
re-printed from its parse tree. So two specs that differ only in alias names or in spacing are
the same test, and a real change (a series, a key, a threshold, the structure) is a new one.
Attach and the language are the Setup Lab ones: `setup_context.attach_bindings` (the only call to
`attach_context`) and `compile_expr` with the canonical names as context sources. The language
is three-valued: a missing value never makes the condition true, also under `not` and windows.
A null gate is false on that bar, and is counted by reason. The gate is keyed by bar timestamp.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli.spine import reserve, setup_context
from alpha_core import DataError
from alpha_data.context import derived
from alpha_data.context.attach import AttachResult, Binding
from alpha_study.setup.context import check_aliases, parse_binding, spells, used_aliases
from alpha_study.setup.expr import compile_expr

UNDEFINED_REASON = "expression-undefined"


@dataclass(frozen=True)
class Canon:
    """The alias-free form of `context` and `when`: what the identity and the gate are built on."""

    bindings: dict[str, Binding]
    when: str


@dataclass(frozen=True)
class Gate:
    by_ts: dict[datetime, bool]
    true_bars: int
    false_bars: int
    null_reasons: dict[str, int]
    spells: int
    span: dict[str, Any] | None
    attach: AttachResult
    stale_days: dict[str, int]
    fingerprint: str


@lru_cache(maxsize=256)
def _canon(items: tuple[tuple[str, str], ...], when: str) -> Canon:
    context = dict(items)
    check_aliases(context, ())  # plain lowercase names; never a price source or a function
    parsed = {alias: Binding(*parse_binding(alias, text)) for alias, text in context.items()}
    for binding in parsed.values():
        derived.series_source(binding.series)  # raises for an unknown series and lists them
    aliases = frozenset(context)
    if compile_expr(when, aliases).kind != "boolean":
        raise DataError(f"when {when!r} must be a true/false condition, for example es_pos > 0.8")
    unread = sorted(aliases - used_aliases(when, aliases))
    if unread:
        raise DataError(f"when does not read the declared context alias(es) {unread}")
    texts = sorted({f"{b.series}@{b.key}" for b in parsed.values()})
    names = {text: f"c{i}" for i, text in enumerate(texts)}
    rename = {alias: names[f"{b.series}@{b.key}"] for alias, b in parsed.items()}
    tree = ast.parse(when, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in rename:
            node.id = rename[node.id]
    bindings = {name: Binding(*text.split("@", 1)) for text, name in names.items()}
    return Canon(bindings, ast.unparse(tree))


def canon(context: Mapping[str, str], when: str) -> Canon:
    """Validate and canonicalise; raises DataError (or ValueError for a bad alias) with the why."""
    try:
        return _canon(tuple(sorted(context.items())), when.strip())
    except (SyntaxError, RecursionError, MemoryError) as exc:
        raise DataError(f"when {when!r} is not a valid condition") from exc


def check_context(context: Mapping[str, str] | None, when: str | None) -> None:
    """Spec-time checks. Raises ValueError (so pydantic reports it) with a clear message."""
    try:
        if context is None:
            if when is not None:
                raise DataError("when needs a context table that names its aliases")
            return
        if when is None:
            raise DataError("context needs a when condition that uses its aliases")
        canon(context, when)
    except DataError as exc:
        raise ValueError(str(exc)) from exc


def canonical_fields(context: Mapping[str, str], when: str) -> dict[str, Any]:
    """The `context` and `when` keys of a spec's canonical bytes (its hash input)."""
    form = canon(context, when)
    return {
        "context": {n: f"{b.series}@{b.key}" for n, b in form.bindings.items()},
        "when": form.when,
    }


def context_fingerprint(attach: AttachResult, stale_days: Mapping[str, int], when: str) -> str:
    """sha256 of the used rows, recipe, staleness limits and canonical `when`; no table hash."""
    payload = {
        "used_rows_sha256": dict(sorted(attach.used_rows_sha256.items())),
        "recipe": attach.recipe,
        "stale_days": dict(sorted(stale_days.items())),
        "when": when,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _null_reasons(frame: pl.DataFrame, gate: pl.Series, aliases: list[str]) -> dict[str, int]:
    """Why each null gate bar is null: the first missing series' reason, else the expression."""
    reason = pl.coalesce(
        *(
            pl.when(pl.col(f"ctx_{a}").is_null()).then(
                pl.col(f"ctx_{a}_reason").fill_null(setup_context.WARM_UP)
            )
            for a in aliases
        ),
        pl.lit(UNDEFINED_REASON),
    )
    nulls = frame.with_columns(gate.alias("_gate")).filter(pl.col("_gate").is_null())
    counts = nulls.select(reason.alias("r"))["r"].value_counts()
    return {str(k): int(n) for k, n in sorted(counts.iter_rows())}


def build_gate(
    bars: pl.DataFrame,
    *,
    context: Mapping[str, str],
    when: str,
    calendar: str | None,
    data_dir: Path,
    cutoff: datetime = reserve.CUTOFF,
    symbol: str | None = None,
) -> Gate:
    """The gate of one asset: a boolean per bar timestamp, with null counts and the fingerprint."""
    form = canon(context, when)
    attach = setup_context.attach_bindings(
        bars.sort("ts"),
        form.bindings,
        calendar=calendar,
        home=data_dir,
        symbol=symbol,
        cutoff=cutoff,
    )
    frame, aliases = attach.frame, sorted(form.bindings)
    raw = frame.select(compile_expr(form.when, frozenset(aliases)).expr.alias("gate"))["gate"]
    values: list[bool | None] = raw.to_list()
    limits = {
        a: derived.STALE_DAYS[derived.series_source(b.series)] for a, b in form.bindings.items()
    }
    return Gate(
        by_ts=dict(zip(frame["ts"].to_list(), (v is True for v in values), strict=True)),
        true_bars=sum(v is True for v in values),
        false_bars=sum(v is False for v in values),
        null_reasons=_null_reasons(frame, raw, aliases),
        spells=spells(values),
        span=setup_context.span(frame, aliases),
        attach=attach,
        stale_days=limits,
        fingerprint=context_fingerprint(attach, limits, form.when),
    )
