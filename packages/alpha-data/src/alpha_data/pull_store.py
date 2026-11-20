"""The one home of "freeze before replace": every pull replaces a stored series through here.

Order of one pull: validate the new data (no write), freeze the stored series as a snapshot (or
reuse an identical one), then replace. A failure at any step before the replace leaves the stored
series untouched; a failure inside the replace puts the old bytes back. A first-ever pull of a
symbol has nothing to freeze. The report that comes back holds counts and dates, never prices.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data._atomic import publish
from alpha_data.adapters.base import FetchResult
from alpha_data.ingest import store_fetch_result
from alpha_data.pipeline import stage_and_promote
from alpha_data.series_diff import SeriesDiff, diff_series
from alpha_data.snapshot import create_snapshot, resolve_snapshot_dir
from alpha_data.snapshot_reuse import latest_snapshot_of, stored_content_hash
from alpha_data.store import ParquetStore

_VALUE_COLUMNS = ("open", "high", "low", "close", "volume")


class FreezeRefused(DataError):
    """The stored series could not be frozen, so nothing was replaced."""

    def __init__(self, reason: str, *, older_adapter: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.older_adapter = older_adapter


@dataclass(frozen=True)
class PullReport(SeriesDiff):
    """What one pull did: the snapshot it froze or reused, and what changed in the series."""

    symbol: str = ""
    source: str = ""
    timeframe: str = "1D"
    bars: int = 0
    actions: int = 0
    snapshot_id: str | None = None
    reused: bool = False
    receipt_id: str | None = None

    @property
    def notice(self) -> str | None:
        count = self.bars_revised[0]
        if not count or self.snapshot_id is None:
            return None
        word = "bar" if count == 1 else "bars"
        return (
            f"the provider revised {count} earlier {word}; "
            f"the earlier series is kept in snapshot {self.snapshot_id}"
        )

    def as_dict(self) -> dict[str, Any]:
        added, removed, (revised, first, columns) = (
            self.bars_added,
            self.bars_removed,
            self.bars_revised,
        )
        return {
            "symbol": self.symbol,
            "source": self.source,
            "timeframe": self.timeframe,
            "bars": self.bars,
            "actions": self.actions,
            "receipt_id": self.receipt_id,
            "snapshot": (
                None
                if self.snapshot_id is None
                else {"id": self.snapshot_id, "reused": self.reused}
            ),
            "bars_added": {
                "count": added[0],
                "first": added[1] and added[1].isoformat(),
                "last": added[2] and added[2].isoformat(),
            },
            "bars_removed": {"count": removed},
            "bars_revised": {
                "count": revised,
                "first_date": first and first.isoformat(),
                "columns": columns,
            },
            "actions_added": {"count": self.actions_added},
            "actions_removed": {"count": self.actions_removed},
            "actions_revised": {"count": self.actions_revised},
            "notice": self.notice,
        }

    def lines(self) -> list[str]:
        """Plain lines for the terminal: the freeze, then what changed."""
        if self.snapshot_id is None:
            out = [f"first pull of {self.symbol}: nothing was stored, so no snapshot was taken"]
        else:
            verb = "reused snapshot" if self.reused else "froze snapshot"
            out = [f"{verb} {self.snapshot_id} (the series before this pull)"]
        added, (revised, first, columns) = self.bars_added, self.bars_revised
        if added[0]:
            out.append(f"bars added: {added[0]} ({added[1]} to {added[2]})")
        if self.bars_removed:
            out.append(f"bars removed: {self.bars_removed}")
        if revised:
            out.append(f"bars revised: {revised}, first {first}, columns {', '.join(columns)}")
        out.append(
            f"actions added {self.actions_added}, removed {self.actions_removed}, "
            f"revised {self.actions_revised}"
        )
        if self.notice:
            out.append(f"notice: {self.notice}")
        return out


def _validate(store: ParquetStore, result: FetchResult) -> None:
    """Refuse bars the store could not hold, or that carry a missing or non-finite value."""
    store.check_bars(result.symbol, result.bars)
    for name in _VALUE_COLUMNS:
        column = result.bars[name]
        if column.null_count() or any(not math.isfinite(float(v)) for v in column.to_list()):
            raise DataError(
                f"bars for {result.symbol} hold a value in {name} that is not a finite number; "
                "nothing was stored"
            )


def _held(store: ParquetStore, result: FetchResult) -> tuple[pl.DataFrame, Any] | None:
    """The bars and actions now stored for the symbol, or None when nothing is stored."""
    bars_path, actions_path, _ = store.series_paths(result.symbol)
    if not bars_path.is_file() and not actions_path.is_file():
        return None
    old_bars = store.read_bars(result.symbol) if bars_path.is_file() else result.bars.clear()
    return old_bars, store.read_actions(result.symbol)


def _snapshot_id(snaps_root: Path, symbol: str, now: datetime, timeframe: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", symbol).strip("-") or "asset"
    suffix = "" if timeframe == "1D" else f"-{timeframe}"
    base = f"pull-{now:%Y%m%dT%H%M%S}-{name}{suffix}"
    snap_id, number = base, 1
    while resolve_snapshot_dir(snaps_root, snap_id).exists():
        number += 1
        snap_id = f"{base}-{number}"
    return snap_id


def _freeze(
    store: ParquetStore,
    snaps_root: Path,
    symbol: str,
    *,
    source: str,
    adapter_version: str,
    parser_version: str,
    now: datetime,
    timeframe: str,
) -> tuple[str, bool]:
    """Freeze the stored series; returns (snapshot id, reused). Raises FreezeRefused."""
    try:
        stored = store.read_provenance(symbol)
        if stored is not None and stored["source"] == source:
            held = (stored["adapter_version"], stored["parser_version"])
            if held != (adapter_version, parser_version):
                raise FreezeRefused(
                    f"the stored {symbol} came from {source} adapter {held[0]} / parser {held[1]}; "
                    f"this pull uses {adapter_version} / {parser_version}. A series is frozen only "
                    "under the adapter version that wrote it, and nothing in ALPHA re-adopts it "
                    "under a newer one, so there is no safe path today and the pull keeps refusing",
                    older_adapter=True,
                )
        if stored is not None:  # another source: the snapshot tells the truth about the old one
            source, adapter_version, parser_version = (
                str(stored["source"]),
                str(stored["adapter_version"]),
                str(stored["parser_version"]),
            )
        latest = latest_snapshot_of(snaps_root, symbol, timeframe)
        current = stored_content_hash(*store.series_paths(symbol))
        if latest is not None and latest[1] == current:
            return latest[0], True
        snap_id = _snapshot_id(snaps_root, symbol, now, timeframe)
        create_snapshot(
            store,
            snaps_root,
            snap_id,
            [symbol],
            source=source,
            adapter_version=adapter_version,
            parser_version=parser_version,
            created_at=now,
            timeframe=timeframe,
        )
    except FreezeRefused:
        raise
    except (DataError, OSError) as exc:
        raise FreezeRefused(str(exc)) from exc
    return snap_id, False


def _put_back(path: Path, data: bytes) -> None:
    publish(path, lambda tmp: tmp.write_bytes(data))


def _restore(saved: dict[Path, bytes | None]) -> None:
    for path, content in saved.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            _put_back(path, content)


def _replace_unreceipted(
    store: ParquetStore,
    result: FetchResult,
    *,
    source: str,
    adapter_version: str,
    parser_version: str,
    before_replace: Callable[[], None],
) -> None:
    _validate(store, result)
    before_replace()
    symbol = result.symbol
    saved = {p: p.read_bytes() if p.is_file() else None for p in store.series_paths(symbol)}
    try:
        store.clear_provenance(symbol)
        store_fetch_result(store, result)
        store.write_provenance(
            symbol, source=source, adapter_version=adapter_version, parser_version=parser_version
        )
    except BaseException:
        _restore(saved)
        raise


def pull_into_store(
    store: ParquetStore,
    snaps_root: Path,
    result: FetchResult,
    *,
    source: str,
    adapter_version: str,
    parser_version: str,
    now: datetime,
    timeframe: str = "1D",
) -> PullReport:
    """Store a fetched series, freezing the one it replaces first. Raises DataError (a
    FreezeRefused when the freeze failed) before any write."""
    symbol = result.symbol
    held = _held(store, result)
    frozen: list[tuple[str, bool]] = []

    def freeze() -> None:
        if held is not None:
            frozen.append(
                _freeze(
                    store,
                    snaps_root,
                    symbol,
                    source=source,
                    adapter_version=adapter_version,
                    parser_version=parser_version,
                    now=now,
                    timeframe=timeframe,
                )
            )

    receipt_id: str | None = None
    if result.identity is not None or result.receipt is not None or result.raw_response is not None:
        receipt_id = stage_and_promote(
            store, result, authoritative_source=source, before_replace=freeze
        ).receipt_id
    else:
        _replace_unreceipted(
            store,
            result,
            source=source,
            adapter_version=adapter_version,
            parser_version=parser_version,
            before_replace=freeze,
        )
    new_bars, new_actions = store.read_bars(symbol), store.read_actions(symbol)
    old_bars, old_actions = held if held is not None else (new_bars.clear(), [])
    diff = diff_series(old_bars, new_bars, old_actions, new_actions)
    snapshot_id, reused = frozen[0] if frozen else (None, False)
    return PullReport(
        **{f.name: getattr(diff, f.name) for f in fields(diff)},
        symbol=symbol,
        source=source,
        timeframe=timeframe,
        bars=new_bars.height,
        actions=len(new_actions),
        snapshot_id=snapshot_id,
        reused=reused,
        receipt_id=receipt_id,
    )
