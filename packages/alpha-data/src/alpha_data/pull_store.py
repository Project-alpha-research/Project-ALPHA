"""The one home of "freeze before replace": every pull replaces a stored series through here.

Order of one pull: validate the new data (no write), freeze the stored series as a snapshot (or
reuse an identical one), then replace. A failure at any step before the replace leaves the stored
series untouched; a failure inside the replace puts the old bytes back, and if even that fails
every read of the symbol refuses until the named repair command runs. One pull at a time holds a
store (an exclusive lock on its folder); a second pull waits. A first-ever pull of a symbol has
nothing to freeze. The report that comes back holds counts and dates, never prices.
"""

from __future__ import annotations

import fcntl
import math
import os
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data.adapters.base import FetchResult
from alpha_data.ingest import store_fetch_result
from alpha_data.pipeline import replace_series, stage_and_promote
from alpha_data.series_diff import PullReport, diff_series
from alpha_data.snapshot import create_snapshot, resolve_snapshot_dir, verify_snapshot
from alpha_data.snapshot_reuse import latest_snapshot_of, stored_content_hash
from alpha_data.store import ParquetStore

__all__ = ["FreezeRefused", "PullReport", "pull_into_store"]

_VALUE_COLUMNS = ("open", "high", "low", "close", "volume")


class FreezeRefused(DataError):
    """The stored series could not be frozen, so nothing was replaced."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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


def _reusable(snaps_root: Path, store: ParquetStore, symbol: str, timeframe: str) -> str | None:
    """The id of the symbol's latest snapshot when it holds exactly the stored bytes and its own
    files still verify; None otherwise (a fresh snapshot is then taken)."""
    latest = latest_snapshot_of(snaps_root, symbol, timeframe)
    if latest is None or latest[1] != stored_content_hash(*store.series_paths(symbol)):
        return None
    try:
        verify_snapshot(resolve_snapshot_dir(snaps_root, latest[0]), timeframe=timeframe)
    except DataError:
        return None  # a tampered snapshot is never trusted to hold the old series
    return latest[0]


def _freeze(
    store: ParquetStore, snaps_root: Path, symbol: str, *, now: datetime, timeframe: str
) -> tuple[str, bool, tuple[str, str, str] | None]:
    """Freeze the stored series under the source and versions that wrote it; returns (snapshot
    id, reused, those versions or None when unrecorded). Raises FreezeRefused."""
    try:
        stored = store.read_provenance(symbol)
        held = (
            None
            if stored is None
            else (
                str(stored["source"]),
                str(stored["adapter_version"]),
                str(stored["parser_version"]),
            )
        )
        reused = _reusable(snaps_root, store, symbol, timeframe)
        if reused is not None:
            return reused, True, held
        snap_id = _snapshot_id(snaps_root, symbol, now, timeframe)
        source, adapter_version, parser_version = held or ("unrecorded", "unknown", "unknown")
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
    except (DataError, OSError) as exc:
        raise FreezeRefused(str(exc)) from exc
    return snap_id, False, held


@contextmanager
def _one_pull_at_a_time(store: ParquetStore) -> Iterator[None]:
    """Hold an exclusive lock on the store folder; a second pull waits for the first."""
    store.root.mkdir(parents=True, exist_ok=True)
    fd = os.open(store.root, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def _replace_unreceipted(
    store: ParquetStore,
    result: FetchResult,
    *,
    source: str,
    adapter_version: str,
    parser_version: str,
    before_replace: Callable[[], None],
    frozen: list[tuple[str, bool, tuple[str, str, str] | None]],
) -> None:
    _validate(store, result)
    before_replace()
    held_in = f" and in snapshot {frozen[0][0]}" if frozen else ""
    symbol = result.symbol

    def write() -> None:
        store.clear_provenance(symbol)
        store_fetch_result(store, result)
        store.write_provenance(
            symbol, source=source, adapter_version=adapter_version, parser_version=parser_version
        )

    replace_series(
        store,
        symbol,
        provider=source,
        backup_id=f"pull-{uuid.uuid4().hex}",
        write=write,
        keep_backup=False,
        held_in=held_in,
    )


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
    FreezeRefused when the freeze failed) before any write, or pipeline.RestoreFailed."""
    with _one_pull_at_a_time(store):
        return _pull_locked(
            store, snaps_root, result, (source, adapter_version, parser_version), now, timeframe
        )


def _pull_locked(
    store: ParquetStore,
    snaps_root: Path,
    result: FetchResult,
    versions: tuple[str, str, str],
    now: datetime,
    timeframe: str,
) -> PullReport:
    symbol, (source, adapter_version, parser_version) = result.symbol, versions
    held = _held(store, result)
    frozen: list[tuple[str, bool, tuple[str, str, str] | None]] = []

    def freeze() -> None:
        if held is not None:
            frozen.append(_freeze(store, snaps_root, symbol, now=now, timeframe=timeframe))

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
            frozen=frozen,
        )
    new_bars, new_actions = store.read_bars(symbol), store.read_actions(symbol)
    old_bars, old_actions = held if held is not None else (new_bars.clear(), [])
    diff = diff_series(old_bars, new_bars, old_actions, new_actions)
    snapshot_id, reused, was = frozen[0] if frozen else (None, False, None)
    older = None
    if was is not None and was[0] == source and was[1:] != (adapter_version, parser_version):
        older = f"{was[0]} adapter {was[1]} / parser {was[2]}"
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
        older_versions=older,
    )
