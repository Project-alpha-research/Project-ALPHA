"""Checksummed USD-M funding and metrics archives, separate from the crypto bar store."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data._atomic import publish
from alpha_data.context.events import (
    FUNDING_SCHEMA,
    METRICS_SCHEMA,
    day,
    load_events,
    number,
    store_events,
    utc_time,
)
from alpha_data.crypto.providers.binance import (
    archive_checksum_sha256,
    archive_csv_member,
    fetch_binance_archive,
    fetch_binance_checksum,
    verify_archive_checksum,
)


def table_path(data_dir: Path, kind: str, symbol: str) -> Path:
    if kind not in {"funding", "metrics"}:
        raise DataError("Binance kind must be funding or metrics")
    if not re.fullmatch(r"[A-Z0-9_-]{1,128}", symbol):
        raise DataError("invalid Binance symbol")
    return data_dir / "context/binance/um" / kind / f"{symbol}.parquet"


def map_binance_csv(kind: str, csv_bytes: bytes) -> pl.DataFrame:
    """All Binance provider field names and clock conventions are confined here."""
    table_path(Path("."), kind, "CHECK")
    funding = {
        "calc_time": "funding_time",
        "funding_interval_hours": "interval_hours",
        "last_funding_rate": "funding_rate",
    }
    metrics = dict(
        create_time="ts",
        symbol="symbol",
        sum_open_interest="open_interest",
        sum_open_interest_value="open_interest_value",
        count_toptrader_long_short_ratio="top_trader_account_ratio",
        sum_toptrader_long_short_ratio="top_trader_position_ratio",
        count_long_short_ratio="global_account_ratio",
        sum_taker_long_short_vol_ratio="taker_buy_sell_ratio",
    )
    mapping = funding if kind == "funding" else metrics
    try:
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")), strict=True)
        headers = reader.fieldnames or []
        allowed = [set(mapping)]
        if kind == "funding":
            allowed.append(set(mapping) - {"funding_interval_hours"})
        if len(headers) != len(set(headers)) or set(headers) not in allowed:
            raise DataError(f"unknown Binance {kind} columns: {headers}")
        rows = []
        for raw in reader:
            if None in raw or any(value is None for value in raw.values()):
                raise DataError("Binance CSV row length differs from header")
            mapped = {mapping[key]: value for key, value in raw.items()}
            if kind == "funding":
                ts = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                    milliseconds=int(mapped["funding_time"])
                )
                interval = mapped.get("interval_hours")
                interval = int(interval) if interval else None
                if interval is not None and not 0 < interval < 2**31:
                    raise DataError("invalid Binance funding interval")
                row: dict[str, Any] = dict(
                    symbol=None,
                    funding_time=ts,
                    funding_rate=number(mapped["funding_rate"]),
                    interval_hours=interval,
                    known_from=ts,
                )
            else:
                ts = datetime.strptime(mapped["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                if ts.strftime("%Y-%m-%d %H:%M:%S") != mapped["ts"]:
                    raise DataError("invalid Binance metrics timestamp")
                table_path(Path("."), kind, mapped["symbol"])
                row = {
                    key: number(value, nullable=True)
                    for key, value in mapped.items()
                    if key not in {"ts", "symbol"}
                }
                row.update(symbol=mapped["symbol"], ts=ts, known_from=ts + timedelta(minutes=5))
            rows.append(row)
    except (UnicodeDecodeError, csv.Error, ValueError, OverflowError) as exc:
        raise DataError(f"invalid Binance {kind} CSV: {type(exc).__name__}") from None
    if not rows:
        raise DataError("Binance CSV contains no rows")
    schema = FUNDING_SCHEMA if kind == "funding" else METRICS_SCHEMA
    return pl.DataFrame(rows, schema=schema)


def periods(kind: str, start: str, end: str) -> list[str]:
    table_path(Path("."), kind, "CHECK")
    try:
        lower, upper = (day(v + "-01" if kind == "funding" else v) for v in (start, end))
        if upper < lower or (kind == "metrics" and (upper - lower).days >= 400):
            raise DataError("BAD_RANGE: reversed range or more than 400 metrics days")
        if kind == "funding":
            first, last = lower.year * 12 + lower.month - 1, upper.year * 12 + upper.month - 1
            return [f"{value // 12:04d}-{value % 12 + 1:02d}" for value in range(first, last + 1)]
        return [(lower + timedelta(days=i)).isoformat() for i in range((upper - lower).days + 1)]
    except (ValueError, DataError):
        raise DataError(
            "BAD_RANGE: expected ordered months or dates; metrics limit is 400 days"
        ) from None


def _merge(frames: list[pl.DataFrame], kind: str, symbol: str) -> pl.DataFrame:
    key = "funding_time" if kind == "funding" else "ts"
    merged = pl.concat(frames).unique(maintain_order=True).sort(key)
    duplicated = merged.filter(pl.col(key).is_duplicated())
    if duplicated.height:
        raise DataError(f"Binance revised {kind} {symbol} at {duplicated[key][0]}")
    if merged["symbol"].unique().to_list() != [symbol]:
        raise DataError("Binance table symbol differs from requested symbol")
    return merged


def pull_binance(
    *,
    data_dir: Path,
    symbol: str,
    kind: str,
    start: str,
    end: str,
    fetched_at: datetime,
    fetch_checksum: Callable[[str], bytes] = fetch_binance_checksum,
    fetch_archive: Callable[[str], bytes] = fetch_binance_archive,
) -> dict[str, Any]:
    utc_time(fetched_at)
    path = table_path(data_dir, kind, symbol)
    requested = periods(kind, start, end)
    schema = FUNDING_SCHEMA if kind == "funding" else METRICS_SCHEMA
    family, frequency = ("fundingRate", "monthly") if kind == "funding" else ("metrics", "daily")
    frames, pending, missing = [], [], []
    fetched = cached = 0
    for period in requested:
        filename = f"{symbol}-{family}-{period}.zip"
        url = (
            f"https://data.binance.vision/data/futures/um/{frequency}/{family}/{symbol}/{filename}"
        )
        cache = data_dir / "context/binance/raw" / kind / symbol / filename
        try:
            checksum = fetch_checksum(url + ".CHECKSUM")
            expected = archive_checksum_sha256(checksum)
            raw = cache.read_bytes() if cache.exists() else None
            hit = raw is not None and hashlib.sha256(raw).hexdigest() == expected
            if not hit:
                raw = fetch_archive(url)
            assert raw is not None
            verify_archive_checksum(raw, checksum)
        except DataError as exc:
            if str(exc) != "Binance archive request failed with HTTP 404":
                raise
            missing.append(period)
            continue
        df = map_binance_csv(kind, archive_csv_member(raw))
        if kind == "funding":
            df = df.with_columns(pl.lit(symbol).alias("symbol"))
        key = "funding_time" if kind == "funding" else "ts"
        pattern = "%Y-%m" if kind == "funding" else "%Y-%m-%d"
        if df.filter(pl.col(key).dt.strftime(pattern) != period).height:
            raise DataError("Binance archive contains rows outside requested period")
        frames.append(df)
        cached += int(hit)
        fetched += int(not hit)
        if not hit:
            pending.append((cache, raw))
    if not frames:
        raise DataError("all Binance periods missing")
    if path.exists() or path.with_suffix(".json").exists():
        frames.insert(0, load_events(path, source="binance", schema=schema))
    merged = _merge(frames, kind, symbol)
    for cache, raw in pending:
        publish(cache, partial(Path.write_bytes, data=raw))
    store_events(
        path,
        merged,
        {
            "source": "binance",
            "fetched_at": fetched_at.isoformat(),
            "symbol": symbol,
            "kind": kind,
            "market": "um",
        },
        schema=schema,
    )
    return dict(
        symbol=symbol,
        kind=kind,
        periods=requested,
        fetched=fetched,
        cached=cached,
        missing=missing,
        rows=merged.height,
    )
