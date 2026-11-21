"""Every named constant and reason of the derived options series, in one place.

The series are descriptive context: readings, no thresholds, no advice. Rules are in
`docs/reference/invariants/data-options.md` (Derived series).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import time
from typing import Final

from alpha_data.options.schema import OptionsDataError

SERIES: Final = (
    "iv30",
    "iv_rank_252",
    "iv_percentile_252",
    "skew_25d",
    "term_slope",
    "iv_minus_rv",
)
TARGET_SHORT_DAYS: Final = 30  # calendar days, ACT/365
TARGET_LONG_DAYS: Final = 90
DAYS_PER_YEAR: Final = 365.0
MIN_DAYS_TO_EXPIRY: Final = 7  # nearer expiries are too noisy to bracket a target
MIN_QUOTED_STRIKES: Final = 3  # strikes with a usable mid, else the expiry is not used
WING_DELTA: Final = 0.25  # absolute forward delta of the wing options
RANK_WINDOW: Final = 252  # sessions, including today
RV_WINDOW: Final = 21  # sessions of close-to-close returns for realized volatility
DEFAULT_RATE: Final = 0.0  # the store records no rate; discounting only, small effect on IV
DEFAULT_DIVIDEND_YIELD: Final = 0.0  # the store records no dividends; used where no parity forward
EXPIRY_TIME_UTC: Final = time(21, 0)  # the store records dates only; same as the fixture
AMERICAN_STEPS: Final = 200  # tree steps for American-style contracts (500 is the solver default)
LABEL_PARITY: Final = "parity_forward"
LABEL_NEAREST: Final = "nearest_strike_to_spot"

REASON_WORDS: Final = {
    "no_expiry_at_or_below_30d": "no usable expiry at or before 30 days",
    "no_expiry_at_or_above_30d": "no usable expiry at or after 30 days",
    "no_expiry_at_or_above_90d": "no usable expiry at or after 90 days",
    "no_expiry_at_or_below_90d": "no usable expiry at or before 90 days",
    "atm_unavailable": "no at-the-money volatility could be solved",
    "forward_outside_listed_strikes": "the forward lies outside the listed strikes",
    "put_wing_not_bracketed": "the 25-delta put wing is not bracketed by listed strikes",
    "call_wing_not_bracketed": "the 25-delta call wing is not bracketed by listed strikes",
    "warm_up_252": "fewer than 252 sessions stored",
    "iv30_missing": "iv30 is null today",
    "gap_in_window": "iv30 is null on some day in the 252-session window",
    "flat_window": "iv30 was the same on every day of the window",
    "no_realized_vol": "no realized volatility stored for this day",
    "no_atm_for_term": "iv30 is null, so the slope has no base",
}


@dataclass(frozen=True)
class SurfaceConfig:
    """Rate, yield and conventions the store does not record. Defaults are the constants above."""

    rate: float = DEFAULT_RATE
    dividend_yield: float = DEFAULT_DIVIDEND_YIELD
    expiry_time_utc: time = EXPIRY_TIME_UTC
    american_steps: int = AMERICAN_STEPS

    def __post_init__(self) -> None:
        for name in ("rate", "dividend_yield"):
            if not math.isfinite(getattr(self, name)):
                raise OptionsDataError(name, "must be finite")
        if self.american_steps < 2:
            raise OptionsDataError("american_steps", "must be at least 2")
