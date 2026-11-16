"""Universe, calendar and year length of the RD-Agent judge, as configuration (ADR-0055).

A universe file names its data source, the instruments it may hold, a point-in-time liquidity
rule and its calendar. The calendar fixes the year length and the three holding clocks, so a
universe file cannot choose its own clocks (ADR-0050's clocks stay pre-stated). Runs frozen before
this file existed carry no universe file and read the built-in default, which is exactly the
judge's earlier behaviour: every Binance spot coin in the store, calendar days, 365 a year.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from alpha_core import DataError

SCHEMA = "AlphaRdagentUniverseV1"
# Each calendar fixes its year length and clocks; a universe file only names one of these.
CALENDARS: dict[str, dict[str, Any]] = {
    "calendar-days": {"annual_periods": 365, "clocks": {"daily": 1, "weekly": 7, "monthly": 28}},
    # US exchange sessions: 252 a year, 1 / 5 / 20 sessions. Configured, not yet evaluable: the
    # clocks, panel checks and replay still assume consecutive calendar days (follow-up).
    "exchange-sessions": {
        "annual_periods": 252,
        "clocks": {"daily": 1, "weekly": 5, "monthly": 20},
    },
}
SOURCES = ("binance-spot", "alpaca-us-equities")
DEFAULT_SURVIVORSHIP = (
    "15 coins chosen in 2026-11 from today's survivors; coins that were delisted or collapsed "
    "(for example LUNA, FTT) are absent, which biases results upward"
)
DEFAULT: dict[str, Any] = {
    "schema": SCHEMA,
    "name": "binance-spot-store",
    "source": "binance-spot",
    "instruments": "all-in-store",
    "calendar": "calendar-days",
    "annual_periods": 365,
    "liquidity": None,
    "min_names": 5,
    "min_universe": 15,
    "survivorship": DEFAULT_SURVIVORSHIP,
}
KEYS = set(DEFAULT)


def validate(spec: Any) -> dict[str, Any]:
    """A universe file, checked; a malformed one fails loud."""
    if (
        not isinstance(spec, dict)
        or set(spec) not in (KEYS, KEYS | {"data_dir"})
        or spec["schema"] != SCHEMA
    ):
        raise DataError(f"universe file must be {SCHEMA} with exactly the keys {sorted(KEYS)}")
    if "data_dir" in spec and (
        not isinstance(spec["data_dir"], str)
        or not spec["data_dir"].strip()
        or not Path(spec["data_dir"]).is_absolute()
    ):
        # Existence is checked where the store is read (freeze), so a frozen run still loads
        # after its store is moved or unmounted.
        raise DataError("universe data_dir must name an absolute store directory")
    if not isinstance(spec["name"], str) or not spec["name"].strip():
        raise DataError("universe name must be a non-empty string")
    if spec["source"] not in SOURCES:
        raise DataError(f"universe source must be one of {SOURCES}")
    if spec["calendar"] not in CALENDARS:
        raise DataError(f"universe calendar must be one of {sorted(CALENDARS)}")
    if spec["annual_periods"] != CALENDARS[spec["calendar"]]["annual_periods"]:
        raise DataError("annual_periods must be the calendar's year length")
    instruments = spec["instruments"]
    if instruments != "all-in-store" and (
        not isinstance(instruments, list)
        or not instruments
        or len(set(instruments)) != len(instruments)
        or any(not isinstance(s, str) or not s.strip() for s in instruments)
    ):
        raise DataError("universe instruments must be 'all-in-store' or distinct names")
    for key in ("min_names", "min_universe"):
        if type(spec[key]) is not int or spec[key] < 1:
            raise DataError(f"universe {key} must be a positive integer")
    if spec["min_universe"] < 3 * spec["min_names"]:
        raise DataError("min_universe must hold three thirds of min_names each")
    if not isinstance(spec["survivorship"], str) or not spec["survivorship"].strip():
        raise DataError("universe survivorship disclosure must be stated")
    rule = spec["liquidity"]
    if rule is not None:
        if not isinstance(rule, dict) or set(rule) != {
            "lookback_days",
            "min_median_quote_volume",
            "max_names",
        }:
            raise DataError(
                "liquidity rule needs lookback_days, min_median_quote_volume, max_names"
            )
        if type(rule["lookback_days"]) is not int or rule["lookback_days"] < 1:
            raise DataError("liquidity lookback_days must be a positive integer")
        if type(rule["max_names"]) is not int or rule["max_names"] < spec["min_names"]:
            raise DataError("liquidity max_names must be at least min_names")
        volume = rule["min_median_quote_volume"]
        if type(volume) not in (int, float) or not math.isfinite(volume) or volume < 0:
            raise DataError("liquidity min_median_quote_volume must be finite and non-negative")
    return spec


def load(path: Path | None) -> dict[str, Any]:
    if path is None:
        return dict(DEFAULT)
    try:
        return validate(json.loads(path.read_bytes()))
    except (OSError, ValueError, UnicodeError) as error:
        raise DataError(f"unreadable universe file: {error}") from error


def frozen(panel_dir: Path) -> dict[str, Any]:
    """The universe a run was frozen with; runs frozen before ADR-0055 use the default."""
    path = panel_dir / "universe.json"
    return load(path) if path.exists() else dict(DEFAULT)


def evaluable(spec: dict[str, Any]) -> None:
    if spec["calendar"] != "calendar-days":
        raise DataError(
            f"universe {spec['name']!r} uses the {spec['calendar']} calendar, which is configured "
            "but not yet evaluable: the clocks, panel checks and replay assume consecutive "
            "calendar days"
        )


def eligibility(
    quote_volume: np.ndarray, volume_days: list[date], days: list[date], rule: dict[str, Any] | None
) -> np.ndarray:
    """Point-in-time liquidity mask, days x instruments.

    On decision day d an instrument is eligible when every one of its last ``lookback_days`` daily
    bars up to and including d exists (a bar dated d is known at d's close) and their median quote
    volume is at least ``min_median_quote_volume``; at most ``max_names`` of them are kept, highest
    median first (ties: lower column index, i.e. instrument name order). Only bars dated on or
    before d are read, so the mask at d never depends on a later bar. No rule: all are eligible.
    """
    if rule is None:
        return np.ones((len(days), quote_volume.shape[1]), dtype=bool)
    if any((b - a).days != 1 for a, b in zip(volume_days, volume_days[1:], strict=False)):
        raise DataError("liquidity rule needs consecutive daily volume dates")
    index = {day: i for i, day in enumerate(volume_days)}
    window = rule["lookback_days"]
    mask = np.zeros((len(days), quote_volume.shape[1]), dtype=bool)
    for row, day in enumerate(days):
        end = index.get(day)
        if end is None or day - timedelta(days=window - 1) < volume_days[0]:
            continue
        block = quote_volume[end - window + 1 : end + 1]
        complete = np.isfinite(block).all(axis=0)
        medians = np.where(complete, np.median(np.where(complete, block, 0.0), axis=0), -np.inf)
        passing = [
            j for j in range(block.shape[1]) if medians[j] >= rule["min_median_quote_volume"]
        ]
        kept = sorted(passing, key=lambda j: (-medians[j], j))[: rule["max_names"]]
        mask[row, kept] = True
    return mask
