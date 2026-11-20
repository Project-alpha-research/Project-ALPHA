"""What a pull changed: bars and actions added, removed or revised, as counts and dates.

`PullReport` is what `pull_store.pull_into_store` returns: the diff plus the snapshot it froze.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import polars as pl

from alpha_core import CorporateAction

_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class SeriesDiff:
    """The change between the series held before a pull and the series stored after it."""

    bars_added: tuple[int, date | None, date | None] = (0, None, None)
    bars_removed: int = 0
    bars_revised: tuple[int, date | None, list[str]] = field(default=(0, None, []))
    actions_added: int = 0
    actions_removed: int = 0
    actions_revised: int = 0


def _rows(frame: pl.DataFrame) -> dict[datetime, tuple[object, ...]]:
    columns = ["ts", *_PRICE_COLUMNS]
    return {row[0]: row[1:] for row in frame.select(columns).iter_rows()}


def _action_rows(actions: list[CorporateAction]) -> dict[tuple[str, date], CorporateAction]:
    return {(a.action_type.value, a.ex_date): a for a in actions}


def diff_series(
    old_bars: pl.DataFrame,
    new_bars: pl.DataFrame,
    old_actions: list[CorporateAction],
    new_actions: list[CorporateAction],
) -> SeriesDiff:
    """Compare two stored series. A bar is added or removed by its timestamp; it is revised when
    the timestamp is in both and any of open, high, low, close or volume differs."""
    old, new = _rows(old_bars), _rows(new_bars)
    added = sorted(set(new) - set(old))
    revised = sorted(ts for ts in set(old) & set(new) if old[ts] != new[ts])
    names = sorted(
        {
            name
            for ts in revised
            for name, a, b in zip(_PRICE_COLUMNS, old[ts], new[ts], strict=True)
            if a != b
        }
    )
    held, now = _action_rows(old_actions), _action_rows(new_actions)
    return SeriesDiff(
        bars_added=(len(added), added[0].date(), added[-1].date()) if added else (0, None, None),
        bars_removed=len(set(old) - set(new)),
        bars_revised=(len(revised), revised[0].date(), names) if revised else (0, None, []),
        actions_added=len(set(now) - set(held)),
        actions_removed=len(set(held) - set(now)),
        actions_revised=sum(1 for key in set(held) & set(now) if held[key] != now[key]),
    )


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
    older_versions: str | None = None  # "adapter A / parser P" when the old series predates them

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
                else {
                    "id": self.snapshot_id,
                    "reused": self.reused,
                    "older_versions": self.older_versions,
                }
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
            if self.older_versions:
                out.append(f"the earlier series came from {self.older_versions}; frozen as such")
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
