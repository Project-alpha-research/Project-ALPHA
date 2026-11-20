"""Hand-built follows for the "what is active today" tests.

Every entry goes through the journal writer with an injected clock: no file is edited by hand.
Stocks use the XNYS calendar, crypto the daily no-calendar market. Nothing reads the wall clock.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli import follow_store as store
from alpha_cli.follow_book import new_book
from alpha_cli.follow_chain import append_entry
from alpha_cli.follow_journal import CALENDAR_KEY, Kind, session_close
from alpha_cli.follow_source import Source
from alpha_cli.spine import idea_card
from alpha_data.store import ParquetStore

NOW = datetime(2026, 11, 20, 1, 0, tzinfo=UTC)  # after the close of 2026-11-19, before the open
START = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
LAST = date(2026, 11, 19)
STOCKS = ("AAA", "BBB", "CCC", "DDD")
CRYPTO = "BTC/USD"
READINGS = {"fast_sma": 101.2, "slow_sma": 99.8}


def seed(home: Path) -> None:
    """Four stock symbols and one crypto symbol, daily bars to 2026-11-19."""
    days = [date(2026, 11, 1) + timedelta(n) for n in range(19)]
    rows = [
        {
            "ts": datetime(d.year, d.month, d.day, tzinfo=UTC),
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 1000.0,
        }
        for i, d in enumerate(days)
    ]
    bars = ParquetStore(home / "store")
    for symbol in (*STOCKS, CRYPTO):
        bars.write_bars(symbol, pl.DataFrame(rows))
        source = "ccxt:coinbase" if symbol == CRYPTO else "alpaca"
        bars.write_provenance(symbol, source=source, adapter_version="1", parser_version="1")


def start(home: Path, asset: str, *, run_id: str, card: str = "", at: datetime = START) -> str:
    source = Source("rule_test", run_id, hashlib.sha256(run_id.encode()).hexdigest(), "", [asset])
    facts = store.start_follow(home, source, card=card, size_pct=10.0, clock=lambda: at)
    return str(facts["follow_id"])


def card(home: Path, claim: str) -> str:
    return idea_card.save(home, idea_card.IdeaCard(claim=claim))[0]


def _written(home: Path, follow: str, session: date, minutes: int = 30) -> datetime:
    entries = store.entries_of(home, follow)
    calendar = str(entries[0].payload[CALENDAR_KEY])
    return session_close(calendar, session) + timedelta(minutes=minutes)


def add(
    home: Path,
    follow: str,
    session: date,
    *,
    kind: Kind = "bar",
    action: str = "none",
    words: str = "no signal",
    units: float = 0.0,
    equity_pct: float = 0.0,
) -> None:
    """Append one session entry the way `follow update` does, through the journal writer."""
    book = {
        **new_book(),
        "units": units,
        "entry_price": 100.0 if units else None,
        "equity": 10_000.0 * (1 + equity_pct / 100),
        "equity_pct": equity_pct,
    }
    payload: dict[str, Any] = {"session": session.isoformat(), "paper": True, "book": book}
    payload["fills"] = []
    if kind == "bar":
        payload["decision"] = {"action": action, "words": words, "long": units > 0}
        payload["readings"] = READINGS
        payload["replay"] = {"agrees": True, "checked": 3, "differences": []}
    elif kind == "late":
        payload["reason"] = "the bar of this session was not stored at run time"
    else:
        payload.update(would_have=words, reason="written after the next open: no paper order")
    written = _written(home, follow, session, 30 if kind != "missed" else 24 * 60)
    append_entry(
        store.folder_of(home, follow),
        kind=kind,
        session_date=session,
        clock=lambda: written,
        payload=payload,
        follow_id=follow,
    )
