"""The per-bar context gate of a rule spec: attach context, evaluate `when`, key by bar timestamp.

`attach_context` is the only join. `when` is read by the closed causal language of Setup Lab
(`alpha_study.setup.expr.compile_expr`), which has no slot for extra number sources. So each alias
the text uses is renamed to one of its five price source names (open, high, low, close, volume)
and those columns hold the context values; the unused ones hold nulls. This reuses the language
with no edit to its file. A later change should add real extra sources there and drop this step.
At most five aliases can appear in one `when`. A null context value makes the gate false, and is
counted by reason. The gate is a map from bar timestamp to a boolean, never an index.
"""

from __future__ import annotations

import ast
import hashlib
import json
import keyword
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from alpha_core import DataError
from alpha_data.context import derived
from alpha_data.context.attach import AttachResult, Binding, attach_context
from alpha_data.timeframe import DAILY, BarTimeframe
from alpha_study.setup.expr import FUNCTIONS, SOURCES, CompiledExpr, compile_expr

WARMUP_REASON = "warm-up-or-undefined"
UNDEFINED_REASON = "expression-undefined"
SHORT_HISTORY = "short-context-history"
SHORT_SECONDS = 3 * 365.25 * 86400


@dataclass(frozen=True)
class Gate:
    by_ts: dict[datetime, bool]
    null_reasons: dict[str, int]
    first_value: datetime | None
    last_value: datetime | None
    attach: AttachResult
    stale_days: dict[str, int]
    fingerprint: str


def parse_bindings(context: Mapping[str, str]) -> dict[str, Binding]:
    """`{alias: "series@key"}` to bindings; an unknown series or a bad alias is a clear error."""
    out: dict[str, Binding] = {}
    for alias, text in context.items():
        reserved = {*SOURCES, *FUNCTIONS}
        if not alias.isidentifier() or keyword.iskeyword(alias) or alias in reserved:
            raise DataError(
                f"context alias {alias!r} must be a plain name that is not a price source, "
                "a function or a Python keyword"
            )
        series, at, key = text.partition("@")
        if not at or not key.strip():
            raise DataError(f"context {alias!r} must read series@key, for example cot_x@13874A")
        derived.series_source(series)  # raises for an unknown series and lists the known ones
        out[alias] = Binding(series, key.strip())
    return out


def _rename(when: str, aliases: set[str]) -> tuple[str, dict[str, str]]:
    """Rewrite each alias in `when` to a price source name. Returns the text and alias -> source."""
    try:
        tree = ast.parse(when, mode="eval")
    except (SyntaxError, RecursionError, MemoryError, ValueError) as exc:
        raise DataError(f"when {when!r} is not a valid condition") from exc
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    names = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and id(n) not in called]
    used = sorted({n.id for n in names})
    unknown = [name for name in used if name not in aliases]
    if unknown:
        raise DataError(f"when uses unknown alias {unknown}; declared: {sorted(aliases)}")
    if len(used) > len(SOURCES):
        raise DataError(f"when may use at most {len(SOURCES)} aliases; it uses {len(used)}")
    mapping = dict(zip(used, SOURCES, strict=False))
    for node in names:
        node.id = mapping[node.id]
    return ast.unparse(tree), mapping


def compile_when(when: str, aliases: set[str]) -> tuple[CompiledExpr, dict[str, str]]:
    text, mapping = _rename(when, aliases)
    compiled = compile_expr(text)
    if compiled.kind != "boolean":
        raise DataError(f"when {when!r} must be a true/false condition, for example es_pos > 0.8")
    return compiled, mapping


def check_context(context: Mapping[str, str] | None, when: str | None) -> None:
    """Spec-time checks. Raises ValueError (so pydantic reports it) with a clear message."""
    try:
        if context is None:
            if when is not None:
                raise DataError("when needs a context table that names its aliases")
            return
        bindings = parse_bindings(context)
        if when is None:
            raise DataError("context needs a when condition that uses its aliases")
        compile_when(when, set(bindings))
    except DataError as exc:
        raise ValueError(str(exc)) from exc


def context_fingerprint(attach: AttachResult, stale_days: Mapping[str, int], when: str) -> str:
    """sha256 of the used rows, recipe, staleness limits and `when`. Source files are not in it."""
    payload = {
        "used_rows_sha256": dict(sorted(attach.used_rows_sha256.items())),
        "recipe": attach.recipe,
        "stale_days": dict(sorted(stale_days.items())),
        "when": when,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _evaluate(frame: pl.DataFrame, compiled: CompiledExpr, mapping: Mapping[str, str]) -> pl.Series:
    """The compiled condition on the attached frame: true, false or null per bar."""
    columns = {name: pl.lit(None, dtype=pl.Float64).alias(name) for name in SOURCES}
    for alias, source in mapping.items():
        columns[source] = pl.col(f"ctx_{alias}").cast(pl.Float64).alias(source)
    return frame.select(*columns.values()).select(compiled.expr.alias("gate"))["gate"]


def _null_reasons(frame: pl.DataFrame, gate: pl.Series, aliases: list[str]) -> dict[str, int]:
    reason = pl.coalesce(
        *(
            pl.when(pl.col(f"ctx_{a}").is_null()).then(
                pl.col(f"ctx_{a}_reason").fill_null(WARMUP_REASON)
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
    cutoff: datetime,
    symbol: str | None = None,
    timeframe: BarTimeframe = DAILY,
) -> Gate:
    """The gate of one asset: a boolean per bar timestamp, with null counts and the fingerprint."""
    bindings = parse_bindings(context)
    compiled, mapping = compile_when(when, set(bindings))
    attach = attach_context(
        bars.sort("ts"),
        timeframe=timeframe,
        calendar=calendar,
        bindings=bindings,
        data_dir=data_dir,
        cutoff=cutoff,
        symbol=symbol,
    )
    frame = attach.frame
    raw = _evaluate(frame, compiled, mapping)
    stamps: list[datetime] = frame["ts"].to_list()
    flags = raw.fill_null(False).to_list()
    known = [ts for ts, value in zip(stamps, raw.to_list(), strict=True) if value is not None]
    limits = {
        alias: derived.STALE_DAYS[derived.series_source(b.series)] for alias, b in bindings.items()
    }
    return Gate(
        by_ts=dict(zip(stamps, flags, strict=True)),
        null_reasons=_null_reasons(frame, raw, sorted(mapping)),
        first_value=known[0] if known else None,
        last_value=known[-1] if known else None,
        attach=attach,
        stale_days=limits,
        fingerprint=context_fingerprint(attach, limits, when),
    )


def spells(gate: Mapping[datetime, bool]) -> int:
    """Separate runs of true bars, in time order."""
    flags = [gate[ts] for ts in sorted(gate)]
    return sum(1 for i, on in enumerate(flags) if on and (i == 0 or not flags[i - 1]))


def short_history(gate: Gate) -> bool:
    """True when the span with a usable context value is under three years."""
    if gate.first_value is None or gate.last_value is None:
        return True
    return (gate.last_value - gate.first_value).total_seconds() < SHORT_SECONDS
