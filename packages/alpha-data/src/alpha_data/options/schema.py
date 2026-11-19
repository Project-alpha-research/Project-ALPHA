"""Provider-neutral option records: contract identity, quotes, trades, greeks, chain snapshots.

Every record is frozen and checks itself on construction. A bad value raises `OptionsDataError`
naming the field. Quotes and trades are separate records. Provider greeks and computed greeks are
separate slots, and each carries a `source` field saying which it is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from alpha_core import DataError

RIGHTS = ("C", "P")
STYLES = ("A", "E")
GREEK_SOURCES = ("provided", "computed")


class OptionsDataError(DataError):
    """Invalid options data. `field` names the offending field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"options {field}: {message}")
        self.field = field


def aware_utc(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise OptionsDataError(field, "must be a timezone-aware UTC datetime")
    return value


def _number(field: str, value: object, *, minimum: float | None = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise OptionsDataError(field, f"must be a finite number, got {value!r}")
    if minimum is not None and value < minimum:
        raise OptionsDataError(field, f"must not be below {minimum:g}, got {value!r}")
    return float(value)


def _count(field: str, value: object) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise OptionsDataError(field, f"must be a non-negative integer or None, got {value!r}")


def _text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise OptionsDataError(field, "must be a non-empty string")


@dataclass(frozen=True, kw_only=True)
class ContractId:
    """One option contract. `provider_symbol` is provenance and never part of the identity."""

    underlying_id: str
    root: str
    expiry: date
    strike: Decimal
    right: str
    style: str
    multiplier: int
    listed_on: date | None
    provider_symbol: str

    def __post_init__(self) -> None:
        for name in ("underlying_id", "root", "provider_symbol"):
            _text(name, getattr(self, name))
        if not isinstance(self.expiry, date) or isinstance(self.expiry, datetime):
            raise OptionsDataError("expiry", "must be a date")
        if self.listed_on is not None and (
            not isinstance(self.listed_on, date) or isinstance(self.listed_on, datetime)
        ):
            raise OptionsDataError("listed_on", "must be a date or None")
        if not isinstance(self.strike, Decimal) or not self.strike.is_finite() or self.strike <= 0:
            raise OptionsDataError(
                "strike", f"must be a finite Decimal above zero: {self.strike!r}"
            )
        if self.right not in RIGHTS:
            raise OptionsDataError("right", f"must be one of {RIGHTS}, got {self.right!r}")
        if self.style not in STYLES:
            raise OptionsDataError("style", f"must be one of {STYLES}, got {self.style!r}")
        if isinstance(self.multiplier, bool) or not isinstance(self.multiplier, int):
            raise OptionsDataError("multiplier", "must be an integer")
        if self.multiplier <= 0:
            raise OptionsDataError("multiplier", f"must be positive, got {self.multiplier}")

    @property
    def key(self) -> str:
        """Exchange-agnostic identity; the provider's own symbol is not part of it."""
        strike = format(self.strike.normalize(), "f")
        return (
            f"{self.underlying_id}|{self.root}|{self.expiry.isoformat()}|{self.right}|"
            f"{self.style}|{self.multiplier}|{strike}"
        )


@dataclass(frozen=True, kw_only=True)
class Quote:
    """Bid and ask at a stated time. Crossed or zero-width quotes are kept and labelled."""

    bid: float
    ask: float
    bid_size: int | None = None
    ask_size: int | None = None
    quote_ts: datetime

    def __post_init__(self) -> None:
        _number("bid", self.bid)
        _number("ask", self.ask)
        _count("bid_size", self.bid_size)
        _count("ask_size", self.ask_size)
        aware_utc("quote_ts", self.quote_ts)


@dataclass(frozen=True, kw_only=True)
class Trade:
    """The last trade, kept apart from the quote."""

    last: float
    last_ts: datetime
    volume: int | None = None

    def __post_init__(self) -> None:
        _number("last", self.last)
        aware_utc("last_ts", self.last_ts)
        _count("volume", self.volume)


@dataclass(frozen=True, kw_only=True)
class Greeks:
    """One block of implied volatility and greeks, from the provider or computed by ALPHA."""

    source: str
    model: str
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    vega: float | None = None
    theta: float | None = None

    def __post_init__(self) -> None:
        if self.source not in GREEK_SOURCES:
            raise OptionsDataError("source", f"must be one of {GREEK_SOURCES}, got {self.source!r}")
        _text("model", self.model)
        if self.iv is not None:
            _number("iv", self.iv)
        for name in ("delta", "gamma", "vega", "theta"):
            value = getattr(self, name)
            if value is not None:
                _number(name, value, minimum=None)

    @property
    def labels(self) -> tuple[str, ...]:
        """A provider IV of exactly zero is a vendor sentinel for "could not solve"."""
        return ("iv_sentinel",) if self.source == "provided" and self.iv == 0.0 else ()


def quote_labels(quote: Quote) -> tuple[str, ...]:
    if quote.bid > quote.ask:
        return ("crossed",)
    return ("zero_width",) if quote.bid == quote.ask else ()


@dataclass(frozen=True, kw_only=True)
class ChainRow:
    """One contract inside a snapshot, with its quote, trade, open interest and greeks."""

    contract: ContractId
    quote: Quote | None = None
    trade: Trade | None = None
    open_interest: int | None = None
    oi_as_of: date | None = None
    provided: Greeks | None = None
    computed: Greeks | None = None

    def __post_init__(self) -> None:
        _count("open_interest", self.open_interest)
        if self.provided is not None and self.provided.source != "provided":
            raise OptionsDataError("provided", "slot holds greeks whose source is not 'provided'")
        if self.computed is not None and self.computed.source != "computed":
            raise OptionsDataError("computed", "slot holds greeks whose source is not 'computed'")

    @property
    def labels(self) -> tuple[str, ...]:
        """Every label on this row (quote shape, provider IV sentinel); they travel with the row."""
        quote = quote_labels(self.quote) if self.quote is not None else ()
        return quote + (self.provided.labels if self.provided is not None else ())


@dataclass(frozen=True, kw_only=True)
class ChainSnapshot:
    """Contracts with quotes at ONE snapshot time, known from `known_at` onward."""

    provider: str
    underlying_id: str
    snapshot_ts: datetime
    known_at: datetime
    underlying_price: float
    rows: tuple[ChainRow, ...]

    def __post_init__(self) -> None:
        _text("provider", self.provider)
        _text("underlying_id", self.underlying_id)
        aware_utc("snapshot_ts", self.snapshot_ts)
        aware_utc("known_at", self.known_at)
        if self.known_at < self.snapshot_ts:
            raise OptionsDataError("known_at", "must not precede snapshot_ts")
        _number("underlying_price", self.underlying_price)
        if self.underlying_price == 0:
            raise OptionsDataError("underlying_price", "must be above zero")
        today = self.snapshot_ts.date()
        seen: set[str] = set()
        for r in self.rows:
            c = r.contract
            if c.underlying_id != self.underlying_id:
                raise OptionsDataError(
                    "underlying_id", f"contract {c.key} is on another underlying"
                )
            if c.key in seen:
                raise OptionsDataError("contract", f"duplicate contract in one snapshot: {c.key}")
            seen.add(c.key)
            if c.expiry < today:
                raise OptionsDataError("expiry", f"{c.key} expired before the snapshot")
            if c.listed_on is not None and c.listed_on > today:
                raise OptionsDataError("listed_on", f"{c.key} appears before its listing date")
            if r.quote is not None and r.quote.quote_ts > self.known_at:
                raise OptionsDataError("quote_ts", f"{c.key} quote is after known_at")
            if r.oi_as_of is not None and r.oi_as_of > self.known_at.date():
                raise OptionsDataError("oi_as_of", f"{c.key} open interest is after known_at")
            if r.trade is not None and r.trade.last_ts > self.known_at:
                raise OptionsDataError("last_ts", f"{c.key} trade is after known_at")
