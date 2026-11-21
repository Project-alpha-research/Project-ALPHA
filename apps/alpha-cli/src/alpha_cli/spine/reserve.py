"""Hold the reserved period back from rule tests and setups; label runs that saw it."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.stores import ResolvedAsset, resolve_asset
from alpha_core.reserve import RESERVED_DAY, RESERVED_START
from alpha_core.reserve import RESERVED_INSTANT as RESERVED_INSTANT  # re-exported: the one boundary

# The one boundary. A row stamped at or after the first instant of the reserved day is held
# back. A row stamped before it is used once it is known, and it is known by this instant at the
# latest when its interval closes on it (the last daily bar of the day before).
# The last instant before the boundary: for readers that keep a row when its stamp <= ``as_of``.
CUTOFF = RESERVED_INSTANT - timedelta(microseconds=1)
CUTOFF_DAY = CUTOFF.date()
CUTOFF_DATE = CUTOFF_DAY.isoformat()
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
    stamps = pl.scan_parquet(path).select("ts")
    return int(stamps.filter(pl.col("ts") >= RESERVED_INSTANT).select(pl.len()).collect().item())


def held_back_count_for(home: Path, asset: str) -> int:
    return held_back_count(resolve_asset(asset, data_dir=home))


@dataclass(frozen=True)
class Hold:
    """What the reserve does to one command's read: the cut-off to pass and what to record."""

    as_of: datetime | None
    research_cutoff: str | None
    held_back: int
    unit: str = "bars"

    def record_fields(self) -> dict[str, Any]:
        """The hold-back record; empty when no bar was held back, so an old id stays the same."""
        return {"reserve": record(self.held_back, self.unit)} if self.held_back else {}

    def identity(self) -> dict[str, Any]:
        """Run-identity keys: the cut-off, and the hold-back record only when a bar was held."""
        return {"research_cutoff": self.research_cutoff, **self.record_fields()}

    def fields(self) -> dict[str, Any]:
        """Manifest keys: the identity keys, and the label when a bar was held back."""
        return {**self.identity(), **({"labels": [HELD_BACK]} if self.held_back else {})}

    def note(self) -> str:
        """The one sentence, for the end of a command's last line; empty when nothing held."""
        return f"\n{sentence(self.held_back, self.unit)}" if self.held_back else ""

    def stamp(self, manifest: dict[str, Any]) -> None:
        """Record the hold-back and its label on a manifest; nothing when no bar was held."""
        if not self.held_back:
            return
        manifest["reserve"] = record(self.held_back, self.unit)
        labels = list(manifest.get("labels", []))
        manifest["labels"] = [*labels, HELD_BACK] if HELD_BACK not in labels else labels

    def label(self, labels: list[str]) -> list[str]:
        """The label list with the hold-back label added when bars were held back."""
        return [*labels, HELD_BACK] if self.held_back and HELD_BACK not in labels else labels

    def announce(self, *, err: bool = False) -> None:
        """Print the one sentence when bars were held back."""
        if self.held_back:
            print(sentence(self.held_back, self.unit), file=sys.stderr if err else sys.stdout)

    def say(self) -> str | None:
        return sentence(self.held_back, self.unit) if self.held_back else None


def hold(
    symbol: str,
    *,
    data_dir: Path,
    as_of: str | None = None,
    snapshot_id: str | None = None,
    timeframe: str = "1D",
    instant: bool = False,
) -> Hold:
    """The cut-off a command passes to its loaders, and how many stored bars it holds back.

    The earlier of the user's own cut-off and the reserve cut-off wins. The count comes from a
    timestamp-only scan of the stored file; no price is read. A cut-off the user set that is
    already before the reserved day holds nothing back and is recorded as the user gave it.
    """
    import polars as pl

    from alpha_cli import _runner
    from alpha_data.snapshot import resolve_snapshot_dir
    from alpha_data.store import ParquetStore
    from alpha_data.timeframe import parse_timeframe, store_dir

    stored = parse_timeframe(timeframe)
    # A daily reader keeps a bar by its stamp; an intraday reader keeps it once it has closed.
    cut = CUTOFF if stored.is_daily else RESERVED_INSTANT
    user = _runner.parse_cutoff(as_of) if instant else _runner.parse_as_of(as_of)
    if user is not None and user <= cut:
        return Hold(user, as_of, 0)
    root = (
        resolve_snapshot_dir(data_dir / "snapshots", snapshot_id)
        if snapshot_id is not None
        else store_dir(data_dir, stored)
    )
    path = ParquetStore(root)._bars_path(symbol)
    n = 0
    if path.exists():
        ts = pl.col("ts") >= RESERVED_INSTANT
        if user is not None:
            ts = ts & (pl.col("ts") <= user)
        n = int(pl.scan_parquet(path).select("ts").filter(ts).select(pl.len()).collect().item())
    return Hold(cut, CUTOFF_DATE if n else as_of, n)


def hold_many(
    symbols: Sequence[str],
    data_dir: Path,
    as_of: str | None = None,
    snapshot_id: str | None = None,
) -> Hold:
    """One cut-off for a basket; the count is the sum over its symbols."""
    holds = [hold(s, data_dir=data_dir, as_of=as_of, snapshot_id=snapshot_id) for s in symbols]
    n = sum(h.held_back for h in holds)
    return Hold(holds[0].as_of if holds else CUTOFF, CUTOFF_DATE if n else as_of, n)


def record(n: int, unit: str = "bars") -> dict[str, Any]:
    """The hold-back record; ``unit`` is "rows" where funding and open interest count too."""
    return {"reserved_start": RESERVED_START, f"held_back_{unit}": n}


def sentence(n: int, unit: str = "bars") -> str:
    what = "rows (bars, funding and open interest)" if unit == "rows" else unit
    return (
        f"Held back {n} {what} from {RESERVED_START} on; they are kept for the owner's "
        "confirmation of an idea, so this test did not use them."
    )


def describe(block: Mapping[str, Any]) -> str:
    """The one sentence for a stored hold-back record, in the unit it was counted in."""
    if "held_back_rows" in block:
        return sentence(block["held_back_rows"], "rows")
    return sentence(block["held_back_bars"])


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
