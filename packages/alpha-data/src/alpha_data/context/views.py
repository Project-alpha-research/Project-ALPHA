"""Pure vintage views and atomic local storage for macro reference data."""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data._atomic import publish, write_text

SCHEMA = {
    "series_id": pl.String,
    "obs_date": pl.Date,
    "value": pl.Float64,
    "known_from": pl.Date,
    "known_until": pl.Date,
}
METADATA_FIELDS = ("title", "units", "frequency", "seasonal_adjustment", "last_updated")
LICENCE_NOTE = (
    "FRED data; some series are copyrighted by their providers and are for personal use only"
)


def series_path(series_id: str, data_dir: Path) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", series_id):
        raise DataError("invalid FRED series_id; use letters, digits, underscore or hyphen")
    return data_dir / "context" / "fred" / f"{series_id}.parquet"


def validate(df: pl.DataFrame) -> None:
    if dict(df.schema) != SCHEMA:
        raise DataError("invalid FRED vintage schema")
    if any(df[c].null_count() for c in ("series_id", "obs_date", "known_from")):
        raise DataError("FRED vintage identity dates cannot be null")
    if df.filter(pl.col("value").is_not_null() & ~pl.col("value").is_finite()).height:
        raise DataError("FRED values must be finite or null")
    if df.filter(pl.col("known_until") < pl.col("known_from")).height:
        raise DataError("FRED real-time period ends before it starts")
    if df.select("series_id", "obs_date", "known_from").is_duplicated().any():
        raise DataError("conflicting or duplicate FRED vintage")
    ordered = df.sort("series_id", "obs_date", "known_from")
    next_start = pl.col("known_from").shift(-1).over("series_id", "obs_date")
    if ordered.filter(
        next_start.is_not_null()
        & (pl.col("known_until").is_null() | (pl.col("known_until") >= next_start))
    ).height:
        raise DataError("overlapping FRED vintage periods")


def as_known(df: pl.DataFrame, *, as_of: date) -> pl.DataFrame:
    """One vintage per observation: greatest publication date no later than as_of."""
    validate(df)
    return (
        df.filter(pl.col("known_from") <= as_of)
        .sort("known_from")
        .unique(subset=["series_id", "obs_date"], keep="last")
        .sort("series_id", "obs_date")
    )


def first_release(df: pl.DataFrame) -> pl.DataFrame:
    """Explicit first-publication view; no implicit historical cutoff."""
    validate(df)
    return (
        df.sort("known_from")
        .unique(subset=["series_id", "obs_date"], keep="first")
        .sort("series_id", "obs_date")
    )


def latest(df: pl.DataFrame) -> pl.DataFrame:
    """Explicit current-vintage view; includes revisions regardless of publication date."""
    validate(df)
    return df.filter(pl.col("known_until").is_null()).sort("series_id", "obs_date")


def metadata_fields(metadata: dict[str, Any]) -> dict[str, str]:
    if any(
        not isinstance(metadata.get(k), str) or not metadata[k].strip() for k in METADATA_FIELDS
    ):
        raise DataError(
            "FRED series metadata requires title, units, frequency, "
            "seasonal_adjustment, last_updated"
        )
    return {k: metadata[k] for k in METADATA_FIELDS}


def store_series(
    series_id: str,
    df: pl.DataFrame,
    metadata: dict[str, Any],
    *,
    data_dir: Path,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Replace parquet and provenance individually atomically; readers verify their binding."""
    path = series_path(series_id, data_dir)
    validate(df)
    if df.is_empty() or df["series_id"].unique().to_list() != [series_id]:
        raise DataError("FRED storage requires nonempty rows for exactly the requested series")
    now = fetched_at if fetched_at is not None else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise DataError("FRED fetched_at must be aware UTC")
    provenance = {
        **metadata_fields(metadata),
        "source": "fred",
        "series_id": series_id,
        "fetched_at": now.isoformat(),
        "rows": df.height,
        "first_obs": str(df["obs_date"].min()),
        "last_obs": str(df["obs_date"].max()),
        "licence_note": LICENCE_NOTE,
        # "vintages": every published version is stored. "approximate": the provider keeps no
        # vintage history, so each value is treated as known the day after its observation date.
        "point_in_time": metadata.get("point_in_time", "vintages"),
    }
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    raw = buffer.getvalue()
    provenance["sha256"] = hashlib.sha256(raw).hexdigest()
    publish(path, lambda tmp: tmp.write_bytes(raw))
    write_text(
        path.with_suffix(".json"), json.dumps(provenance, sort_keys=True, allow_nan=False) + "\n"
    )
    return provenance


def read_provenance(series_id: str, *, data_dir: Path) -> dict[str, Any]:
    path = series_path(series_id, data_dir)
    try:
        raw = path.read_bytes()
        provenance = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DataError(f"missing or unreadable FRED series/provenance: {series_id}") from None
    if (
        not isinstance(provenance, dict)
        or provenance.get("source") != "fred"
        or provenance.get("series_id") != series_id
    ):
        raise DataError("invalid FRED provenance identity")
    if provenance.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise DataError("FRED parquet sha256 differs from provenance; re-pull the series")
    metadata_fields(provenance)
    return provenance


def load_series(series_id: str, *, data_dir: Path) -> pl.DataFrame:
    """Read and verify stored vintages without contacting FRED."""
    provenance = read_provenance(series_id, data_dir=data_dir)
    raw = series_path(series_id, data_dir).read_bytes()
    if hashlib.sha256(raw).hexdigest() != provenance["sha256"]:
        raise DataError("FRED parquet changed during read; retry")
    try:
        df = pl.read_parquet(io.BytesIO(raw))
    except pl.exceptions.PolarsError:
        raise DataError("invalid FRED parquet") from None
    validate(df)
    if df.height != provenance.get("rows") or df["series_id"].unique().to_list() != [series_id]:
        raise DataError("FRED rows differ from provenance")
    return df
