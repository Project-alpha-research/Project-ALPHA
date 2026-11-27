"""Append-only, hash-bound options snapshots with point-in-time reads.

Layout: `<root>/options/<provider>/<underlying_id>/<yyyy>/<yyyymmddThhmmssZ>.parquet`, plus a
`.json` sidecar with the content hash, row count and fetch provenance. A snapshot, once written,
is never changed.

Two read paths, as in the bars store:
- Research reads (`snapshots_as_of`, `chain_as_of`) cut the caller's time at the held-back
  boundary and report how many snapshots that hid. They never return data from the reserved period.
- Forward use (`forward_chain_as_of`) reads the newest data on purpose, up to the caller's time.
  Research-side code must never call it; `tests/unit/test_options_forward_guard.py` enforces that.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_core.atomic import publish, write_text
from alpha_core.reserve import RESERVED_DAY
from alpha_data.options.codec import filter_rows, from_frame, to_frame
from alpha_data.options.schema import ChainSnapshot, OptionsDataError, aware_utc

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_SCHEMA_VERSION = 1


def _name(field: str, value: str) -> str:
    if not _NAME.fullmatch(value) or ".." in value:
        raise OptionsDataError(field, f"unsafe name for storage: {value!r}")
    return value


_BOUNDARY = datetime.combine(RESERVED_DAY, time.min, UTC)
_LAST_VISIBLE = _BOUNDARY - timedelta(microseconds=1)


def _aware(when: datetime) -> datetime:
    if when.tzinfo is None or when.utcoffset() is None:
        raise OptionsDataError("when", "cut-off must be timezone-aware")
    return when.astimezone(UTC)


@dataclass(frozen=True)
class SnapshotsRead:
    """Research read result: snapshots known at the capped time, and how many the cap hid."""

    snapshots: tuple[ChainSnapshot, ...]
    held_back: int


@dataclass(frozen=True)
class ChainRead:
    """Research read result: the newest visible chain (or None) and how many snapshots were hid."""

    chain: ChainSnapshot | None
    held_back: int


class OptionsStore:
    """Writes immutable snapshots and reads them as known at a cut-off."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, provider: str, underlying_id: str) -> Path:
        return (
            self.root
            / "options"
            / _name("provider", provider)
            / _name("underlying_id", underlying_id)
        )

    def _path(self, snapshot: ChainSnapshot) -> Path:
        ts = snapshot.snapshot_ts
        folder = self._dir(snapshot.provider, snapshot.underlying_id) / f"{ts:%Y}"
        return folder / f"{ts:%Y%m%dT%H%M%SZ}.parquet"

    def _metas(self, provider: str, underlying_id: str) -> list[tuple[datetime, datetime, Path]]:
        """(known_at, snapshot_ts, parquet path) from the small sidecars, oldest first."""
        found: list[tuple[datetime, datetime, Path]] = []
        for sidecar in self._dir(provider, underlying_id).glob("*/*.json"):
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                known = aware_utc("known_at", datetime.fromisoformat(meta["known_at"]))
                taken = aware_utc("snapshot_ts", datetime.fromisoformat(meta["snapshot_ts"]))
            except (OSError, ValueError, KeyError, TypeError):
                raise DataError(f"unreadable options provenance: {sidecar}") from None
            found.append((known, taken, sidecar.with_suffix(".parquet")))
        return sorted(found)

    def _load(self, path: Path) -> tuple[ChainSnapshot, pl.DataFrame]:
        try:
            raw = path.read_bytes()
            meta: dict[str, Any] = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise DataError(f"unreadable options snapshot or provenance: {path}") from None
        if hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
            raise DataError(f"options parquet sha256 differs from provenance: {path}")
        try:
            frame = pl.read_parquet(io.BytesIO(raw))
        except pl.exceptions.PolarsError:
            raise DataError(f"invalid options parquet: {path}") from None
        if meta.get("rows") != frame.height:
            raise DataError(f"options rows differ from provenance: {path}")
        snapshot = from_frame(frame)
        if snapshot.known_at.isoformat() != meta.get(
            "known_at"
        ) or snapshot.snapshot_ts.isoformat() != meta.get("snapshot_ts"):
            raise DataError(f"options times differ from provenance: {path}")
        return snapshot, frame

    def write(self, snapshot: ChainSnapshot, *, fetched_at: datetime, adapter_version: str) -> Path:
        """Publish one snapshot. Same content again is a no-op; changed content is refused."""
        aware_utc("fetched_at", fetched_at)
        if not adapter_version.strip():
            raise OptionsDataError("adapter_version", "must be a non-empty string")
        path = self._path(snapshot)
        frame = to_frame(snapshot)
        if path.exists() or path.with_suffix(".json").exists():
            _, stored = self._load(path)
            if not stored.equals(frame):
                raise DataError(f"snapshot {path.name} already stored with different content")
            return path
        metas = self._metas(snapshot.provider, snapshot.underlying_id)
        newest = max((taken for _, taken, _ in metas), default=None)
        if newest is not None and snapshot.snapshot_ts < newest:
            raise OptionsDataError("snapshot_ts", f"older than the newest stored snapshot {newest}")
        buffer = io.BytesIO()
        frame.write_parquet(buffer)
        raw = buffer.getvalue()
        meta = {
            "schema_version": _SCHEMA_VERSION,
            "source": snapshot.provider,
            "adapter_version": adapter_version,
            "fetched_at": fetched_at.isoformat(),
            "snapshot_ts": snapshot.snapshot_ts.isoformat(),
            "known_at": snapshot.known_at.isoformat(),
            "rows": frame.height,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        publish(path, lambda tmp: tmp.write_bytes(raw))
        write_text(
            path.with_suffix(".json"), json.dumps(meta, sort_keys=True, allow_nan=False) + "\n"
        )
        return path

    def snapshots_as_of(self, provider: str, underlying_id: str, when: datetime) -> SnapshotsRead:
        """RESEARCH read: snapshots with known_at <= min(when, last instant before the held-back
        day), oldest first, plus the count of snapshots the cap hid. Later files are not opened."""
        asked = _aware(when)
        cutoff = min(asked, _LAST_VISIBLE)
        metas = self._metas(provider, underlying_id)
        return SnapshotsRead(
            tuple(self._load(path)[0] for known, _, path in metas if known <= cutoff),
            sum(1 for known, _, _ in metas if cutoff < known <= asked),
        )

    def chain_as_of(self, provider: str, underlying_id: str, when: datetime) -> ChainRead:
        """RESEARCH read: the newest snapshot visible at the capped time, with contracts listed
        and unexpired that day. A contract expiring after the boundary is kept: its identity was
        known then. No quote, trade or greek from the held-back period is returned."""
        asked = _aware(when)
        cutoff = min(asked, _LAST_VISIBLE)
        metas = self._metas(provider, underlying_id)
        held = sum(1 for known, _, _ in metas if cutoff < known <= asked)
        chain = self._newest(metas, cutoff)
        return ChainRead(chain, held)

    def forward_chain_as_of(
        self, provider: str, underlying_id: str, when: datetime
    ) -> ChainSnapshot | None:
        """FORWARD USE ONLY (paper following, "active today", display): the newest snapshot known
        at `when`, with no held-back cap. Research code must never call this."""
        return self._newest(self._metas(provider, underlying_id), _aware(when))

    def _newest(
        self, metas: list[tuple[datetime, datetime, Path]], cutoff: datetime
    ) -> ChainSnapshot | None:
        known = [m for m in metas if m[0] <= cutoff]
        if not known:
            return None
        newest = max(known, key=lambda m: (m[0], m[1]))
        return filter_rows(self._load(newest[2])[0], cutoff.date())
