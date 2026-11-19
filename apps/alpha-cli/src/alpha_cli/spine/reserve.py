"""Hold the reserved period back from rule tests and setups; label runs that saw it."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.stores import ResolvedAsset, resolve_asset
from alpha_core.reserve import RESERVED_DAY, RESERVED_START

# The last instant of the last day before the reserved day: every read passes it as ``as_of``.
CUTOFF_DAY = RESERVED_DAY - timedelta(days=1)
CUTOFF_DATE = CUTOFF_DAY.isoformat()
CUTOFF = datetime.combine(CUTOFF_DAY, time(23, 59, 59), tzinfo=UTC)
HELD_BACK = "reserved-period-held-back"
SEEN = "reserved-period-seen"
SEEN_SENTENCE = (
    f"This run used data from {RESERVED_START} on, before that data was held back. "
    "It is not a fresh test on that period."
)


def held_back_count(resolved: ResolvedAsset) -> int:
    """Count stored bar timestamps on or after the reserved day; no price is read."""
    import polars as pl

    path = resolved.daily_store()._bars_path(resolved.symbol)
    start = datetime.combine(RESERVED_DAY, time.min, tzinfo=UTC)
    stamps = pl.scan_parquet(path).select("ts")
    return int(stamps.filter(pl.col("ts") >= start).select(pl.len()).collect().item())


def held_back_count_for(home: Path, asset: str) -> int:
    return held_back_count(resolve_asset(asset, data_dir=home))


def record(n: int) -> dict[str, Any]:
    return {"reserved_start": RESERVED_START, "held_back_bars": n}


def sentence(n: int) -> str:
    return (
        f"Held back {n} bars from {RESERVED_START} on; they are kept for the owner's "
        "confirmation of an idea, so this test did not use them."
    )


def seen(last_ts: str | datetime | None, manifest: Mapping[str, Any]) -> bool:
    """A run that reached the reserved day and recorded no hold-back saw the period."""
    if last_ts is None:
        return False
    last = datetime.fromisoformat(last_ts) if isinstance(last_ts, str) else last_ts
    spine = manifest.get("spine")
    block = manifest.get("reserve") or (
        spine.get("reserve") if isinstance(spine, Mapping) else None
    )
    return last.date() >= RESERVED_DAY and block is None


def read_labels(manifest: Mapping[str, Any]) -> list[str]:
    """A rule run's stored labels, plus `reserved-period-seen` derived when it is read."""
    spine = manifest.get("spine", {})
    labels = list(spine.get("labels", []))
    if SEEN not in labels and seen(spine.get("data_period", {}).get("last_ts"), manifest):
        labels.append(SEEN)
    return labels


def refuse_find_that_saw_period(manifest: Mapping[str, Any]) -> None:
    """Study and trade never run on a find that used reserved bars (checked before any load)."""
    for asset in manifest["assets"]:
        if asset["error"] is None and seen(asset["last_bar"], manifest):
            raise SpineError(
                "RESERVED_PERIOD_SEEN",
                f"This find used data from {RESERVED_START} on, which is now held back.",
                "Run alpha setup find again; the new find holds that data back.",
            )


def carry_to_outcome(summary: dict[str, Any], find_manifest: Mapping[str, Any]) -> None:
    """A study or trade repeats its find's hold-back label and sentence; nothing else."""
    block = find_manifest.get("reserve")
    if not block:
        return
    if HELD_BACK not in summary["labels"]:
        summary["labels"] = [*summary["labels"], HELD_BACK]
    summary["reserve"] = block
    summary["reserve_sentence"] = sentence(block["held_back_bars"])
