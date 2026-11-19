"""Options records: typed, frozen, and loud about invalid data."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from alpha_core import DataError
from alpha_data.options import (
    ChainRow,
    ChainSnapshot,
    ContractId,
    Greeks,
    OptionsDataError,
    Quote,
    Trade,
    quote_labels,
)

SNAP = datetime(2023, 3, 1, 21, 0, tzinfo=UTC)


BASE = ContractId(
    underlying_id="AAA",
    root="AAA",
    expiry=date(2023, 4, 21),
    strike=Decimal("100"),
    right="C",
    style="A",
    multiplier=100,
    listed_on=None,
    provider_symbol="vendor-1",
)


def contract(**changes: Any) -> ContractId:
    return dataclasses.replace(BASE, **changes)


def quote(bid: float = 1.0, ask: float = 1.2, ts: datetime = SNAP) -> Quote:
    return Quote(bid=bid, ask=ask, bid_size=10, ask_size=12, quote_ts=ts)


def row(c: ContractId | None = None, q: Quote | None = None) -> ChainRow:
    return ChainRow(contract=c or contract(), quote=q or quote())


def snap(
    rows: tuple[ChainRow, ...] | None = None,
    ts: datetime = SNAP,
    known: datetime | None = None,
    price: float = 101.0,
) -> ChainSnapshot:
    return ChainSnapshot(
        provider="fixture",
        underlying_id="AAA",
        snapshot_ts=ts,
        known_at=known or ts,
        underlying_price=price,
        rows=rows if rows is not None else (row(),),
    )


def field_of(exc: pytest.ExceptionInfo[OptionsDataError]) -> str:
    return exc.value.field


def test_error_is_a_data_error_and_names_the_field() -> None:
    with pytest.raises(OptionsDataError) as exc:
        quote(bid=-1.0)
    assert isinstance(exc.value, DataError)
    assert field_of(exc) == "bid"
    assert "bid" in str(exc.value)


def test_records_are_frozen() -> None:
    for record in (
        contract(),
        quote(),
        Trade(last=1.0, last_ts=SNAP),
        Greeks(source="provided", model="m"),
        row(),
        snap(),
    ):
        field = dataclasses.fields(record)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(record, field, None)


def test_contract_key_ignores_provider_symbol_and_keeps_it_as_provenance() -> None:
    a, b = contract(provider_symbol="x"), contract(provider_symbol="y")
    assert a.key == b.key
    assert a.provider_symbol == "x"
    assert contract(strike=Decimal("100.00")).key == a.key
    assert contract(right="P").key != a.key


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-5"), Decimal("NaN")])
def test_strike_must_be_positive_and_finite(bad: Decimal) -> None:
    with pytest.raises(OptionsDataError) as exc:
        contract(strike=bad)
    assert field_of(exc) == "strike"


def test_unknown_right_style_and_multiplier() -> None:
    with pytest.raises(OptionsDataError) as exc:
        contract(right="X")
    assert field_of(exc) == "right"
    with pytest.raises(OptionsDataError) as exc:
        contract(style="Z")
    assert field_of(exc) == "style"
    with pytest.raises(OptionsDataError) as exc:
        contract(multiplier=0)
    assert field_of(exc) == "multiplier"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01])
def test_prices_must_be_finite_and_not_negative(bad: float) -> None:
    with pytest.raises(OptionsDataError) as exc:
        Quote(bid=bad, ask=2.0, quote_ts=SNAP)
    assert field_of(exc) == "bid"
    with pytest.raises(OptionsDataError) as exc:
        Quote(bid=1.0, ask=bad, quote_ts=SNAP)
    assert field_of(exc) == "ask"
    with pytest.raises(OptionsDataError) as exc:
        Trade(last=bad, last_ts=SNAP, volume=1)
    assert field_of(exc) == "last"


def test_crossed_and_zero_width_quotes_are_labelled_not_rejected() -> None:
    assert quote_labels(quote(bid=2.0, ask=1.0)) == ("crossed",)
    assert quote_labels(quote(bid=1.0, ask=1.0)) == ("zero_width",)
    assert quote_labels(quote()) == ()


def test_naive_datetimes_are_refused_everywhere() -> None:
    naive = datetime(2023, 3, 1, 21, 0)
    with pytest.raises(OptionsDataError) as exc:
        quote(ts=naive)
    assert field_of(exc) == "quote_ts"
    with pytest.raises(OptionsDataError) as exc:
        snap(ts=naive)
    assert field_of(exc) == "snapshot_ts"
    with pytest.raises(OptionsDataError) as exc:
        snap(known=naive)
    assert field_of(exc) == "known_at"
    with pytest.raises(OptionsDataError) as exc:
        snap(ts=SNAP.astimezone(timezone(timedelta(hours=2))))
    assert field_of(exc) == "snapshot_ts"


def test_known_at_cannot_precede_the_snapshot() -> None:
    with pytest.raises(OptionsDataError) as exc:
        snap(known=SNAP - timedelta(seconds=1))
    assert field_of(exc) == "known_at"


def test_duplicate_contract_in_one_snapshot_is_refused() -> None:
    with pytest.raises(OptionsDataError) as exc:
        snap(rows=(row(contract(provider_symbol="a")), row(contract(provider_symbol="b"))))
    assert field_of(exc) == "contract"


def test_expired_contract_relative_to_the_snapshot_is_invalid() -> None:
    with pytest.raises(OptionsDataError) as exc:
        snap(rows=(row(contract(expiry=date(2023, 2, 28))),))
    assert field_of(exc) == "expiry"
    snap(rows=(row(contract(expiry=date(2023, 3, 1))),))  # expires today: still listed


def test_contract_cannot_appear_before_its_listing_date() -> None:
    with pytest.raises(OptionsDataError) as exc:
        snap(rows=(row(contract(listed_on=date(2023, 3, 2))),))
    assert field_of(exc) == "listed_on"


def test_quote_from_after_known_at_is_refused() -> None:
    with pytest.raises(OptionsDataError) as exc:
        snap(rows=(row(q=quote(ts=SNAP + timedelta(minutes=1))),))
    assert field_of(exc) == "quote_ts"


def test_underlying_must_match_and_price_be_positive() -> None:
    with pytest.raises(OptionsDataError) as exc:
        snap(rows=(row(contract(underlying_id="BBB")),))
    assert field_of(exc) == "underlying_id"
    with pytest.raises(OptionsDataError) as exc:
        snap(price=0.0)
    assert field_of(exc) == "underlying_price"


def test_provided_and_computed_greeks_are_kept_apart_with_a_source_field() -> None:
    provided = Greeks(source="provided", model="vendor-smoothed", iv=0.2, delta=0.5)
    computed = Greeks(source="computed", model="alpha-bs-v1", iv=0.21)
    r = ChainRow(contract=contract(), quote=quote(), provided=provided, computed=computed)
    assert (r.provided, r.computed) == (provided, computed)
    with pytest.raises(OptionsDataError) as exc:
        ChainRow(contract=contract(), quote=quote(), provided=computed)
    assert field_of(exc) == "provided"
    with pytest.raises(OptionsDataError) as exc:
        Greeks(source="guess", model="m")
    assert field_of(exc) == "source"
    with pytest.raises(OptionsDataError) as exc:
        Greeks(source="provided", model="m", iv=float("nan"))
    assert field_of(exc) == "iv"
    with pytest.raises(OptionsDataError) as exc:
        Greeks(source="provided", model="m", iv=-0.1)
    assert field_of(exc) == "iv"


def test_provided_iv_zero_is_a_labelled_sentinel_not_an_error() -> None:
    g = Greeks(source="provided", model="vendor", iv=0.0)
    assert g.labels == ("iv_sentinel",)
    assert Greeks(source="provided", model="vendor", iv=0.2).labels == ()
