"""Chain snapshot <-> one flat Parquet frame (one row per contract, snapshot fields repeated)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data.options.schema import (
    ChainRow,
    ChainSnapshot,
    ContractId,
    Greeks,
    Quote,
    Trade,
)

TIME = pl.Datetime("us", "UTC")
_GREEKS = ("iv", "delta", "gamma", "vega", "theta")
SCHEMA: dict[str, Any] = {
    "snapshot_ts": TIME,
    "known_at": TIME,
    "provider": pl.String,
    "underlying_id": pl.String,
    "root": pl.String,
    "expiry": pl.Date,
    "right": pl.String,
    "strike": pl.String,  # exact decimal text, never a float
    "style": pl.String,
    "multiplier": pl.Int64,
    "listed_on": pl.Date,
    "provider_symbol": pl.String,
    "bid": pl.Float64,
    "ask": pl.Float64,
    "bid_size": pl.Int64,
    "ask_size": pl.Int64,
    "quote_ts": TIME,
    "last": pl.Float64,
    "last_ts": TIME,
    "volume": pl.Int64,
    "open_interest": pl.Int64,
    "oi_as_of": pl.Date,
    "underlying_price": pl.Float64,
    **{f"provided_{g}": pl.Float64 for g in _GREEKS},
    "provided_model": pl.String,
    **{f"computed_{g}": pl.Float64 for g in _GREEKS},
    "computed_model": pl.String,
}


def _greek_cells(prefix: str, block: Greeks | None) -> dict[str, Any]:
    cells: dict[str, Any] = {f"{prefix}_{g}": getattr(block, g, None) for g in _GREEKS}
    cells[f"{prefix}_model"] = block.model if block is not None else None
    return cells


def _cells(snapshot: ChainSnapshot, r: ChainRow) -> dict[str, Any]:
    c, q, t = r.contract, r.quote, r.trade
    return {
        "snapshot_ts": snapshot.snapshot_ts,
        "known_at": snapshot.known_at,
        "provider": snapshot.provider,
        "underlying_id": c.underlying_id,
        "root": c.root,
        "expiry": c.expiry,
        "right": c.right,
        "strike": format(c.strike.normalize(), "f"),
        "style": c.style,
        "multiplier": c.multiplier,
        "listed_on": c.listed_on,
        "provider_symbol": c.provider_symbol,
        "bid": q.bid if q else None,
        "ask": q.ask if q else None,
        "bid_size": q.bid_size if q else None,
        "ask_size": q.ask_size if q else None,
        "quote_ts": q.quote_ts if q else None,
        "last": t.last if t else None,
        "last_ts": t.last_ts if t else None,
        "volume": t.volume if t else None,
        "open_interest": r.open_interest,
        "oi_as_of": r.oi_as_of,
        "underlying_price": snapshot.underlying_price,
        **_greek_cells("provided", r.provided),
        **_greek_cells("computed", r.computed),
    }


def to_frame(snapshot: ChainSnapshot) -> pl.DataFrame:
    """Rows are sorted by contract key so the same content always gives the same frame."""
    rows = sorted(snapshot.rows, key=lambda r: r.contract.key)
    return pl.DataFrame([_cells(snapshot, r) for r in rows], schema=SCHEMA, orient="row")


def _block(prefix: str, source: str, row: dict[str, Any]) -> Greeks | None:
    model = row[f"{prefix}_model"]
    if model is None:
        return None
    return Greeks(source=source, model=model, **{g: row[f"{prefix}_{g}"] for g in _GREEKS})


def _row(raw: dict[str, Any]) -> ChainRow:
    contract = ContractId(
        underlying_id=raw["underlying_id"],
        root=raw["root"],
        expiry=raw["expiry"],
        strike=Decimal(raw["strike"]),
        right=raw["right"],
        style=raw["style"],
        multiplier=raw["multiplier"],
        listed_on=raw["listed_on"],
        provider_symbol=raw["provider_symbol"],
    )
    quote = None
    if raw["bid"] is not None and raw["ask"] is not None:
        quote = Quote(
            bid=raw["bid"],
            ask=raw["ask"],
            bid_size=raw["bid_size"],
            ask_size=raw["ask_size"],
            quote_ts=raw["quote_ts"],
        )
    trade = None
    if raw["last"] is not None:
        trade = Trade(last=raw["last"], last_ts=raw["last_ts"], volume=raw["volume"])
    return ChainRow(
        contract=contract,
        quote=quote,
        trade=trade,
        open_interest=raw["open_interest"],
        oi_as_of=raw["oi_as_of"],
        provided=_block("provided", "provided", raw),
        computed=_block("computed", "computed", raw),
    )


def from_frame(frame: pl.DataFrame) -> ChainSnapshot:
    """Rebuild one snapshot; every record re-validates, so a damaged file fails loud."""
    if dict(frame.schema) != SCHEMA:
        raise DataError("options parquet has an unexpected schema")
    if frame.height == 0:
        raise DataError("options parquet holds no rows")
    for name in ("snapshot_ts", "known_at", "provider", "underlying_id", "underlying_price"):
        if frame[name].n_unique() != 1 or frame[name].null_count():
            raise DataError(f"options parquet has an inconsistent {name} column")
    head: dict[str, Any] = frame.row(0, named=True)
    snapshot_ts: datetime = head["snapshot_ts"]
    return ChainSnapshot(
        provider=head["provider"],
        underlying_id=head["underlying_id"],
        snapshot_ts=snapshot_ts,
        known_at=head["known_at"],
        underlying_price=head["underlying_price"],
        rows=tuple(_row(raw) for raw in frame.iter_rows(named=True)),
    )


def filter_rows(snapshot: ChainSnapshot, when_day: date) -> ChainSnapshot:
    """Drop contracts not yet listed or already expired on `when_day`."""
    kept = tuple(
        r
        for r in snapshot.rows
        if (r.contract.listed_on is None or r.contract.listed_on <= when_day)
        and r.contract.expiry >= when_day
    )
    return ChainSnapshot(
        provider=snapshot.provider,
        underlying_id=snapshot.underlying_id,
        snapshot_ts=snapshot.snapshot_ts,
        known_at=snapshot.known_at,
        underlying_price=snapshot.underlying_price,
        rows=kept,
    )
