"""Content hash of one frozen symbol, and the listing of existing snapshots built on it.

The hash covers the bars, actions and provenance bytes of one symbol. A snapshot whose symbol
hashes like that symbol's most recent snapshot is not written again. Old manifests carry no hash:
they are never matched and never rewritten.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from alpha_core import DataError

_KINDS = ("bars", "actions", "provenance")


def content_hash(entry: dict[str, Any]) -> str:
    """The content hash of one manifest symbol entry, from its three file digests."""
    parts = "\n".join(f"{kind}_sha256:{entry.get(f'{kind}_sha256', '')}" for kind in _KINDS)
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def stored_content_hash(bars: Path, actions: Path, provenance: Path) -> str:
    """The same hash for a symbol still in the store; a missing optional file counts as absent."""
    entry: dict[str, Any] = {}
    for kind, path in zip(_KINDS, (bars, actions, provenance), strict=True):
        if path.is_file():
            entry[f"{kind}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return content_hash(entry)


def read_manifests(snaps_root: Path) -> list[tuple[Path, bytes, dict[str, Any]]]:
    """Every snapshot manifest as (path, raw bytes, parsed), in snapshot-id order."""
    found: list[tuple[Path, bytes, dict[str, Any]]] = []
    if not snaps_root.is_dir():
        return found
    for path in sorted(snaps_root.glob("*/manifest.json")):
        raw = path.read_bytes()
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DataError(f"corrupt snapshot manifest at {path}") from exc
        if not isinstance(manifest, dict):
            raise DataError(f"corrupt snapshot manifest at {path}")
        found.append((path, raw, manifest))
    return found


def latest_snapshot_of(
    snaps_root: Path, symbol: str, timeframe: str
) -> tuple[str, str | None] | None:
    """(snapshot id, content hash or None for an old manifest) of the most recent snapshot that
    holds ``symbol`` at ``timeframe``; None when there is none."""
    best: tuple[str, str, str | None] | None = None
    for _, _, manifest in read_manifests(snaps_root):
        symbols = manifest.get("symbols")
        entry = symbols.get(symbol) if isinstance(symbols, dict) else None
        if not isinstance(entry, dict) or manifest.get("timeframe", "1D") != timeframe:
            continue
        held = entry.get("content_sha256")
        held = held if held == content_hash(entry) else None  # never trust a hash the digests deny
        key = (str(manifest.get("created_at")), str(manifest.get("snapshot_id")))
        if best is None or key > best[:2]:
            best = (*key, held)
    return None if best is None else (best[1], best[2])


def shared_content(
    manifests: list[tuple[Path, bytes, dict[str, Any]]],
) -> dict[tuple[str, str], list[str]]:
    """Snapshot ids per (symbol, content hash), for the hashes more than one snapshot holds."""
    groups: dict[tuple[str, str], list[str]] = {}
    for _, _, manifest in manifests:
        symbols = manifest.get("symbols")
        for symbol, entry in (symbols if isinstance(symbols, dict) else {}).items():
            held = entry.get("content_sha256") if isinstance(entry, dict) else None
            if isinstance(held, str):
                groups.setdefault((symbol, held), []).append(str(manifest.get("snapshot_id")))
    return {key: ids for key, ids in groups.items() if len(ids) > 1}


def total_bytes(snaps_root: Path) -> int:
    """The disk the snapshots use: the size of every file under the snapshots root."""
    if not snaps_root.is_dir():
        return 0
    return sum(p.stat().st_size for p in snaps_root.rglob("*") if p.is_file())
