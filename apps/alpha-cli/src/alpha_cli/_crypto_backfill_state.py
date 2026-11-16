"""Invocation-local discovery and progress state; no additional on-disk format."""

from __future__ import annotations

import stat
from bisect import bisect_left
from collections.abc import Callable, Iterable
from pathlib import Path

from alpha_core import DataError
from alpha_data.crypto.storage import CryptoBulkStore


def progress_identity(path: Path) -> tuple[int, int, int, int, int] | None:
    """Constant-size change detection while the existing progress lock is held."""
    try:
        info = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DataError("backfill progress identity is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise DataError("backfill progress must be a regular non-hardlinked file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class CommandStore:
    """Open lazily so planning and empty commands need no mounted bulk storage."""

    def __init__(self, factory: Callable[[], CryptoBulkStore]) -> None:
        self._factory = factory
        self._store: CryptoBulkStore | None = None

    def get(self) -> CryptoBulkStore:
        if self._store is None:
            self._store = self._factory()
        return self._store


class RetainedRanges:
    """Static split-topology index for one preflight, with logarithmic containment queries."""

    def __init__(self, keys: Iterable[str]) -> None:
        grouped: dict[str, list[tuple[str, str, str]]] = {}
        for key in keys:
            parts = key.rsplit("|", 3)
            if len(parts) == 4 and parts[3] == "None" and parts[1] < parts[2]:
                grouped.setdefault(parts[0], []).append((parts[1], parts[2], key))
        self._starts: dict[str, list[str]] = {}
        self._ends: dict[str, list[tuple[tuple[str, str], ...]]] = {}
        for symbol, ranges in grouped.items():
            ranges.sort()
            self._starts[symbol] = [start for start, _, _ in ranges]
            # Two smallest ends in each suffix allow exclusion of the queried parent itself.
            ends: list[tuple[tuple[str, str], ...]] = [()] * len(ranges)
            best: tuple[tuple[str, str], ...] = ()
            for index in range(len(ranges) - 1, -1, -1):
                _, end, key = ranges[index]
                best = tuple(sorted((*best, (end, key)))[:2])
                ends[index] = best
            self._ends[symbol] = ends

    def has_child(self, symbol: str, start: str, end: str, key: str) -> bool:
        starts = self._starts.get(symbol, [])
        position = bisect_left(starts, start)
        if position == len(starts):
            return False
        return any(
            child_end <= end and child_key != key
            for child_end, child_key in self._ends[symbol][position]
        )
