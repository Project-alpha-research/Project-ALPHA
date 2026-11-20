"""What a pull changed: bars and actions added, removed or revised, as counts and dates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

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
