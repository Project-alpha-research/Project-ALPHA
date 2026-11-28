"""Round an order delta to a valid venue quantity for the instrument's size increment."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from nautilus_trader.model.objects import Quantity

from alpha_core import DataError


def normalize_order_quantity(
    delta: float, *, size_precision: int, size_increment: float
) -> Quantity | None:
    """Return a valid venue quantity without changing the legacy integer-lot SIM path.

    Existing simulations round to the nearest integer, so that exact behavior is retained when
    the instrument advertises precision ``0`` and increment ``1``.  Fractional live quantities
    are rounded down to the nearest positive venue increment to avoid exceeding the target.
    """
    magnitude = abs(delta)
    if size_precision == 0 and size_increment == 1.0:
        lots = round(magnitude)
        return Quantity.from_int(lots) if lots > 0 else None
    if size_increment <= 0.0:
        raise DataError(f"instrument size_increment must be > 0, got {size_increment}")
    raw = Decimal(str(magnitude))
    increment = Decimal(str(size_increment))
    steps = (raw / increment).to_integral_value(rounding=ROUND_DOWN)
    normalized = steps * increment
    if normalized <= 0:
        return None
    return Quantity(float(normalized), size_precision)
