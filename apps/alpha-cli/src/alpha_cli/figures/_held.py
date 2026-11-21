"""Held-period shading for the price chart: closed trades plus a position still open."""

from __future__ import annotations

from typing import Any

from alpha_cli.figures import _sources as src
from alpha_cli.figures._common import BuildContext
from alpha_research.figures import Mark, ZoneMark


def held_zones(ctx: BuildContext, span: tuple[float, float] | None) -> list[Mark]:
    """Shade each closed trade's holding period: one block instead of two markers."""
    trades = src.frame(ctx.rdir, "trades.parquet", "entry_ts")
    if trades is None or trades.is_empty():
        return []
    zones: list[Mark] = []
    labelled: set[str] = set()
    for entry, exit_, side in zip(
        src.epochs(trades["entry_ts"]),
        src.epochs(trades["exit_ts"]),
        src.strings(trades["side"]),
        strict=True,
    ):
        if span is not None:
            entry, exit_ = max(entry, span[0]), min(exit_, span[1])
        if exit_ > entry:
            name = "Held short" if side == "SELL" else "Held long"
            zones.append(
                ZoneMark(
                    x0=entry,
                    x1=exit_,
                    role="down" if side == "SELL" else "up",
                    alpha=0.14,
                    label=name if name not in labelled else None,
                )
            )
            labelled.add(name)
    return zones


def open_position_zone(fills: Any, span: tuple[float, float] | None) -> Mark | None:
    """A position still open at the window's end: closed trades never list it, the fills do.

    ``fills`` is the whole fill history. The balance is rebuilt from the first fill, then
    the zone is cut to the plotted window, so an entry made before the window counts.
    """
    column = next((name for name in ("filled_quantity", "quantity") if name in fills.columns), None)
    if column is None:
        return None  # without sizes the net position cannot be told; draw nothing, guess nothing
    quantities = fills[column].to_list()
    if "quantity" in fills.columns:
        quantities = [
            q if q is not None else r
            for q, r in zip(quantities, fills["quantity"].to_list(), strict=True)
        ]
    position, since = 0.0, 0.0
    for stamp, side, quantity in zip(
        src.epochs(fills["ts"]),
        src.strings(fills["side"]),
        quantities,
        strict=True,
    ):
        if quantity is None:
            return None
        if span is not None and stamp > span[1]:
            break
        before = position
        position += float(quantity) * (1.0 if side == "BUY" else -1.0)
        # A new holding starts when the account leaves flat or flips sign in one fill.
        if abs(before) < 1e-9 <= abs(position) or before * position < 0:
            since = stamp
    end = span[1] if span else since
    since = max(since, span[0]) if span else since
    if abs(position) < 1e-9 or end <= since:
        return None
    return ZoneMark(
        x0=since,
        x1=end,
        role="up" if position > 0 else "down",
        alpha=0.14,
        label="Open position",
    )
