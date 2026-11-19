"""Seeded synthetic chains from a known volatility surface, for tests and later solver work.

No real market data. Quotes use a placeholder price shape (intrinsic value plus a time value that
grows with the surface IV). It is NOT an option model: these prices are not arbitrage-free, and no
implied-volatility solver can recover the stored surface IV from them. Never use this fixture to
judge a pricing or volatility method. It only tests records, storage and point-in-time reads.
The solver build must add a fixture priced with a stated model (for example Black-Scholes at the
surface IV) so a solver can recover the known volatility. The surface IV is stored as the provided
IV so that later check has a target.
"""

from __future__ import annotations

import calendar
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from alpha_core import DataError
from alpha_data.options.schema import ChainRow, ChainSnapshot, ContractId, Greeks, Quote

UNDERLYING = "AAA"
PROVIDER = "fixture"
STRIKES = tuple(Decimal(5 * k) for k in range(16, 25))
_MODEL = "synthetic-surface-v1"


@dataclass(frozen=True)
class VolSurface:
    """IV = base + skew * (strike / spot - 1) + term * years, floored at one volatility point."""

    base: float = 0.20
    skew: float = -0.10
    term: float = 0.02

    def iv(self, strike: float, spot: float, years: float) -> float:
        return max(0.01, self.base + self.skew * (strike / spot - 1.0) + self.term * years)


def _month_ends(day: date, count: int) -> list[date]:
    ends: list[date] = []
    year, month = day.year, day.month
    while len(ends) < count:
        end = date(year, month, calendar.monthrange(year, month)[1])
        if end >= day + timedelta(days=7):
            ends.append(end)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return ends


class SyntheticAdapter:
    """Implements `OptionsAdapter` for one generic underlying, deterministic per seed."""

    def __init__(
        self, seed: int, surface: VolSurface | None = None, strikes: tuple[Decimal, ...] = STRIKES
    ) -> None:
        self._seed = seed
        self._strikes = strikes
        self._surface = surface or VolSurface()

    def list_underlyings(self) -> list[str]:
        return [UNDERLYING]

    def _contract(self, expiry: date, strike: Decimal, right: str) -> ContractId:
        return ContractId(
            underlying_id=UNDERLYING,
            root=UNDERLYING,
            expiry=expiry,
            strike=strike,
            right=right,
            style="A",
            multiplier=100,
            listed_on=expiry - timedelta(days=120),
            provider_symbol=f"{UNDERLYING}-{expiry:%y%m%d}-{right}-{strike}",
        )

    def chain(self, underlying: str, day: date) -> ChainSnapshot:
        if underlying != UNDERLYING:
            raise DataError(f"synthetic adapter has no underlying {underlying!r}")
        rng = random.Random(f"{self._seed}|{underlying}|{day.isoformat()}")
        spot = round(100.0 * (1.0 + 0.1 * (rng.random() - 0.5)), 4)
        ts = datetime.combine(day, time(21, 0), UTC)
        rows: list[ChainRow] = []
        for expiry in _month_ends(day, 3):
            years = (expiry - day).days / 365.0
            for strike in self._strikes:
                for right in ("C", "P"):
                    rows.append(self._row(rng, expiry, strike, right, spot, years, ts))
        return ChainSnapshot(
            provider=PROVIDER,
            underlying_id=UNDERLYING,
            snapshot_ts=ts,
            known_at=ts,
            underlying_price=spot,
            rows=tuple(rows),
        )

    def _row(
        self,
        rng: random.Random,
        expiry: date,
        strike: Decimal,
        right: str,
        spot: float,
        years: float,
        ts: datetime,
    ) -> ChainRow:
        k = float(strike)
        iv = self._surface.iv(k, spot, years)
        intrinsic = max(spot - k, 0.0) if right == "C" else max(k - spot, 0.0)
        mid = intrinsic + 0.4 * iv * spot * math.sqrt(max(years, 1.0 / 365.0))
        half = max(0.01, 0.02 * mid)
        return ChainRow(
            contract=self._contract(expiry, strike, right),
            quote=Quote(
                bid=max(0.0, round(mid - half, 2)),
                ask=round(mid + half, 2),
                bid_size=10,
                ask_size=12,
                quote_ts=ts,
            ),
            open_interest=100 + int(rng.random() * 900),
            oi_as_of=ts.date() - timedelta(days=1),
            provided=Greeks(source="provided", model=_MODEL, iv=iv),
        )

    def contracts(self, underlying: str, start: date, end: date) -> list[ContractId]:
        found: dict[str, ContractId] = {}
        for offset in range((end - start).days + 1):
            for r in self.chain(underlying, start + timedelta(days=offset)).rows:
                found.setdefault(r.contract.key, r.contract)
        return sorted(found.values(), key=lambda c: c.key)
