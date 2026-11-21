"""Stores for the reserved-period read tests: one with bars after the boundary, one cut at it."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import _runner
from alpha_core import Bar
from alpha_core.corporate import ActionType, CorporateAction
from alpha_core.reserve import RESERVED_DAY
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

# 2020-01-01 plus 1,600 daily bars ends 2024-05-19; the first 1,461 bars are dated before 2024.
LONG, SHORT = 1600, 1461
HELD = LONG - SHORT


class Spy:
    """The latest bar and every action date that each loader call returned."""

    def __init__(self) -> None:
        self.latest: list[datetime] = []
        self.actions: list[date] = []

    def assert_nothing_from_the_reserved_day(self) -> None:
        assert self.latest, "the command never read a bar"
        assert all(ts.date() < RESERVED_DAY for ts in self.latest), self.latest
        assert all(day < RESERVED_DAY for day in self.actions), self.actions


def watch_loaders(monkeypatch: pytest.MonkeyPatch) -> Spy:
    """Wrap `_runner.load_bars` and `load_dividends`; every caller reaches them by that name."""
    seen = Spy()
    load_bars, load_dividends = _runner.load_bars, _runner.load_dividends

    def bars(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.latest.append(max(bar.ts for bar in result[0]))
        return result

    def dividends(*args: Any, **kwargs: Any) -> list[Any]:
        result: list[Any] = load_dividends(*args, **kwargs)
        seen.actions.extend(action.ex_date for action in result)
        return result

    monkeypatch.setattr(_runner, "load_bars", bars)
    monkeypatch.setattr(_runner, "load_dividends", dividends)
    return seen


def write_store(home: Path, n: int, *, poisoned: bool, symbols: Sequence[str] = ("SPY",)) -> None:
    """`n` bars per symbol. A poisoned store has prices x1000 from the reserved day on, and a
    split and a dividend dated after it: a command that read them would give other numbers."""
    for index, symbol in enumerate(symbols):
        seed_store(home, symbol=symbol, n=n, seed=index)
        store = ParquetStore(home / "store")
        store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")
        if not poisoned:
            continue
        late = pl.col("ts").dt.date() >= RESERVED_DAY
        store.write_bars(
            symbol,
            store.read_bars(symbol).with_columns(
                [
                    pl.when(late).then(pl.col(c) * 1000.0).otherwise(pl.col(c)).alias(c)
                    for c in ("open", "high", "low", "close")
                ]
            ),
        )
        store.write_actions(
            symbol,
            [
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.SPLIT,
                    ex_date=date(2024, 2, 15),
                    ratio=4.0,
                ),
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.DIVIDEND,
                    ex_date=date(2024, 3, 1),
                    pay_date=date(2024, 3, 5),
                    amount=1.0,
                ),
            ],
        )
