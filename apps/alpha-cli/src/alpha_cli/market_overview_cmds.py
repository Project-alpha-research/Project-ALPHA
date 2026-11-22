"""``alpha data market-overview``: stored bars as a read-only grid of small-multiple summaries.

A display of stored market data, not a research result. It reads stored bars through the same
point-in-time reader the chart uses, writes nothing and never touches the network, the ledger
or any run. Work is bounded by ``MAX_ASSETS_SCANNED`` and ``MAX_BARS_READ``.
"""

from __future__ import annotations

import json
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from alpha_core import DataError

WINDOWS = (30, 90, 365)
#: At most this many assets are read from one store (in name order); the rest are counted only.
MAX_ASSETS_SCANNED = 200
#: At most this many of the newest bars of one asset are used. A window may not exceed it.
MAX_BARS_READ = 400
MAX_SERIES_POINTS = 60
VOLUME_BASE_BARS = 20
MAX_LIMIT = 30
_FEW_BARS = re.compile(r"got (\d+)$")


def _stored_timeframes(data_dir: Path) -> list[str]:
    """Canonical names of the stores that hold at least one bar file, daily first."""
    from alpha_data.timeframe import DAILY, parse_timeframe, store_dir

    found: list[Any] = []
    for entry in sorted(data_dir.glob("store*")):
        name = entry.name.removeprefix("store").removeprefix("-")
        try:
            timeframe = parse_timeframe(name or "1D")
        except DataError:
            continue
        if store_dir(data_dir, timeframe) == entry and any((entry / "bars").rglob("*.parquet")):
            found.append(timeframe)
    found.sort(key=lambda item: (item != DAILY, item.minutes))
    return [item.canonical for item in found]


def _sample(count: int) -> list[int]:
    """Evenly spaced indexes of ``count`` points, always keeping the first and the last."""
    if count <= MAX_SERIES_POINTS:
        return list(range(count))
    last = MAX_SERIES_POINTS - 1
    return [round(i * (count - 1) / last) for i in range(MAX_SERIES_POINTS)]


def _summary(symbol: str, bars: list[Any], window: int) -> dict[str, Any]:
    used = bars[-MAX_BARS_READ:]
    recent = used[-window:]
    closes = [bar.close for bar in recent]
    volumes = [bar.volume for bar in used]
    base = statistics.median(volumes[-VOLUME_BASE_BARS - 1 : -1])
    picks = _sample(window)
    return {
        "asset": symbol,
        "last_close": used[-1].close,
        "change_1_pct": (used[-1].close / used[-2].close - 1) * 100,
        "change_7_pct": (used[-1].close / used[-8].close - 1) * 100,
        "change_window_pct": (closes[-1] / closes[0] - 1) * 100,
        "last_volume": used[-1].volume,
        "volume_vs_median": used[-1].volume / base if base > 0 else None,
        "median_traded_value": statistics.median(bar.close * bar.volume for bar in recent),
        "series": [closes[i] / closes[0] * 100 for i in picks],
        "series_ts": [int(recent[i].ts.timestamp()) for i in picks],
        "last_bar": used[-1].ts.astimezone(UTC).isoformat(),
        "bar_count": len(bars),
    }


def build_market_overview(data_dir: Path, *, store: str, window: int, limit: int) -> dict[str, Any]:
    """The overview payload for one stored timeframe."""
    from polars.exceptions import PolarsError

    from alpha_cli._runner import load_bars
    from alpha_data.store import ParquetStore
    from alpha_data.timeframe import parse_timeframe, store_dir

    if window not in WINDOWS:
        raise DataError(f"window must be one of {list(WINDOWS)} bars, got {window}")
    if window > MAX_BARS_READ:
        raise DataError(f"window {window} is above the bar cap of {MAX_BARS_READ} bars")
    if not 1 <= limit <= MAX_LIMIT:
        raise DataError(f"limit must be 1..{MAX_LIMIT}, got {limit}")
    timeframe = parse_timeframe(store)
    available = _stored_timeframes(data_dir)
    if timeframe.canonical not in available:
        raise DataError(f"no stored bars in the {timeframe.canonical} store")
    names = ParquetStore(store_dir(data_dir, timeframe)).list_symbols()
    scanned = names[:MAX_ASSETS_SCANNED]
    rows: list[dict[str, Any]] = []
    too_few: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []
    for symbol in scanned:
        try:
            bars, _ = load_bars(
                symbol,
                data_dir=data_dir,
                timeframe=timeframe.canonical,
                source_timeframe=timeframe.canonical,
                last=MAX_BARS_READ,
            )
        except (DataError, OSError, PolarsError) as exc:
            few = _FEW_BARS.search(str(exc)) if isinstance(exc, DataError) else None
            if few:
                too_few.append({"asset": symbol, "bar_count": int(few[1]), "needed": window})
            else:
                unreadable.append({"asset": symbol, "reason": str(exc)[:200]})
            continue
        if len(bars) < window:
            too_few.append({"asset": symbol, "bar_count": len(bars), "needed": window})
            continue
        rows.append(_summary(symbol, bars, window))
    rows.sort(key=lambda row: (-row["median_traded_value"], row["asset"]))
    return {
        "store": timeframe.canonical,
        "available_stores": available,
        "bar_unit": "day" if timeframe.is_daily else "bar",
        "window": window,
        "limit": limit,
        "assets_in_store": len(names),
        "assets_scanned": len(scanned),
        "scan_cap": MAX_ASSETS_SCANNED,
        "bars_cap": MAX_BARS_READ,
        "eligible_assets": len(rows),
        "data_to": max((row["last_bar"] for row in rows), default=None),
        "assets": rows[:limit],
        "too_few_bars": too_few,
        "unreadable": unreadable,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def run_market_overview(store: str, window: int, limit: int, json_out: bool) -> None:
    """Print the overview (JSON or text); a bad request becomes a CLI usage error."""
    from alpha_core.config import AlphaSettings

    try:
        result = build_market_overview(
            AlphaSettings().data_dir, store=store, window=window, limit=limit
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_out:
        typer.echo(json.dumps(result))
        return
    typer.echo(
        f"{len(result['assets'])} of {result['eligible_assets']} assets,"
        f" data to {result['data_to']}"
    )
    for row in result["assets"]:
        period = f"over the last {result['window']} {result['bar_unit']}s"
        typer.echo(
            f"{row['asset']}: {row['last_close']:g} ({row['change_window_pct']:+.1f}% {period})"
        )
