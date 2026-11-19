"""Append-only, hash-bound options snapshots with point-in-time reads.

Layout: `<root>/options/<provider>/<underlying_id>/<yyyy>/<yyyymmddThhmmssZ>.parquet`, plus a
`.json` sidecar with the content hash, row count and fetch provenance. A snapshot, once written,
is never changed. Reads take an aware cut-off and stop at the held-back day.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_core.reserve import RESERVED_DAY
from alpha_data._atomic import publish, write_text
from alpha_data.options.codec import filter_rows, from_frame, to_frame
from alpha_data.options.schema import ChainSnapshot, OptionsDataError, aware_utc

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_SCHEMA_VERSION = 1


def _name(field: str, value: str) -> str:
    if not _NAME.fullmatch(value) or ".." in value:
        raise OptionsDataError(field, f"unsafe name for storage: {value!r}")
    return value


def _cutoff(when: datetime) -> datetime:
    """The same held-back rule the other stores use: no read reaches the reserved day."""
    if when.tzinfo is None or when.utcoffset() is None:
        raise OptionsDataError("when", "cut-off must be timezone-aware")
    utc = when.astimezone(UTC)
    if utc.date() >= RESERVED_DAY:
        raise OptionsDataError("when", "options read reaches the held-back period")
    return utc


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
        return from_frame(frame), frame

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

    def snapshots_as_of(
        self, provider: str, underlying_id: str, when: datetime
    ) -> list[ChainSnapshot]:
        """Snapshots with known_at <= when, oldest first. Later files are not opened."""
        cutoff = _cutoff(when)
        return [
            self._load(path)[0]
            for known, _, path in self._metas(provider, underlying_id)
            if known <= cutoff
        ]

    def chain_as_of(
        self, provider: str, underlying_id: str, when: datetime
    ) -> ChainSnapshot | None:
        """The newest snapshot known at `when`, with contracts listed and unexpired that day."""
        cutoff = _cutoff(when)
        known = [m for m in self._metas(provider, underlying_id) if m[0] <= cutoff]
        if not known:
            return None
        newest = max(known, key=lambda m: (m[0], m[1]))
        return filter_rows(self._load(newest[2])[0], cutoff.date())
