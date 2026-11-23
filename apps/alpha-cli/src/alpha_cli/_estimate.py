"""One time estimate for the long commands: measured on this computer, never a fixed number.

A command splits its work into equal units (an asset, a fold, a batch of paths). The time of the
first finished unit, times the units in all, is the estimate. A rate kept from an earlier run on
this computer gives the first guess, before any unit has finished. Nothing here changes a result.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from pathlib import Path

Clock = Callable[[], float]
RATES_FILE = "timing_rates.json"


class UnitTimer:
    """Times finished units and says how long all of them take."""

    def __init__(
        self, units: int, *, prior_per_unit: float | None = None, clock: Clock = time.monotonic
    ) -> None:
        if units < 1:
            raise ValueError("a timer needs at least one unit")
        self.units = units
        self.done = 0
        self._prior = prior_per_unit
        self._clock = clock
        self._started: float | None = None
        self._elapsed = 0.0

    def start(self) -> None:
        """Start the clock; later calls do nothing."""
        if self._started is None:
            self._started = self._clock()

    def finish_unit(self) -> None:
        if self._started is None:
            raise ValueError("start the timer before a unit finishes")
        self.done = min(self.done + 1, self.units)
        self._elapsed = self._clock() - self._started

    @property
    def started(self) -> bool:
        return self._started is not None

    @property
    def measured(self) -> bool:
        return self.done >= 1

    def per_unit(self) -> float | None:
        """Seconds a unit takes: measured in this run once one has finished, else the prior."""
        return self._elapsed / self.done if self.done else self._prior

    def expected(self) -> float | None:
        """Seconds for all units; None when neither a measurement nor a prior exists."""
        each = self.per_unit()
        return None if each is None else each * self.units


def say_minutes(seconds: float) -> str:
    if seconds < 90:
        return f"about {max(1, round(seconds))} seconds"
    return f"about {math.ceil(seconds / 60)} minutes"


def read_rate(data_dir: Path, key: str) -> float | None:
    """The seconds per unit kept from the last run of ``key`` on this computer."""
    try:
        stored = json.loads((data_dir / RATES_FILE).read_text(encoding="utf-8"))[key]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    ok = isinstance(stored, int | float) and not isinstance(stored, bool) and stored > 0
    return float(stored) if ok else None


def write_rate(data_dir: Path, key: str, seconds_per_unit: float) -> None:
    """Keep the measured rate of this run for the next estimate."""
    if not seconds_per_unit > 0 or not math.isfinite(seconds_per_unit):
        return
    path = data_dir / RATES_FILE
    try:
        rates = json.loads(path.read_text(encoding="utf-8"))
        rates = rates if isinstance(rates, dict) else {}
    except (OSError, ValueError):
        rates = {}
    rates[key] = seconds_per_unit
    path.write_text(json.dumps(rates, sort_keys=True), encoding="utf-8")
