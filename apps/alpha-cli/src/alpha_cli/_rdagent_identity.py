"""Declared asset boundaries and fail-loud checks for unexplained gap price jumps."""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from alpha_core import DataError

IDENTITY_JUMP_MIN_GAP_DAYS = 1
IDENTITY_JUMP_RATIO = 5.0
JUMP_POLICY = {"min_gap_days": IDENTITY_JUMP_MIN_GAP_DAYS, "ratio": IDENTITY_JUMP_RATIO}


class IdentityJumpError(DataError):
    """A gap may join different assets or units; the owner must resolve its identity."""


def validate_breaks(value: Any, instruments: list[str] | str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise DataError("identity_breaks must be a list")
    previous: dict[str, date] = {}
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"instrument", "new_from", "reason"}:
            raise DataError("identity_breaks entries need instrument, new_from and reason")
        name, start, reason = (entry[k] for k in ("instrument", "new_from", "reason"))
        if not isinstance(name, str) or not name.strip():
            raise DataError("identity_breaks instrument must be a non-empty name")
        if instruments != "all-in-store" and name not in instruments:
            raise DataError(f"identity_breaks instrument {name!r} is absent from the universe")
        if reason not in ("ticker_reused", "redenominated"):
            raise DataError("identity_breaks reason must be ticker_reused or redenominated")
        try:
            day = date.fromisoformat(start) if isinstance(start, str) else None
        except ValueError as error:
            raise DataError("identity_breaks new_from must be a YYYY-MM-DD date") from error
        if day is None or day.isoformat() != start:
            raise DataError("identity_breaks new_from must be a YYYY-MM-DD date")
        if name in previous and day <= previous[name]:
            raise DataError(f"identity_breaks for {name} must be strictly increasing")
        previous[name] = day
    return value


def relabel(
    panel: pl.DataFrame, breaks: list[dict[str, str]]
) -> tuple[pl.DataFrame, list[dict[str, str]]]:
    """Partition daily rows at each boundary before any feature, label or trading read.

    The original name/date columns select every segment, so later declarations cannot relabel
    an already renamed instrument accidentally. No bar is copied or spans two identities.
    Declarations outside this panel are retained in the universe, but are not applied here.
    """
    validate_breaks(breaks, "all-in-store")
    names = set(panel["instrument"].to_list())
    counts: dict[str, int] = {}
    applied = []
    expression = pl.col("instrument")
    for entry in breaks:
        name = entry["instrument"]
        if name not in names:
            raise DataError(
                f"identity_breaks instrument {name!r} is absent from the frozen universe"
            )
        counts[name] = counts.get(name, 1) + 1
        new_name = f"{name}~{counts[name]}"
        if new_name in names:
            raise DataError(f"identity_breaks name collision: {new_name}")
        boundary = date.fromisoformat(entry["new_from"])
        selected = (pl.col("instrument") == name) & (pl.col("date") >= boundary)
        expression = pl.when(selected).then(pl.lit(new_name)).otherwise(expression)
        if panel.filter(selected).height:
            applied.append({**entry, "new_name": new_name})
    return (
        panel.with_columns(expression.alias("instrument")).sort(["date", "instrument"])
        if applied
        else panel
    ), applied


def check_jumps(panel: pl.DataFrame) -> None:
    """Check price jumps across any gap of one or more missing calendar days inside each instrument.

    Missing days are (later date - earlier date).days - 1; consecutive daily bars are not checked.

    Every offending gap is named in one refusal, so the owner can fix the list in one pass.
    """
    found = []
    for (name,), group in sorted(panel.partition_by("instrument", as_dict=True).items()):
        rows = list(group.select("date", "close").sort("date").iter_rows())
        for (before, old), (after, new) in zip(rows, rows[1:], strict=False):
            ratio = new / old
            if (after - before).days - 1 >= IDENTITY_JUMP_MIN_GAP_DAYS and (
                ratio > IDENTITY_JUMP_RATIO or ratio < 1 / IDENTITY_JUMP_RATIO
            ):
                found.append(
                    f"identity jump for {name}: {before} close {old} -> {after} close {new}; "
                    f"ratio {ratio}; declare instrument={name!r}, new_from={after.isoformat()!r}"
                )
    if found:
        raise IdentityJumpError(
            f"{len(found)} undeclared identity jump(s) across a gap of at least "
            f"{IDENTITY_JUMP_MIN_GAP_DAYS} missing days. Declare each as an identity_breaks entry "
            "(reason ticker_reused or redenominated) in the universe file, or leave the "
            "instrument out. No override is available.\n" + "\n".join(found)
        )


def disclosure(breaks: list[dict[str, str]]) -> str:
    count = len({entry["instrument"] for entry in breaks})
    return f"{count} tickers were split at declared identity breaks."
