"""Chart-pattern events as `ctx_<alias>` columns of the setup bars.

A spec names one as `alias = "swing_low@SELF"`. The value is 1.0 on the bar where the event
became known and 0.0 on other bars; the first bars are missing with the reason `series-warm-up`.
The events come from `alpha_cli.pattern_events` over the same bars the find reads (already cut at
the reserved day), so nothing after that day is read. There are no table rows: the identity of an
alias is the hash of its values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from alpha_cli import pattern_events
from alpha_data.context.attach import AttachResult

if TYPE_CHECKING:
    from alpha_patterns import OHLCV

PATTERN_SERIES = frozenset(n for names in pattern_events.FAMILIES.values() for n in names)
TIME = pl.Datetime("us", "UTC")
WARM_UP = "series-warm-up"


def _ohlcv(frame: pl.DataFrame) -> OHLCV:
    from alpha_patterns import OHLCV

    return OHLCV(
        ts=np.asarray([t.timestamp() * 1000.0 for t in frame["ts"].to_list()], dtype=np.float64),
        open=frame["open"].to_numpy(),
        high=frame["high"].to_numpy(),
        low=frame["low"].to_numpy(),
        close=frame["close"].to_numpy(),
        volume=frame["volume"].to_numpy(),
        symbol="SELF",
    )


def add_patterns(
    result: AttachResult, aliases: Mapping[str, str], symbol: str | None
) -> AttachResult:
    """Add one column group per alias (alias -> series name) to an attach result."""
    frame = result.frame
    values = pattern_events.event_series(_ohlcv(frame), sorted(set(aliases.values())))
    hashes = dict(result.used_rows_sha256)
    for alias, series in aliases.items():
        column = values[series]
        known = [v is not None for v in column]
        frame = frame.with_columns(
            pl.Series(f"ctx_{alias}", column, dtype=pl.Float64),
            pl.Series(f"ctx_{alias}_age_days", [0 if k else None for k in known], dtype=pl.Int64),
            pl.Series(f"ctx_{alias}_stale", [False] * len(column), dtype=pl.Boolean),
            frame["ts"].cast(TIME).alias(f"ctx_{alias}_known_from"),
            pl.Series(
                f"ctx_{alias}_reason", [None if k else WARM_UP for k in known], dtype=pl.String
            ),
        )
        body = json.dumps([alias, series, symbol, column], separators=(",", ":"))
        hashes[alias] = hashlib.sha256(body.encode()).hexdigest()
    recipe = pattern_events.RECIPE
    if result.used_rows_sha256:
        recipe = f"{result.recipe}+{recipe}"
    return replace(result, frame=frame, used_rows_sha256=hashes, recipe=recipe)
