"""Resample complete bars on session-open or UTC-epoch grids."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, time

import polars as pl

from alpha_core import DataError
from alpha_data.sessions import _aware_utc, filter_session, session_bounds, session_date_of
from alpha_data.timeframe import BarTimeframe


def resample_bars(
    frame: pl.DataFrame,
    *,
    source: BarTimeframe,
    target: BarTimeframe,
    calendar: str | None,
    known_by: datetime | None = None,
) -> pl.DataFrame:
    """Aggregate complete intervals, refusing gaps in every already-known bin.

    Inspect bins between the first and last observed bins in each session (or the continuous
    UTC range), including wholly missing interior bins. Source starts are aligned to each bin.
    """
    if target == source:
        return frame
    if target < source or target.minutes % source.minutes:
        raise DataError(f"cannot resample {source.canonical} to {target.canonical}")
    if known_by is not None:
        known_by = _aware_utc(known_by)
    if calendar is not None:
        regular = filter_session(frame, timeframe=source, calendar=calendar, scope="regular")
        if regular.height != frame.height:
            raise DataError(
                "resample regular-session bars only: input extends outside regular hours"
            )
    if frame.is_empty():
        return frame
    stamps = [_aware_utc(ts) for ts in frame["ts"].to_list()]
    if len(set(stamps)) != len(stamps) or stamps != sorted(stamps):
        raise DataError("resample source timestamps must be strictly increasing")

    # Each session is independent: overnight and holiday gaps are not missing stock bars.
    groups: dict[tuple[datetime, datetime | None], list[int]] = defaultdict(list)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for index, ts in enumerate(stamps):
        opening, closing = (
            session_bounds(calendar, session_date_of(ts, calendar))
            if calendar is not None
            else (epoch, None)
        )
        groups[(opening, closing)].append(index)

    output: list[dict[str, object]] = []
    for (anchor, closing), indices in groups.items():
        bins: dict[int, list[int]] = defaultdict(list)
        for index in indices:
            bins[(stamps[index] - anchor) // target.duration].append(index)
        for number in range(min(bins), max(bins) + 1):
            start = anchor + number * target.duration
            end = start + target.duration
            if closing is not None:
                end = min(end, closing)
            if known_by is not None and end > known_by:
                continue
            members = bins.get(number, [])
            present = {stamps[index] for index in members}
            expected = start
            while expected < end:
                if expected not in present:
                    raise DataError(f"incomplete bin {start}: missing source start {expected}")
                expected += source.duration
            if any((ts - start) % source.duration for ts in present):
                raise DataError(f"source start is not aligned in bin {start}")
            chunk = frame[members]
            stamp = (
                datetime.combine(session_date_of(start, calendar), time.min, UTC)
                if calendar is not None and target.is_daily
                else start
            )
            output.append(
                {
                    "ts": stamp,
                    "open": chunk["open"][0],
                    "high": chunk["high"].max(),
                    "low": chunk["low"].min(),
                    "close": chunk["close"][-1],
                    "volume": chunk["volume"].sum(),
                }
            )
    return pl.DataFrame(output, schema=frame.schema).sort("ts")
