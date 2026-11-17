"""Declared asset boundaries and fail-loud checks for unexplained gap price jumps."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import polars as pl

from alpha_core import DataError

IDENTITY_JUMP_MIN_GAP_DAYS = 1
IDENTITY_JUMP_RATIO = 5.0
JUMP_POLICY = {"min_gap_days": IDENTITY_JUMP_MIN_GAP_DAYS, "ratio": IDENTITY_JUMP_RATIO}


class IdentityJumpError(DataError):
    """A gap may join different assets or units; the owner must resolve its identity."""


def validate_breaks(value: Any, instruments: list[str] | str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise DataError("identity_breaks must be a list")
    previous: dict[str, date] = {}
    for entry in value:
        if not isinstance(entry, dict) or not {"instrument", "new_from", "reason"} <= set(entry):
            raise DataError("identity_breaks entries need instrument, new_from and reason")
        name, start, reason = (entry[k] for k in ("instrument", "new_from", "reason"))
        if not isinstance(name, str) or not name.strip():
            raise DataError("identity_breaks instrument must be a non-empty name")
        if instruments != "all-in-store" and name not in instruments:
            raise DataError(f"identity_breaks instrument {name!r} is absent from the universe")
        if reason not in ("ticker_reused", "redenominated", "renamed"):
            raise DataError(
                "identity_breaks reason must be ticker_reused, redenominated or renamed"
            )
        required = {"instrument", "new_from", "reason"}
        if reason == "renamed":
            successor = entry.get("continues_as")
            if not isinstance(successor, str) or not successor.strip() or successor == name:
                raise DataError(
                    f"renamed entry for {name!r} requires a distinct continues_as instrument"
                )
            if instruments != "all-in-store" and successor not in instruments:
                raise DataError(f"renamed successor {successor!r} is absent from the universe")
            required.add("continues_as")
        if reason == "redenominated" or reason == "renamed" and "ratio" in entry:
            ratio = entry.get("ratio")
            if (
                isinstance(ratio, bool)
                or not isinstance(ratio, (int, float))
                or not math.isfinite(ratio)
                or ratio <= 0
            ):
                raise DataError(
                    f"identity_breaks {reason} entry for {name!r} requires a positive "
                    "finite ratio; add ratio = new price units per old unit (for example 100 when "
                    "the first new price is 100 times the last old one). Open, high, low and close "
                    "on and after new_from are divided by it and base volume is multiplied by it"
                )
            required.add("ratio")
        if set(entry) != required:
            raise DataError("identity_breaks entry has unexpected fields")
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
    panel: pl.DataFrame, breaks: list[dict[str, Any]]
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Partition daily rows at each boundary before any feature, label or trading read.

    The original name/date columns select every segment, so later declarations cannot relabel
    an already renamed instrument accidentally. No bar is copied or spans two identities.
    Declarations outside this panel are retained in the universe, but are not applied here.
    """
    validate_breaks(breaks, "all-in-store")
    panel, joins = join_renames(panel, breaks)
    names = set(panel["instrument"].to_list())
    counts: dict[str, int] = {}
    applied = joins
    expression = pl.col("instrument")
    for entry in breaks:
        if entry["reason"] == "renamed":
            continue
        name = entry["instrument"]
        if name not in names:
            raise DataError(
                f"identity_breaks instrument {name!r} is absent from the frozen universe"
            )
        boundary = date.fromisoformat(entry["new_from"])
        selected = (pl.col("instrument") == name) & (pl.col("date") >= boundary)
        if entry["reason"] == "redenominated":
            ratio = entry["ratio"]
            panel = panel.with_columns(
                [
                    pl.when(selected).then(pl.col(c) / ratio).otherwise(pl.col(c)).alias(c)
                    for c in ("open", "high", "low", "close")
                ]
                + [
                    pl.when(selected)
                    .then(pl.col("volume") * ratio)
                    .otherwise(pl.col("volume"))
                    .alias("volume")
                ]
            )
            if panel.filter(selected).height:
                applied.append(dict(entry))
            continue
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


def join_renames(
    panel: pl.DataFrame, breaks: list[dict[str, Any]]
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Join a declared successor forward in time without creating bars in the gap."""
    applied = []
    for entry in breaks:
        if entry["reason"] != "renamed":
            continue
        name, successor = entry["instrument"], entry["continues_as"]
        names = set(panel["instrument"].to_list())
        for instrument in (name, successor):
            if instrument not in names:
                raise DataError(
                    f"renamed instrument {instrument!r} is absent from the frozen store"
                )
        boundary = date.fromisoformat(entry["new_from"])
        old = panel.filter(pl.col("instrument") == name)
        new = panel.filter(pl.col("instrument") == successor)
        if new.filter(pl.col("date") < boundary).height:
            raise DataError(
                f"renamed successor {successor!r} has rows before new_from; "
                "earlier rows cannot change"
            )
        old_last, new_first = old["date"].max(), new["date"].min()
        if not isinstance(old_last, date) or not isinstance(new_first, date):
            raise DataError("renamed series require dated bars")
        if old_last >= boundary or old_last >= new_first:
            raise DataError(
                f"overlapping renamed series: {name} has bars on or after new_from "
                f"{entry['new_from']}, where {successor} continues it"
            )
        selected = (pl.col("instrument") == successor) & (pl.col("date") >= boundary)
        ratio = entry.get("ratio", 1)
        panel = panel.with_columns(
            [
                pl.when(selected).then(pl.col(c) / ratio).otherwise(pl.col(c)).alias(c)
                for c in ("open", "high", "low", "close")
            ]
            + [
                pl.when(selected)
                .then(pl.col("volume") * ratio)
                .otherwise(pl.col("volume"))
                .alias("volume"),
                pl.when(selected)
                .then(pl.lit(name))
                .otherwise(pl.col("instrument"))
                .alias("instrument"),
            ]
        )
        applied.append({**entry, "ratio": ratio})
    return panel.sort(["date", "instrument"]) if applied else panel, applied


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


def disclosure(breaks: list[dict[str, Any]]) -> str:
    count = len({entry["instrument"] for entry in breaks})
    noun = "ticker was" if count == 1 else "tickers were"
    return f"{count} {noun} split at declared identity breaks."
