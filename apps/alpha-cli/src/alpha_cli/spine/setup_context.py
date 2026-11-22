"""Context series on setup bars: the one call to `attach_context`, honest counts and identity.

A spec's `[context]` table names series by alias. This module attaches them to the bars with the
spine reserve cutoff and hands the study code plain `ctx_<alias>` columns. The data fingerprint of
a context spec holds the hash of the rows used and the recipe version, never a table file hash, so
rows added after the reserved day change nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli import _runner
from alpha_cli.spine import reserve
from alpha_cli.spine.pattern_context import PATTERN_SERIES, add_patterns
from alpha_cli.spine.stores import ResolvedAsset
from alpha_core import DataError
from alpha_data.context import derived
from alpha_data.context.attach import SELF, AttachResult, Binding, attach_context
from alpha_data.timeframe import DAILY
from alpha_study.setup.context import condition_counts, parse_binding

SHORT = "short-context-history"
SHORT_YEARS = 3
WARM_UP = "series-warm-up"
REASONS = ("not-yet-known", "stale", derived.UNVERIFIED, WARM_UP)
FRAME_SCHEMA: dict[str, Any] = {
    "ts": pl.Datetime("us", "UTC"),
    **dict.fromkeys(("open", "high", "low", "close", "volume"), pl.Float64),
}


def frame_of(bars: list[Any]) -> pl.DataFrame:
    return pl.DataFrame(
        {k: [getattr(b, k) for b in bars] for k in FRAME_SCHEMA}, schema=FRAME_SCHEMA
    )


def bindings(spec: Any) -> dict[str, Binding]:
    return {a: Binding(*parse_binding(a, text)) for a, text in spec.context.items()}


def check_series(spec: Any) -> None:
    """Fail loud before any data loads when a declared series does not exist."""
    for binding in bindings(spec).values():
        if binding.series in PATTERN_SERIES:
            if binding.key != SELF:
                raise DataError(f"pattern series {binding.series!r} takes the key SELF")
            continue
        try:
            derived.series_source(binding.series)
        except DataError as exc:
            raise DataError(f"{exc}; chart-pattern series: {sorted(PATTERN_SERIES)}") from exc


def calendar_of(resolved: ResolvedAsset) -> str | None:
    store = resolved.daily_store()
    return _runner._calendar_for(resolved.symbol, store.read_provenance(resolved.symbol))


def attach_bindings(
    frame: pl.DataFrame,
    binds: Mapping[str, Binding],
    *,
    calendar: str | None,
    home: Path,
    symbol: str | None,
    cutoff: datetime = reserve.CUTOFF,
) -> AttachResult:
    """The one call to `attach_context` for Setup Lab and the rule gate: daily, reserve cutoff."""
    tables = {a: b for a, b in binds.items() if b.series not in PATTERN_SERIES}
    result = attach_context(
        frame,
        timeframe=DAILY,
        calendar=calendar,
        bindings=tables,
        data_dir=home,
        cutoff=cutoff,
        symbol=symbol,
    )
    patterns = {a: b.series for a, b in binds.items() if b.series in PATTERN_SERIES}
    return add_patterns(result, patterns, symbol) if patterns else result


def attach(spec: Any, bars: list[Any], resolved: ResolvedAsset, home: Path) -> AttachResult:
    """Attach the declared series to the bars; nothing after the reserve cutoff is read."""
    return attach_bindings(
        frame_of(bars),
        bindings(spec),
        calendar=calendar_of(resolved),
        home=home,
        symbol=resolved.symbol,
    )


def fingerprint(result: AttachResult) -> str:
    """Rows used plus the recipe: the context part of a data identity."""
    payload = json.dumps({"used": result.used_rows_sha256, "recipe": result.recipe}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _nulls(frame: pl.DataFrame, alias: str) -> dict[str, int]:
    missing = frame.filter(pl.col(f"ctx_{alias}").is_null())
    reasons = missing[f"ctx_{alias}_reason"].fill_null(WARM_UP).to_list()
    return {r: reasons.count(r) for r in REASONS if r in reasons}


def span(frame: pl.DataFrame, aliases: list[str]) -> dict[str, Any] | None:
    ok = frame.with_row_index("i").filter(
        pl.all_horizontal(pl.col(f"ctx_{a}").is_not_null() for a in aliases)
    )
    if not ok.height:
        return None
    first, last = ok["ts"][0], ok["ts"][-1]
    return dict(
        first=first.date().isoformat(),
        last=last.date().isoformat(),
        bars=int(ok["i"][-1] - ok["i"][0] + 1),
        years=round((last - first) / timedelta(days=365.25), 2),
    )


def block(spec: Any, result: AttachResult) -> dict[str, Any]:
    """What the context did on one asset: nulls by reason, span, true bars and spells."""
    frame, aliases = result.frame, list(spec.context)
    return dict(
        series=dict(spec.context),
        recipe=result.recipe,
        used_rows_sha256=result.used_rows_sha256,
        source_table_sha256=result.source_table_sha256,
        notes={a: n for a, n in result.notes.items() if n},
        bars=frame.height,
        null_by_reason={a: _nulls(frame, a) for a in aliases},
        with_value={a: frame.height - frame[f"ctx_{a}"].null_count() for a in aliases},
        span=span(frame, aliases),
        conditions=condition_counts(spec, frame),
    )


def labels(info: dict[str, Any]) -> list[str]:
    span = info["span"]
    return [SHORT] if span is None or span["years"] < SHORT_YEARS else []


def sentence(info: dict[str, Any], asset: str | None = None) -> str:
    """Plain words; a reading of stored data, no verdict."""
    span, who = info["span"], f"{asset}: " if asset else ""
    if span is None:
        return who + "The condition data has no value on any bar, so no condition could be true."
    text = (
        f"{who}The condition data covers {span['first'][:7]} to {span['last'][:7]} "
        f"(about {span['years']:.1f} years)."
    )
    if span["years"] < SHORT_YEARS:
        text += f" That is under {SHORT_YEARS} years: a short history."
    for name, count in info["conditions"].items():
        label = name.removeprefix("filter:")
        text += (
            f" Condition {label} was true on {count['true_bars']} of {span['bars']} days, "
            f"in {count['spells']} separate spells (a weekly value repeats on daily bars, "
            "so days overstate the sample)."
        )
    gaps: dict[str, int] = {}
    for reasons in info["null_by_reason"].values():
        for reason, n in reasons.items():
            gaps[reason] = gaps.get(reason, 0) + n
    if gaps:
        text += " Bars with no value: " + ", ".join(f"{k} {v}" for k, v in gaps.items()) + "."
    return text + " The reading uses this span only."


def annotate(summary: dict[str, Any], spec: Any, manifest: dict[str, Any]) -> None:
    """Add the stored context block, its label and sentence to a study or trade summary."""
    if not spec.context:
        return
    blocks = {a["asset"]: a["context"] for a in manifest["assets"] if a.get("context")}
    summary["context"] = blocks
    for info in blocks.values():
        summary["labels"].extend(x for x in labels(info) if x not in summary["labels"])
    many = len(blocks) > 1
    summary["reading"] += "".join(
        " " + sentence(info, asset if many else None) for asset, info in blocks.items()
    )


def control_span(spec: Any, result: AttachResult, bars: list[Any], warmup: int) -> tuple[int, int]:
    """Bars `[start, stop)` where random controls may sit: this asset's own context span.

    Events need every declared series to have a value, so controls start no earlier than the
    first such bar and end at the last one. A gap inside the span stays drawable (see the docs).
    """
    if result.frame.height != len(bars):
        raise DataError("context frame and bars differ in length")
    ok = result.frame.with_row_index("i").filter(
        pl.all_horizontal(pl.col(f"ctx_{a}").is_not_null() for a in spec.context)
    )
    if not ok.height:
        return len(bars), len(bars)
    return max(warmup, int(ok["i"][0])), int(ok["i"][-1]) + 1
