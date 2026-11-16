"""Atomic hash-bound event tables; every read requires an aware UTC cutoff."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data._atomic import publish, write_text

type Schema = dict[str, Any]

TIME = pl.Datetime("us", "UTC")
FILINGS_SCHEMA: Schema = dict(
    cik=pl.String,
    ticker=pl.String,
    accession=pl.String,
    form=pl.String,
    filing_date=pl.Date,
    report_date=pl.Date,
    accepted_at=TIME,
    items=pl.String,
    primary_document=pl.String,
    known_from=TIME,
)
INSIDER_SCHEMA: Schema = dict(
    cik=pl.String,
    accession=pl.String,
    form=pl.String,
    owner_cik=pl.String,
    owner_name=pl.String,
    is_director=pl.Boolean,
    is_officer=pl.Boolean,
    officer_title=pl.String,
    is_ten_percent=pl.Boolean,
    derivative=pl.Boolean,
    security_title=pl.String,
    transaction_date=pl.Date,
    code=pl.String,
    shares=pl.Float64,
    price=pl.Float64,
    acquired_disposed=pl.String,
    shares_after=pl.Float64,
    known_from=TIME,
)
FUNDING_SCHEMA: Schema = dict(
    symbol=pl.String,
    funding_time=TIME,
    funding_rate=pl.Float64,
    interval_hours=pl.Int32,
    known_from=TIME,
)
METRICS_SCHEMA: Schema = dict(
    symbol=pl.String,
    ts=TIME,
    open_interest=pl.Float64,
    open_interest_value=pl.Float64,
    top_trader_account_ratio=pl.Float64,
    top_trader_position_ratio=pl.Float64,
    global_account_ratio=pl.Float64,
    taker_buy_sell_ratio=pl.Float64,
    known_from=TIME,
)


def utc_time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise DataError("event timestamp must be aware UTC")
    return value


def day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        raise DataError("invalid event date; expected YYYY-MM-DD") from None


def number(value: str | None, *, nullable: bool = False) -> float | None:
    if nullable and value in {None, ""}:
        return None
    try:
        result = float(value) if value is not None else float("nan")
    except (TypeError, ValueError):
        raise DataError("event number must be finite") from None
    if not math.isfinite(result):
        raise DataError("event number must be finite")
    return result


def cik10(value: object) -> str:
    if not re.fullmatch(r"[0-9]{1,10}", str(value)) or int(str(value)) == 0:
        raise DataError("CIK must contain 1 to 10 digits and be positive")
    return str(value).zfill(10)


def _validate(df: pl.DataFrame, schema: Schema) -> None:
    if dict(df.schema) != schema or df.schema.get("known_from") != TIME:
        raise DataError("invalid event schema")
    if df["known_from"].null_count():
        raise DataError("event known_from cannot be null")
    for name, dtype in df.schema.items():
        if dtype in {pl.Float32, pl.Float64} and df[name].drop_nulls().is_finite().not_().any():
            raise DataError("event numbers must be finite or null")


def as_known_events(df: pl.DataFrame, *, as_of: datetime) -> pl.DataFrame:
    utc_time(as_of)
    _validate(df, dict(df.schema))
    return df.filter(pl.col("known_from") <= as_of)


def store_events(
    path: Path, df: pl.DataFrame, provenance: dict[str, Any], *, schema: Schema
) -> dict[str, Any]:
    """Publish each file atomically; a torn pair fails its hash check on read."""
    _validate(df, schema)
    _provenance(provenance)
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    raw = buffer.getvalue()
    meta = {**provenance, "rows": df.height, "sha256": hashlib.sha256(raw).hexdigest()}
    serialized = json.dumps(meta, sort_keys=True, allow_nan=False) + "\n"
    publish(path, lambda tmp: tmp.write_bytes(raw))
    write_text(path.with_suffix(".json"), serialized)
    return meta


def _provenance(meta: dict[str, Any]) -> None:
    try:
        utc_time(datetime.fromisoformat(meta["fetched_at"]))
    except (KeyError, TypeError, ValueError):
        raise DataError("event provenance requires an aware UTC fetched_at") from None
    if not isinstance(meta.get("source"), str) or not meta["source"]:
        raise DataError("event provenance requires source")


def load_events(path: Path, *, source: str, schema: Schema) -> pl.DataFrame:
    try:
        raw = path.read_bytes()
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DataError(f"not found: {path}") from None
    except (OSError, ValueError):
        raise DataError(f"unreadable event table/provenance: {path}") from None
    if not isinstance(meta, dict) or meta.get("source") != source:
        raise DataError("invalid event provenance source")
    _provenance(meta)
    if hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
        raise DataError("event parquet sha256 differs from provenance")
    try:
        df = pl.read_parquet(io.BytesIO(raw))
    except pl.exceptions.PolarsError:
        raise DataError("invalid event parquet") from None
    _validate(df, schema)
    if type(meta.get("rows")) is not int or df.height != meta["rows"]:
        raise DataError("event rows differ from provenance")
    return df


def retain_partitions(path: Path, incoming: pl.DataFrame, *, source: str, key: str) -> pl.DataFrame:
    """Retain previously acquired immutable groups, including repeated transactions within one."""
    if not path.exists() and not path.with_suffix(".json").exists():
        return incoming
    previous = load_events(path, source=source, schema=dict(incoming.schema))
    for identity in incoming[key].unique():
        before = previous.filter(pl.col(key) == identity)
        after = incoming.filter(pl.col(key) == identity)
        if before.height and not before.sort(before.columns).equals(after.sort(after.columns)):
            raise DataError(f"revised {source} event partition: {identity}")
    return pl.concat([previous.filter(~pl.col(key).is_in(incoming[key].implode())), incoming])
