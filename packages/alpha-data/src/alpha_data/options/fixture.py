"""Seeded synthetic chains from a known volatility surface, for tests and solver work.

No real market data. Two modes.
- Placeholder mode (default): quotes use a placeholder price shape (intrinsic value plus a time
  value that grows with the surface IV). It is NOT an option model: these prices are not
  arbitrage-free, and no implied-volatility solver can recover the stored surface IV from them.
  Never use this mode to judge a pricing or volatility method. It only tests records, storage and
  point-in-time reads. Contracts are American-style.
- Model-priced mode (`priced=PricedModel(rate, dividend_yield)`): every quote is centred on the
  Black-Scholes-Merton price (`alpha_data.options.pricing`) at the surface IV, with a symmetric
  spread capped at half the price, so the bid is never zero. Contracts are European-style, so the
  model price is exact and a solver can recover the surface IV from the quote mid. Time to
  expiry is ACT/365 from the snapshot to 21:00 UTC on the expiry day. The rate and dividend
  yield are the explicit values in `PricedModel`.
- American model-priced mode (`PricedModel(..., american_steps=N)`): the same, but contracts are
  American-style and the quotes are centred on the CRR tree price (`alpha_data.options.tree`)
  with N steps and the cash dividends in `PricedModel.dividends` (none by default). The solver
  recovers the surface IV when it uses the same steps and dividends.
The surface IV is stored as the provided IV in both modes so a check has a target.
"""

from __future__ import annotations

import calendar
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from alpha_core import DataError
from alpha_data.options.implied import years_between
from alpha_data.options.pricing import OptionInputs, price
from alpha_data.options.schema import ChainRow, ChainSnapshot, ContractId, Greeks, Quote
from alpha_data.options.tree import AmericanInputs, Dividend, TreeRefused, american_price

UNDERLYING = "AAA"
PROVIDER = "fixture"
STRIKES = tuple(Decimal(5 * k) for k in range(16, 25))
_MODEL = "synthetic-surface-v1"
EXPIRY_TIME_UTC = time(21, 0)
SPREAD_FLOOR = 0.01
SPREAD_FRACTION = 0.01


@dataclass(frozen=True)
class PricedModel:
    """Rate and dividend yield for the model-priced fixture mode. Both are explicit."""

    rate: float
    dividend_yield: float
    american_steps: int | None = None
    dividends: tuple[Dividend, ...] = ()


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
        self,
        seed: int,
        surface: VolSurface | None = None,
        strikes: tuple[Decimal, ...] = STRIKES,
        priced: PricedModel | None = None,
    ) -> None:
        self._seed = seed
        self._priced = priced
        self._strikes = strikes
        self._surface = surface or VolSurface()

    def list_underlyings(self) -> list[str]:
        return [UNDERLYING]

    def _contract(self, expiry: date, strike: Decimal, right: str) -> ContractId:
        style = "E" if self._priced is not None and self._priced.american_steps is None else "A"
        return ContractId(
            underlying_id=UNDERLYING,
            root=UNDERLYING,
            expiry=expiry,
            strike=strike,
            right=right,
            style=style,
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
        if self._priced is None:
            mid = intrinsic + 0.4 * iv * spot * math.sqrt(max(years, 1.0 / 365.0))
            half = max(0.01, 0.02 * mid)
            bid, ask = max(0.0, round(mid - half, 2)), round(mid + half, 2)
        else:
            bid, ask = self._model_quote(ts, expiry, strike, right, spot, iv)
        return ChainRow(
            contract=self._contract(expiry, strike, right),
            quote=Quote(
                bid=bid,
                ask=ask,
                bid_size=10,
                ask_size=12,
                quote_ts=ts,
            ),
            open_interest=100 + int(rng.random() * 900),
            oi_as_of=ts.date() - timedelta(days=1),
            provided=Greeks(source="provided", model=_MODEL, iv=iv),
        )

    def _model_quote(
        self, ts: datetime, expiry: date, strike: Decimal, right: str, spot: float, iv: float
    ) -> tuple[float, float]:
        """Bid and ask around the model price; the mid is the model price (spread is symmetric)."""
        assert self._priced is not None
        expiry_ts = datetime.combine(expiry, EXPIRY_TIME_UTC, UTC)
        if self._priced.american_steps is not None:
            tree = american_price(
                AmericanInputs(
                    spot=spot, strike=float(strike), valuation_ts=ts, expiry_ts=expiry_ts,
                    rate=self._priced.rate, dividend_yield=self._priced.dividend_yield,
                    dividends=self._priced.dividends, right=right,
                ),
                iv,
                self._priced.american_steps,
            )  # fmt: skip
            if isinstance(tree, TreeRefused):
                raise DataError(tree.message)
            return self._spread(tree)
        inp = OptionInputs(
            underlying=spot,
            kind="spot",
            strike=float(strike),
            years=years_between(ts, datetime.combine(expiry, EXPIRY_TIME_UTC, UTC)),
            rate=self._priced.rate,
            dividend_yield=self._priced.dividend_yield,
            right=right,
        )
        return self._spread(price(inp, iv))

    @staticmethod
    def _spread(value: float) -> tuple[float, float]:
        half = min(max(SPREAD_FLOOR, SPREAD_FRACTION * value), value / 2.0)  # bid stays above 0
        return value - half, value + half

    def contracts(self, underlying: str, start: date, end: date) -> list[ContractId]:
        found: dict[str, ContractId] = {}
        for offset in range((end - start).days + 1):
            for r in self.chain(underlying, start + timedelta(days=offset)).rows:
                found.setdefault(r.contract.key, r.contract)
        return sorted(found.values(), key=lambda c: c.key)
