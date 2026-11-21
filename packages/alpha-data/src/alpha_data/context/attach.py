"""The one place context values are put onto bars: a backward as-of join on availability.

Rules, in order: read each table hash-checked and keep rows with `known_from` <= cutoff; drop
rows whose period is on or after the reserved day (a filter, not a refusal); derive the series
on the native timeline (`derived.py`); take each bar's decision instant from `bar_known_at`;
join backward and inclusive on `known_eff`; null a value older than its staleness limit and mark
it stale. A cutoff at or after the reserved instant is refused. A null is never filled.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple

import polars as pl

from alpha_core import DataError
from alpha_core.reserve import RESERVED_DAY
from alpha_core.reserve import RESERVED_INSTANT as RESERVED_INSTANT  # re-exported
from alpha_data.context import cftc_cot, derived, finra_short
from alpha_data.context.events import TIME, as_known_events, load_events, utc_time
from alpha_data.sessions import bar_known_at
from alpha_data.timeframe import BarTimeframe

SELF = "SELF"
ALL_NAMES = "ALL"
NOT_YET_KNOWN = "not-yet-known"
STALE = "stale"


class Binding(NamedTuple):
    """`series@key`: the key is declared (a COT market code or a FINRA symbol), never inferred."""

    series: str
    key: str


@dataclass(frozen=True)
class AttachResult:
    frame: pl.DataFrame
    used_rows_sha256: dict[str, str]
    source_table_sha256: dict[str, str]
    recipe: str
    notes: dict[str, str]


@dataclass(frozen=True)
class _Source:
    frame: pl.DataFrame
    tables: dict[str, str]
    note: str


def _read_table(
    path: Path, *, source: str, schema: dict[str, object], cutoff: datetime
) -> pl.DataFrame:
    return as_known_events(load_events(path, source=source, schema=schema), as_of=cutoff)


def _table_hash(path: Path) -> str:
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return str(meta["sha256"])


def _cot_source(key: str, data_dir: Path, cutoff: datetime) -> _Source:
    path = cftc_cot.table_path(data_dir, key)
    rows = _read_table(path, source=cftc_cot.SOURCE, schema=cftc_cot.SCHEMA, cutoff=cutoff)
    rows = rows.filter(pl.col("report_date") < RESERVED_DAY)
    return _Source(rows, {f"{cftc_cot.SOURCE}:{key}": _table_hash(path)}, "")


def _finra_rows(symbol: str, data_dir: Path, cutoff: datetime) -> tuple[pl.DataFrame, Path]:
    path = finra_short.table_path(data_dir, symbol)
    rows = _read_table(path, source=finra_short.SOURCE, schema=finra_short.SCHEMA, cutoff=cutoff)
    return rows.filter(pl.col("trade_date") < RESERVED_DAY), path


def _derive(series: str, key: str, data_dir: Path, cutoff: datetime) -> _Source:
    """The derived series for one binding, with the hashes of the tables it read."""
    kind = derived.series_source(series)
    if kind == "cot":
        source = _cot_source(key, data_dir, cutoff)
        return _Source(derived.derive_cot(source.frame, series), source.tables, "")
    if series != "sv_breadth_z1":
        rows, path = _finra_rows(key, data_dir, cutoff)
        return _Source(
            derived.derive_sv(rows, series), {f"{finra_short.SOURCE}:{key}": _table_hash(path)}, ""
        )
    if key != ALL_NAMES:
        raise DataError(f"sv_breadth_z1 takes the key {ALL_NAMES!r}, not {key!r}")
    folder = finra_short.table_path(data_dir, "X").parent
    names = sorted(p.stem for p in folder.glob("*.parquet"))
    if not names:
        raise DataError("no FINRA short volume tables are stored; breadth has no names")
    z: dict[str, pl.DataFrame] = {}
    tables: dict[str, str] = {}
    for name in names:
        rows, path = _finra_rows(name, data_dir, cutoff)
        z[name] = derived.derive_sv(rows, "sv_ratio_z_60d")
        tables[f"{finra_short.SOURCE}:{name}"] = _table_hash(path)
    return _Source(derived.derive_breadth(z), tables, derived.breadth_label(len(names)))


def _join_one(
    left: pl.DataFrame, series: pl.DataFrame, alias: str, limit: int
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Backward as-of join of one derived series; returns the frame and the rows it used."""
    right = series.sort("known_eff", "period").rename(
        dict(period="_period", value="_value", reason="_reason")
    )
    joined = left.join_asof(right, left_on="_d", right_on="known_eff", strategy="backward")
    age = (pl.col("_d").dt.date() - pl.col("_period")).dt.total_days()
    stale = (age > limit).fill_null(False)
    reason = (
        pl.when(pl.col("_period").is_null())
        .then(pl.lit(NOT_YET_KNOWN))
        .when(stale)
        .then(pl.lit(STALE))
        .otherwise(pl.col("_reason"))
    )
    used = (
        joined.filter(pl.col("_period").is_not_null())
        .select("_period", "known_eff", "_value", "_reason")
        .unique(maintain_order=True)
    )
    out = joined.with_columns(
        pl.when(stale).then(None).otherwise(pl.col("_value")).alias(f"ctx_{alias}"),
        age.alias(f"ctx_{alias}_age_days"),
        stale.alias(f"ctx_{alias}_stale"),
        pl.col("known_eff").alias(f"ctx_{alias}_known_from"),
        reason.alias(f"ctx_{alias}_reason"),
    ).drop("_period", "known_eff", "_value", "_reason")
    return out, used


