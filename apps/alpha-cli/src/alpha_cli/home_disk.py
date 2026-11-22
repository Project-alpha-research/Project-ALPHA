"""Disk facts about the data home: its size, the free space and the trend across nightly records.

Reads only. The reserve is the owner's storage setting (`<home>/crypto/storage-config.json`,
ADR-0043) or, with none set, the default of ADR-0032. Nothing here refuses a write: it only says.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alpha_cli.crypto_bulk_store import (
    DEFAULT_MINIMUM_FREE_BYTES,
    DEFAULT_RESERVE_FRACTION,
    OwnerStorageReserveV1,
)
from alpha_core import DataError

UNITS = ("kB", "MB", "GB", "TB")
NOT_RECORDED = "not recorded"


def human(size: int) -> str:
    """A size in plain decimal units: 999 bytes, 1.5 kB, 2.3 MB, 7.0 GB."""
    if abs(size) < 1000:
        return f"{size} bytes"
    value = float(size)
    for unit in UNITS:
        value /= 1000
        if abs(value) < 1000 or unit == UNITS[-1]:
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")


def tree_bytes(root: Path) -> int:
    """The bytes of every file under `root`. A link is counted as a link and never followed."""
    total = 0
    for folder, _, names in os.walk(root, followlinks=False):
        for name in names:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except FileNotFoundError:  # a file removed while the walk ran is simply gone
                continue
    return total


def _reserve(home: Path, total: int) -> tuple[int | None, str]:
    """The reserve in bytes and where it comes from; (None, why) when the setting is unreadable."""
    path = home / "crypto" / "storage-config.json"
    default = max(int(total * DEFAULT_RESERVE_FRACTION), DEFAULT_MINIMUM_FREE_BYTES)
    words = "the default: the larger of 15% of the disk and 100 GB; you have set no reserve"
    if not path.exists():
        return default, words
    try:
        config = json.loads(path.read_bytes())
        if not isinstance(config, dict):
            raise DataError("it is not an object")
        if "free_space_reserve" not in config:
            return default, words
        owner = OwnerStorageReserveV1.from_dict(config["free_space_reserve"])
    except (OSError, ValueError, DataError) as error:
        return None, f"the storage settings file {path} cannot be read ({error})"
    return owner.minimum_free_bytes, f"set by {owner.decided_by} on {owner.decided_on}"


def _trend(records: list[dict[str, Any]]) -> dict[str, Any]:
    known = [
        {"run": f"{r.get('date')}-{r.get('run_number')}", "bytes": r["home_bytes"]}
        for r in records
        if type(r.get("home_bytes")) is int
    ]
    return {
        "recorded": len(known),
        "not_recorded": len(records) - len(known),
        "first": known[0] if known else None,
        "last": known[-1] if known else None,
        "change_bytes": known[-1]["bytes"] - known[0]["bytes"] if len(known) > 1 else None,
    }


def disk_facts(
    home: Path,
    records: list[dict[str, Any]],
    usage: Callable[[Path], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    """Size now, free space, the reserve and the size change across the stored records."""
    place = next(p for p in (home, *home.resolve().parents) if p.exists())
    disk = usage(place)
    reserve, source = _reserve(home, disk.total)
    return {
        "home_bytes": tree_bytes(home),
        "free_bytes": disk.free,
        "total_bytes": disk.total,
        "reserve_bytes": reserve,
        "reserve_source": source,
        "under_reserve": None if reserve is None else disk.free < reserve,
        "trend": _trend(records),
    }


def _trend_line(trend: dict[str, Any]) -> str:
    old = trend["not_recorded"]
    tail = f"; {old} older record{'' if old == 1 else 's'}: {NOT_RECORDED}" if old else ""
    if trend["first"] is None:
        return f"Size across the stored nightly records: {NOT_RECORDED}."
    first, last, change = trend["first"], trend["last"], trend["change_bytes"]
    if change is None:
        return (
            f"Size across the stored nightly records: one size is recorded "
            f"({human(first['bytes'])} at run {first['run']}); a change needs two{tail}."
        )
    word = "did not change" if change == 0 else f"{'grew' if change > 0 else 'shrank'} by "
    amount = "" if change == 0 else human(abs(change))
    return (
        f"Size across the stored nightly records: {word}{amount} "
        f"({human(first['bytes'])} at run {first['run']}, {human(last['bytes'])} at run "
        f"{last['run']}; {trend['recorded']} records){tail}."
    )


def disk_lines(disk: dict[str, Any]) -> list[str]:
    lines = [
        f"Data home size now: {human(disk['home_bytes'])}. "
        f"Free space on its disk: {human(disk['free_bytes'])}.",
        _trend_line(disk["trend"]),
    ]
    if disk["under_reserve"] is None:
        lines.append(f"Free space is not compared with a reserve: {disk['reserve_source']}.")
    elif disk["under_reserve"]:
        lines.append(
            f"LOW DISK SPACE: free space ({human(disk['free_bytes'])}) is under your storage "
            f"reserve ({human(disk['reserve_bytes'])}; {disk['reserve_source']}). "
            "Free disk space before the next data write."
        )
    return lines
