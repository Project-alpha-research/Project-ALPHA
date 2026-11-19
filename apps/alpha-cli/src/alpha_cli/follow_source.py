"""What a follow is made from: a stored rule test or setup find. Read-only. Paper only.

Also records the hash of the newest stored bar of each asset. Forward use reads the newest bars
on purpose, as `alpha scan check` does; a research command never takes this path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_core import DataError


def refuse(code: str, message: str, next_step: str) -> SpineError:
    return SpineError(code, message, next_step)


class Source:
    """What a follow is made from: read from the stored test or find, never changed."""

    def __init__(self, kind: str, source_id: str, spec: str, card: str, assets: list[str]) -> None:
        self.kind, self.source_id, self.spec, self.card, self.assets = (
            kind,
            source_id,
            spec,
            card,
            assets,
        )


def _manifest(path: Path, what: str, source_id: str) -> dict[str, Any]:
    try:
        raw = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise refuse(
            "FOLLOW_SOURCE_UNKNOWN",
            f"There is no {what} with the id {source_id!r}.",
            f"Run `alpha {'test' if what == 'rule test' else 'setup find'}` first.",
        ) from exc
    return raw if isinstance(raw, dict) else {}


def rule_test_source(home: Path, run_id: str) -> Source:
    from alpha_cli.run_store import find_run_dir

    folder = find_run_dir(home, run_id)
    manifest = _manifest(folder, "rule test", run_id) if folder else {}
    spine = manifest.get("spine")
    symbol = manifest.get("metadata", {}).get("symbol")
    if not isinstance(spine, dict) or not symbol or not spine.get("spec_sha256"):
        raise refuse(
            "FOLLOW_SOURCE_UNKNOWN",
            f"There is no rule test with the run id {run_id!r}.",
            "Use the run id that `alpha test` printed.",
        )
    store = spine.get("store", "home")
    asset = symbol if store == "home" else f"{symbol}@{store}"
    return Source("rule_test", run_id, spine["spec_sha256"], spine.get("idea_card", ""), [asset])


def setup_find_source(home: Path, find_id: str) -> Source:
    manifest = _manifest(home / "setups" / find_id, "setup find", find_id)
    rows = manifest.get("assets")
    assets = [r["asset"] for r in rows if r.get("error") is None] if isinstance(rows, list) else []
    if not assets or not manifest.get("spec_sha256"):
        raise refuse(
            "FOLLOW_SOURCE_UNKNOWN",
            f"There is no setup find with the id {find_id!r}, or it found no asset.",
            "Use the find id that `alpha setup find` printed.",
        )
    return Source(
        "setup_find", find_id, manifest["spec_sha256"], manifest.get("idea_card", ""), assets
    )


def latest_bar_hashes(home: Path, assets: list[str]) -> dict[str, str]:
    """The hash of the newest stored bar of each asset. Forward use reads the newest bars on
    purpose, as `alpha scan check` does; a research command never takes this path."""
    from alpha_cli._runner import load_bars, source_fingerprint
    from alpha_cli.spine.stores import resolve_asset

    hashes: dict[str, str] = {}
    for asset in assets:
        try:
            resolved = resolve_asset(asset, data_dir=home)
            bars, _ = load_bars(resolved.symbol, data_dir=resolved.data_dir)
        except DataError as exc:
            raise refuse(
                "FOLLOW_NO_BARS",
                f"Cannot read stored bars for {asset}: {exc}",
                "Store bars for the asset first, then start the follow.",
            ) from exc
        hashes[asset] = source_fingerprint([bars[-1]])
    return hashes