def _used_hash(alias: str, used: pl.DataFrame) -> str:
    digest = hashlib.sha256()
    for period, known, value, reason in used.sort("_period").iter_rows():
        digest.update(f"{alias}|{period}|{known.isoformat()}|{value!r}|{reason}\n".encode())
    return digest.hexdigest()


def _decision_instants(
    frame: pl.DataFrame, timeframe: BarTimeframe, calendar: str | None
) -> list[datetime]:
    """`bar_known_at` per bar; the one calendar home answers old and new history alike."""
    instants = [
        bar_known_at(ts, timeframe=timeframe, calendar=calendar) for ts in frame["ts"].to_list()
    ]
    if any(b <= a for a, b in zip(instants, instants[1:], strict=False)):
        raise DataError("bars must be strictly increasing in time")
    return instants


def _resolve(binding: Binding, symbol: str | None) -> Binding:
    if binding.key != SELF:
        return binding
    if symbol is None:
        raise DataError("the key SELF needs the bar symbol (pass symbol=...)")
    return Binding(binding.series, symbol)


def attach_context(
    bars: pl.DataFrame,
    *,
    timeframe: BarTimeframe,
    calendar: str | None,
    bindings: Mapping[str, Binding],
    data_dir: Path,
    cutoff: datetime,
    symbol: str | None = None,
) -> AttachResult:
    """Put `ctx_<alias>` columns (value, age, stale, known_from, reason) onto `bars`.

    Callers pass the spine reserve CUTOFF. Bars stamped on or after the reserved day are dropped.
    """
    utc_time(cutoff)
    if cutoff >= RESERVED_INSTANT:
        raise DataError(f"cutoff {cutoff.isoformat()} is at or after the reserved period")
    taken = [c for c in bars.columns if c.startswith("ctx_")]
    if taken:
        raise DataError(f"bars already hold context columns: {taken}")
    frame = bars.filter(pl.col("ts") < RESERVED_INSTANT)
    resolved = {alias: _resolve(raw, symbol) for alias, raw in bindings.items()}
    sources = {alias: _derive(b.series, b.key, data_dir, cutoff) for alias, b in resolved.items()}
    # A derived row is known no earlier than its stored rows; it must also be known by the cutoff.
    sources = {
        alias: _Source(s.frame.filter(pl.col("known_eff") <= cutoff), s.tables, s.note)
        for alias, s in sources.items()
    }
    left = frame.with_columns(
        pl.Series("_d", _decision_instants(frame, timeframe, calendar), dtype=TIME)
    )
    used_hashes: dict[str, str] = {}
    tables: dict[str, str] = {}
    notes: dict[str, str] = {}
    for alias, source in sources.items():
        limit = derived.STALE_DAYS[derived.series_source(resolved[alias].series)]
        left, used = _join_one(left, source.frame, alias, limit)
        used_hashes[alias] = _used_hash(alias, used)
        tables.update(source.tables)
        notes[alias] = source.note
    return AttachResult(left.drop("_d"), used_hashes, tables, derived.RECIPE, notes)


def known_dates(result: AttachResult, alias: str) -> list[date]:
    """Bar dates whose value for `alias` is not null (used by readings that count coverage)."""
    kept = result.frame.filter(pl.col(f"ctx_{alias}").is_not_null())
    return [ts.date() for ts in kept["ts"].to_list()]
