"""FINRA daily short sale volume (consolidated NMS file) as point-in-time context rows."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data.context.events import TIME, load_events, store_events, utc_time
from alpha_data.context.free_http import Client, merge_without_revision

SOURCE = "finra-short-volume"
CAVEAT = (
    "FINRA facilities only: these files cover trades reported to FINRA trade reporting facilities, "
    "not all exchange volume, so they understate total volume and short volume."
)
KNOWN_RULE = (
    "FINRA publishes the file after the trading day. known_from is the next UTC midnight "
    "(00:00 UTC the day after the trade date), later than the publication time."
)
SCHEMA: dict[str, Any] = dict(
    symbol=pl.String,
    trade_date=pl.Date,
    short_volume=pl.Float64,
    short_exempt_volume=pl.Float64,
    total_volume=pl.Float64,
    markets=pl.String,
    known_from=TIME,
)
_HEADER = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market"
_MAX_DAYS = 400


def table_path(data_dir: Path, symbol: str) -> Path:
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,9}", symbol):
        raise DataError("invalid symbol; expected capital letters or digits, e.g. SPY")
    return data_dir / "context/finra/short_volume" / f"{symbol}.parquet"


def known_from(trade_date: date) -> datetime:
    return datetime.combine(trade_date + timedelta(days=1), time(0), tzinfo=UTC)


def _volume(raw: str, field: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise DataError(f"FINRA {field} must be a number, got {raw!r}") from None
    if not math.isfinite(value) or value < 0:
        raise DataError(f"FINRA {field} must be finite and not negative, got {raw!r}")
    return value


def map_file(raw: bytes, trade_date: date, symbols: set[str] | None) -> pl.DataFrame:
    """Parse one day's pipe file; the last line is the provider's record count and must agree."""
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise DataError("FINRA file is not UTF-8 text") from None
    if not lines or lines[0].strip() != _HEADER:
        raise DataError(f"FINRA header changed: expected {_HEADER!r}")
    body, trailer = lines[1:-1], lines[-1].strip() if len(lines) > 1 else ""
    if not trailer.isdigit() or int(trailer) != len(body):
        raise DataError(f"FINRA record count {trailer!r} differs from {len(body)} data rows")
    stamp, seen, rows = trade_date.strftime("%Y%m%d"), set(), []
    for line in body:
        parts = line.split("|")
        if len(parts) != 6:
            raise DataError(f"FINRA row needs 6 fields, got {len(parts)}: {line[:60]!r}")
        day, symbol, short, exempt, total, markets = parts
        if day != stamp:
            raise DataError(f"FINRA Date {day!r} differs from the file date {stamp}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./+\-]{0,14}", symbol):
            raise DataError(f"FINRA Symbol {symbol!r} is not a ticker")  # files hold AAC/WS, ABCp
        if symbol in seen:
            raise DataError(f"FINRA Symbol {symbol} appears twice on {trade_date}")
        seen.add(symbol)
        if not re.fullmatch(r"[A-Z](,[A-Z])*", markets):
            raise DataError(f"FINRA Market must be letters separated by commas, got {markets!r}")
        if symbols is not None and symbol not in symbols:
            continue
        values = (
            _volume(short, "ShortVolume"),
            _volume(exempt, "ShortExemptVolume"),
            _volume(total, "TotalVolume"),
        )
        if values[0] > values[2]:
            raise DataError(f"FINRA TotalVolume is below ShortVolume for {symbol} on {trade_date}")
        rows.append((symbol, trade_date, *values, markets, known_from(trade_date)))
    return pl.DataFrame(rows, schema=SCHEMA, orient="row").sort("symbol")


def _days(start: date, end: date) -> list[date]:
    if end < start or (end - start).days >= _MAX_DAYS:
        raise DataError(f"bad range: need start <= end and under {_MAX_DAYS} days")
    span = (start + timedelta(days=n) for n in range((end - start).days + 1))
    return [day for day in span if day.weekday() < 5]


def pull_short_volume(
    *,
    data_dir: Path,
    symbols: list[str],
    start: date,
    end: date,
    fetched_at: datetime,
    client: Client | None = None,
) -> dict[str, Any]:
    """Fetch every day first, then store; a missing day is listed, a bad file stores nothing."""
    utc_time(fetched_at)
    client = client or Client()
    wanted = list(dict.fromkeys(symbols))
    paths = {symbol: table_path(data_dir, symbol) for symbol in wanted}
    frames: list[pl.DataFrame] = []
    missing: list[str] = []
    for day in _days(start, end):
        url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day:%Y%m%d}.txt"
        status, raw = client.get(url, "FINRA")
        if status in {403, 404}:  # the host answers 403 for a day with no file
            missing.append(str(day))
        elif status != 200:
            raise DataError(f"FINRA HTTP {status} for {day}; nothing was stored")
        else:
            frames.append(map_file(raw, day, set(wanted)))
    if not frames:
        raise DataError(f"FINRA has no file for any weekday from {start} to {end}")
    combined = pl.concat(frames)
    results = []
    for symbol, path in paths.items():
        df = combined.filter(pl.col("symbol") == symbol)
        if df.is_empty():
            raise DataError(f"FINRA files hold no rows for symbol {symbol} from {start} to {end}")
        merged = merge_without_revision(
            path,
            df.sort("trade_date"),
            source=SOURCE,
            schema=SCHEMA,
            key="trade_date",
            label=f"FINRA {symbol}",
        )
        store_events(
            path,
            merged,
            {
                "source": SOURCE,
                "fetched_at": fetched_at.isoformat(),
                "symbol": symbol,
                "file": "CNMSshvol (consolidated NMS)",
                "known_from_rule": KNOWN_RULE,
                "caveat": CAVEAT,
            },
            schema=SCHEMA,
        )
        results.append(_summary(symbol, merged))
    return dict(
        symbols=results,
        rows=sum(item["rows"] for item in results),
        missing_days=missing,
        known_from_rule=KNOWN_RULE,
        caveat=CAVEAT,
    )


def _summary(symbol: str, df: pl.DataFrame) -> dict[str, Any]:
    return dict(
        symbol=symbol,
        rows=df.height,
        first_period=str(df["trade_date"].min()),
        last_period=str(df["trade_date"].max()),
    )


def describe(data_dir: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted((data_dir / "context/finra/short_volume").glob("*.parquet")):
        df = load_events(path, source=SOURCE, schema=SCHEMA)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        out.append(
            {
                "source": SOURCE,
                "key": path.stem,
                **{k: v for k, v in _summary(path.stem, df).items() if k != "symbol"},
                "last_known_from": df.select(pl.col("known_from").max()).item().isoformat(),
                "fetched_at": meta["fetched_at"],
                "caveat": meta["caveat"],
            }
        )
    return out
