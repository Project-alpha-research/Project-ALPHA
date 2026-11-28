"""Absolute paper risk limits a ``VolTargetStrategy`` checks before it submits a paper order."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from alpha_core import DataError


@dataclass(frozen=True, slots=True)
class PaperRiskLimits:
    """Absolute limits derived by ``alpha_cli`` from an approved paper risk profile."""

    max_order_notional: float
    max_position_notional: float
    max_gross_notional: float
    daily_loss_fraction: float
    max_open_orders: int
    max_quote_age_seconds: float
    intent_id: str
    account_id: str | None = None
    expected_position_units: float = 0.0
    order_cutoff: datetime | None = None

    def __post_init__(self) -> None:
        positive = (
            self.max_order_notional,
            self.max_position_notional,
            self.max_gross_notional,
            self.daily_loss_fraction,
            self.max_quote_age_seconds,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise DataError("paper risk limits must be finite and positive")
        if self.max_order_notional > self.max_position_notional:
            raise DataError("paper max order notional cannot exceed max position notional")
        if self.max_position_notional > self.max_gross_notional:
            raise DataError("paper max position notional cannot exceed max gross notional")
        if not 0.0 < self.daily_loss_fraction < 1.0 or self.max_open_orders < 1:
            raise DataError("invalid paper daily-loss or open-order limit")
        if len(self.intent_id) != 64 or any(
            character not in "0123456789abcdef" for character in self.intent_id
        ):
            raise DataError("paper intent id must be a lowercase SHA-256")
        if self.account_id is not None and not self.account_id.startswith("DU"):
            raise DataError("paper risk account must be an IBKR DU… account")
        if not math.isfinite(self.expected_position_units):
            raise DataError("paper expected position must be finite")
        if self.order_cutoff is not None and (
            self.order_cutoff.tzinfo is None or self.order_cutoff.utcoffset() is None
        ):
            raise DataError("paper order cutoff must be timezone-aware")
