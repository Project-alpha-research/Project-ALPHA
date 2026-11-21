"""One expiry of one stored chain, read as at-the-money and 25-delta volatilities.

Pure math on a `ChainSnapshot` already read through the capped store read. No clock, no reads.

Rules (all constants in `derived_params`)
- Quotes: only rows with a mid count. Crossed, zero-width, zero-bid and missing quotes are dropped.
  An expiry needs `MIN_QUOTED_STRIKES` strikes with a mid, and `MIN_DAYS_TO_EXPIRY` days to run.
- Forward: when European calls and puts both quote at a strike, F = K + exp(rT)(C - P) at the strike
  with the smallest |C - P|. Rows are then solved with Black-76 on F. Else (no pair, or American
  style) F = S exp((r - q)T), ATM is the listed strike nearest spot, and the label says so.
- Solving: European rows use `solve_implied_vol`; American rows use `solve_row` (CRR tree, no cash
  dividends, `cfg.american_steps`). A low-confidence solve is dropped, never used.
- ATM IV: the mean of the call and put IV at a strike; linear in strike between the two listed
  strikes around F. If F is outside the listed strikes the reading is null, never extrapolated.
- 25-delta wings: OTM options only (puts with K <= F, calls with K >= F). IV is linear in absolute
  forward delta N(d1) (undiscounted) between the two options around 0.25. For American rows the
  delta is the closed-form delta at the solved IV, an approximation.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from alpha_data.options.derived_params import (
    LABEL_NEAREST,
    LABEL_PARITY,
    MIN_DAYS_TO_EXPIRY,
    MIN_QUOTED_STRIKES,
    WING_DELTA,
    SurfaceConfig,
)
from alpha_data.options.implied import IvSolved, mid_price, solve_implied_vol, solve_row
from alpha_data.options.iv_core import years_between
from alpha_data.options.pricing import OptionInputs, greeks
from alpha_data.options.schema import ChainRow, ChainSnapshot

Sides = dict[str, tuple[ChainRow, float]]


@dataclass(frozen=True)
class ExpiryReading:
    """What one expiry gives: ATM IV, 25-delta put and call IV, each with a reason when null."""

    expiry: date
    years: float
    atm_iv: float | None
    atm_label: str
    atm_reason: str | None
    put25: float | None
    call25: float | None
    wing_reason: str | None


def _quoted(snapshot: ChainSnapshot, expiry: date) -> dict[Decimal, Sides]:
    out: dict[Decimal, Sides] = {}
    for row in snapshot.rows:
        c = row.contract
        if c.expiry != expiry or row.quote is None:
            continue
        mid = mid_price(row.quote).value
        if mid is not None:
            out.setdefault(c.strike, {})[c.right] = (row, mid)
    return out


def expiry_years(snapshot: ChainSnapshot, expiry: date, cfg: SurfaceConfig) -> float:
    return years_between(snapshot.snapshot_ts, datetime.combine(expiry, cfg.expiry_time_utc, UTC))


def usable_expiries(snapshot: ChainSnapshot, cfg: SurfaceConfig) -> dict[date, float]:
    """Expiry -> years, for expiries far enough out and with enough quoted strikes."""
    found: dict[date, float] = {}
    for expiry in sorted({r.contract.expiry for r in snapshot.rows}):
        years = expiry_years(snapshot, expiry, cfg)
        if years * 365.0 < MIN_DAYS_TO_EXPIRY:
            continue
        if len(_quoted(snapshot, expiry)) >= MIN_QUOTED_STRIKES:
            found[expiry] = years
    return found


def _parity_forward(by_strike: dict[Decimal, Sides], years: float, rate: float) -> float | None:
    best: tuple[float, float] | None = None
    for strike, sides in by_strike.items():
        pair = (sides.get("C"), sides.get("P"))
        if pair[0] is None or pair[1] is None:
            continue
        if pair[0][0].contract.style != "E" or pair[1][0].contract.style != "E":
            continue
        diff = pair[0][1] - pair[1][1]
        if best is None or abs(diff) < abs(best[1]):
            best = (float(strike), diff)
    if best is None:
        return None
    forward = best[0] + math.exp(rate * years) * best[1]
    return forward if forward > 0 else None


def _solver(
    snapshot: ChainSnapshot, years: float, forward: float, parity: bool, cfg: SurfaceConfig
) -> Callable[[ChainRow, float], float | None]:
    """IV of one row from its mid, or None when unsolved or low confidence."""

    def solve(row: ChainRow, mid: float) -> float | None:
        c = row.contract
        if c.style == "A":
            out = solve_row(
                row,
                snapshot_ts=snapshot.snapshot_ts,
                underlying_price=snapshot.underlying_price,
                rate=cfg.rate,
                dividend_yield=cfg.dividend_yield,
                expiry_time_utc=cfg.expiry_time_utc,
                dividends=(),
                steps=cfg.american_steps,
            ).outcome
        else:
            inp = (
                OptionInputs(
                    underlying=forward, kind="forward", strike=float(c.strike), years=years,
                    rate=cfg.rate, dividend_yield=None, right=c.right,
                )
                if parity
                else OptionInputs(
                    underlying=snapshot.underlying_price, kind="spot", strike=float(c.strike),
                    years=years, rate=cfg.rate, dividend_yield=cfg.dividend_yield, right=c.right,
                )
            )  # fmt: skip
            out = solve_implied_vol(inp, mid, style="E")
        return out.iv if isinstance(out, IvSolved) and out.confidence == "normal" else None

    return solve


def _interp(points: list[tuple[float, float]], x: float) -> float | None:
    """Linear interpolation inside sorted (x, y) points; None outside them (no extrapolation)."""
    for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
        if x1 <= x <= x2:
            return y1 if x2 == x1 else y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    return points[0][1] if len(points) == 1 and points[0][0] == x else None


def _atm(
    iv_at: Callable[[Decimal], float | None],
    strikes: list[Decimal],
    forward: float,
    spot: float,
    parity: bool,
) -> tuple[float | None, str | None]:
    if not parity:
        for strike in sorted(strikes, key=lambda k: (abs(float(k) - spot), k)):
            iv = iv_at(strike)
            if iv is not None:
                return iv, None
        return None, "atm_unavailable"
    below = [k for k in sorted(strikes, reverse=True) if float(k) <= forward]
    above = [k for k in sorted(strikes) if float(k) >= forward]
    lo = next(((k, v) for k in below if (v := iv_at(k)) is not None), None)
    hi = next(((k, v) for k in above if (v := iv_at(k)) is not None), None)
    if lo is None or hi is None:
        return None, "forward_outside_listed_strikes"
    value = _interp([(float(lo[0]), lo[1]), (float(hi[0]), hi[1])], forward)
    return value, None if value is not None else "forward_outside_listed_strikes"


def _wings(
    by_strike: dict[Decimal, Sides],
    solve: Callable[[ChainRow, float], float | None],
    forward: float,
    years: float,
    cfg: SurfaceConfig,
) -> tuple[float | None, float | None, str | None]:
    pts: dict[str, list[tuple[float, float]]] = {"P": [], "C": []}
    for strike, sides in by_strike.items():
        k = float(strike)
        for right in ("P", "C"):
            otm = k <= forward if right == "P" else k >= forward
            if right not in sides or not otm:
                continue
            row, mid = sides[right]
            iv = solve(row, mid)
            if iv is None:
                continue
            inp = OptionInputs(
                underlying=forward, kind="forward", strike=k, years=years, rate=cfg.rate,
                dividend_yield=None, right=right,
            )  # fmt: skip
            pts[right].append((abs(greeks(inp, iv).delta / inp.discount), iv))
    out = {r: _interp(sorted(p), WING_DELTA) for r, p in pts.items()}
    if out["P"] is None:
        return None, out["C"], "put_wing_not_bracketed"
    if out["C"] is None:
        return out["P"], None, "call_wing_not_bracketed"
    return out["P"], out["C"], None


def read_expiry(
    snapshot: ChainSnapshot, expiry: date, cfg: SurfaceConfig, *, wings: bool
) -> ExpiryReading:
    """ATM IV (and the 25-delta wings when asked) of one expiry; null values carry a reason."""
    years = expiry_years(snapshot, expiry, cfg)
    by_strike = _quoted(snapshot, expiry)
    parity_f = _parity_forward(by_strike, years, cfg.rate)
    parity = parity_f is not None
    forward = parity_f or snapshot.underlying_price * math.exp(
        (cfg.rate - cfg.dividend_yield) * years
    )
    solve = _solver(snapshot, years, forward, parity, cfg)
    cache: dict[Decimal, float | None] = {}

    def iv_at(strike: Decimal) -> float | None:
        if strike not in cache:
            vals = [v for r, m in by_strike[strike].values() if (v := solve(r, m)) is not None]
            cache[strike] = sum(vals) / len(vals) if vals else None
        return cache[strike]

    atm, reason = _atm(iv_at, list(by_strike), forward, snapshot.underlying_price, parity)
    label = LABEL_PARITY if parity else LABEL_NEAREST
    if not wings:
        return ExpiryReading(expiry, years, atm, label, reason, None, None, None)
    put, call, wing_reason = _wings(by_strike, solve, forward, years, cfg)
    return ExpiryReading(expiry, years, atm, label, reason, put, call, wing_reason)
