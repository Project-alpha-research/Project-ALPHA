"""Derived daily options series: iv30, IV rank and percentile, 25-delta skew, term slope, IV - RV.

Descriptive context, never a signal: readings with no thresholds. Each value is computed from the
stored chain snapshots passed in (the caller reads them through `OptionsStore.snapshots_as_of`,
the capped research read) and carries `known_from`.

Rules (the numbers are in `derived_params`; the per-expiry reading is in `derived_surface`)
- Session: one per snapshot day; if a day has several snapshots the latest one is kept.
- Constant maturity: the two usable expiries around the target (largest at or before it, smallest
  at or after it). Total variance sigma^2 * T is linear in T between them. One side missing: null
  with a reason, never extrapolated. An expiry exactly at the target is used alone.
- iv30: constant-maturity ATM IV at 30 days. term_slope: the same at 90 days minus iv30.
- skew_25d: 25-delta put IV minus 25-delta call IV, each put through the same time rule at 30 days.
- iv_rank_252 = (iv30 - min) / (max - min) over the last 252 sessions including today.
  iv_percentile_252 = share of those 252 values strictly below today's. Fewer than 252 sessions,
  a null day in the window, or max = min: null with a reason.
- iv_minus_rv = iv30 - realized volatility (caller-supplied, see `RealizedPoint`).
- known_from: the snapshot's own `known_at`; for rank and percentile the latest `known_at` in the
  window; for iv_minus_rv the later of the snapshot's and the realized value's. Never earlier.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from alpha_data.options.derived_params import (
    DAYS_PER_YEAR,
    RANK_WINDOW,
    SERIES,
    TARGET_LONG_DAYS,
    TARGET_SHORT_DAYS,
    SurfaceConfig,
)
from alpha_data.options.derived_surface import (
    ExpiryReading,
    read_expiry,
    usable_expiries,
)
from alpha_data.options.schema import ChainSnapshot, OptionsDataError
from alpha_data.options.store import SnapshotsRead

__all__ = [
    "DerivedPoint",
    "DerivedResult",
    "Maturity",
    "RealizedPoint",
    "constant_maturity",
    "derive",
    "interpolate_total_variance",
    "rank_and_percentile",
]


@dataclass(frozen=True)
class RealizedPoint:
    """Realized volatility of the underlying for one day and the instant it became known."""

    value: float
    known_from: datetime


@dataclass(frozen=True)
class DerivedPoint:
    day: date
    value: float | None
    reason: str | None
    known_from: datetime
    label: str = ""


@dataclass(frozen=True)
class DerivedResult:
    series: dict[str, tuple[DerivedPoint, ...]]
    sessions: int
    held_back: int


@dataclass(frozen=True)
class Maturity:
    """A constant-maturity reading: ATM IV, wings, the forward label and reasons for nulls."""

    atm: float | None
    put25: float | None
    call25: float | None
    atm_reason: str | None
    wing_reason: str | None
    label: str


def interpolate_total_variance(
    t1: float, vol1: float, t2: float, vol2: float, target: float
) -> float:
    """Vol at `target` when total variance vol^2 * T is linear in T between (t1, t2)."""
    if t1 == t2:
        return vol1
    w = vol1 * vol1 * t1 + (vol2 * vol2 * t2 - vol1 * vol1 * t1) * (target - t1) / (t2 - t1)
    return math.sqrt(w / target)


def _bracket(years: Mapping[date, float], target_days: int) -> tuple[date, date] | str:
    target = target_days / DAYS_PER_YEAR
    below = [(y, e) for e, y in years.items() if y <= target + 1e-12]
    above = [(y, e) for e, y in years.items() if y >= target - 1e-12]
    if not below:
        return f"no_expiry_at_or_below_{target_days}d"
    if not above:
        return f"no_expiry_at_or_above_{target_days}d"
    return max(below)[1], min(above)[1]


def _blend(
    a: float | None, b: float | None, lo: ExpiryReading, hi: ExpiryReading, t: float
) -> float | None:
    if a is None or b is None:
        return None
    return interpolate_total_variance(lo.years, a, hi.years, b, t)


def constant_maturity(
    snapshot: ChainSnapshot, cfg: SurfaceConfig, target_days: int, *, wings: bool = False
) -> Maturity | str:
    """The constant-maturity reading at `target_days`, or the reason there is none."""
    years = usable_expiries(snapshot, cfg)
    found = _bracket(years, target_days)
    if isinstance(found, str):
        return found
    lo = read_expiry(snapshot, found[0], cfg, wings=wings)
    hi = lo if found[1] == found[0] else read_expiry(snapshot, found[1], cfg, wings=wings)
    t = target_days / DAYS_PER_YEAR
    reason = lo.atm_reason or hi.atm_reason
    atm = _blend(lo.atm_iv, hi.atm_iv, lo, hi, t)
    label = lo.atm_label if lo.atm_label == hi.atm_label else "mixed"
    if not wings:
        return Maturity(atm, None, None, reason, None, label)
    put = _blend(lo.put25, hi.put25, lo, hi, t)
    call = _blend(lo.call25, hi.call25, lo, hi, t)
    wing_reason = lo.wing_reason or hi.wing_reason
    return Maturity(atm, put, call, reason, wing_reason, label)


def rank_and_percentile(
    values: Sequence[float | None], window: int = RANK_WINDOW
) -> list[tuple[float | None, float | None, str | None]]:
    """Rank and percentile of each value among the trailing `window` values including itself."""
    out: list[tuple[float | None, float | None, str | None]] = []
    for i, today in enumerate(values):
        if i + 1 < window:
            out.append((None, None, f"warm_up_{window}"))
            continue
        span = values[i + 1 - window : i + 1]
        if today is None:
            out.append((None, None, "iv30_missing"))
        elif any(v is None for v in span):
            out.append((None, None, "gap_in_window"))
        else:
            nums = [v for v in span if v is not None]
            lo, hi = min(nums), max(nums)
            if hi == lo:
                out.append((None, None, "flat_window"))
            else:
                share = sum(1 for v in nums if v < today) / window
                out.append(((today - lo) / (hi - lo), share, None))
    return out


def _sessions(read: SnapshotsRead) -> list[ChainSnapshot]:
    latest: dict[date, ChainSnapshot] = {}
    for snap in read.snapshots:
        day = snap.snapshot_ts.date()
        kept = latest.get(day)
        if kept is None or (snap.known_at, snap.snapshot_ts) >= (kept.known_at, kept.snapshot_ts):
            latest[day] = snap
    return [latest[d] for d in sorted(latest)]


def _maturity_points(
    sessions: list[ChainSnapshot], cfg: SurfaceConfig, names: set[str]
) -> dict[str, list[DerivedPoint]]:
    out: dict[str, list[DerivedPoint]] = {n: [] for n in ("iv30", "skew_25d", "term_slope")}
    for snap in sessions:
        day, known = snap.snapshot_ts.date(), snap.known_at
        short = constant_maturity(snap, cfg, TARGET_SHORT_DAYS, wings="skew_25d" in names)
        s_atm = short.atm if isinstance(short, Maturity) else None
        s_reason = short if isinstance(short, str) else (short.atm_reason or "atm_unavailable")
        label = short.label if isinstance(short, Maturity) else ""
        out["iv30"].append(
            DerivedPoint(day, s_atm, None if s_atm is not None else s_reason, known, label)
        )
        skew, why = None, s_reason if not isinstance(short, Maturity) else short.wing_reason
        if isinstance(short, Maturity) and short.put25 is not None and short.call25 is not None:
            skew, why = short.put25 - short.call25, None
        out["skew_25d"].append(DerivedPoint(day, skew, why, known, label))
        term, why = None, s_reason
        if "term_slope" in names and s_atm is not None:
            long = constant_maturity(snap, cfg, TARGET_LONG_DAYS)
            if isinstance(long, str):
                why = long
            elif long.atm is None:
                why = long.atm_reason or "atm_unavailable"
            else:
                term, why = long.atm - s_atm, None
        out["term_slope"].append(DerivedPoint(day, term, why, known, label))
    return out


def derive(
    read: SnapshotsRead,
    cfg: SurfaceConfig | None = None,
    *,
    series: Sequence[str] = SERIES,
    realized: Mapping[date, RealizedPoint] | None = None,
    rank_window: int = RANK_WINDOW,
) -> DerivedResult:
    """Compute the requested series for every stored session in `read` (oldest first)."""
    unknown = [s for s in series if s not in SERIES]
    if unknown:
        raise OptionsDataError("series", f"unknown series {unknown}; known: {list(SERIES)}")
    cfg = cfg or SurfaceConfig()
    sessions = _sessions(read)
    need_iv = {"iv30", "iv_rank_252", "iv_percentile_252", "iv_minus_rv", "term_slope"}
    names = set(series)
    base = _maturity_points(sessions, cfg, names) if names & (need_iv | {"skew_25d"}) else {}
    iv30 = base.get("iv30", [])
    out: dict[str, tuple[DerivedPoint, ...]] = {}
    if names & {"iv_rank_252", "iv_percentile_252"}:
        ranked = rank_and_percentile([p.value for p in iv30], rank_window)
        for name, rank_slot in (("iv_rank_252", True), ("iv_percentile_252", False)):
            out[name] = tuple(
                DerivedPoint(
                    p.day,
                    r[0] if rank_slot else r[1],
                    r[2],
                    max(q.known_from for q in iv30[max(0, i + 1 - rank_window) : i + 1]),
                )
                for i, (p, r) in enumerate(zip(iv30, ranked, strict=True))
            )
    if "iv_minus_rv" in names:
        out["iv_minus_rv"] = tuple(_iv_minus_rv(p, (realized or {}).get(p.day)) for p in iv30)
    for name in ("iv30", "skew_25d", "term_slope"):
        if name in names:
            out[name] = tuple(base[name])
    return DerivedResult({n: out[n] for n in series}, len(sessions), read.held_back)


def _iv_minus_rv(iv30: DerivedPoint, rv: RealizedPoint | None) -> DerivedPoint:
    if iv30.value is None:
        return DerivedPoint(iv30.day, None, iv30.reason or "iv30_missing", iv30.known_from)
    if rv is None:
        return DerivedPoint(iv30.day, None, "no_realized_vol", iv30.known_from)
    return DerivedPoint(iv30.day, iv30.value - rv.value, None, max(iv30.known_from, rv.known_from))
