"""A seeded synthetic setup with enough occurrences to be read, for the Setup Lab word tests.

Self-contained (it imports only product packages) so one script can run it on two checkouts.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli import setup_cmds
from alpha_data.store import ParquetStore

BARS = 900
FIRST_EVENT = 40
EVERY = 25
HORIZON = 5


def seed_events(home: Path, *, lift: float, seed: int = 11, symbol: str = "SPY") -> None:
    """900 noisy daily bars, an event every 25 bars; `lift` is added to its 5-bar window.

    Entries are the next open; open equals the previous close, so a lift on bars event+2 to
    event+6 is a lift on the primary horizon's return and on nothing else.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0004, 0.01, BARS)
    events = list(range(FIRST_EVENT, BARS - 10, EVERY))
    for event in events:
        returns[event + 2 : event + 2 + HORIZON] += lift
    closes = 100.0 * np.cumprod(1.0 + returns)
    opens = np.concatenate([[100.0], closes[:-1]])
    start = date(2020, 1, 1)
    rows = [
        {
            "ts": datetime.fromordinal(start.toordinal() + i).replace(tzinfo=UTC),
            "open": float(opens[i]),
            "high": float(max(opens[i], closes[i]) * 1.001),
            "low": float(min(opens[i], closes[i]) * 0.999),
            "close": float(closes[i]),
            "volume": 1.0 if i in events else 1000.0,
        }
        for i in range(BARS)
    ]
    store = ParquetStore(home / "store")
    store.write_bars(symbol, pl.DataFrame(rows))
    store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")


def spec_text(idea: str, *, exit_table: bool = True, horizon: int = HORIZON) -> str:
    text = (
        f'[setup]\nname="Synthetic"\nidea="{idea}"\ntimeframe="1D"\nassets=["SPY"]\n'
        'event="volume == 1"\n[reference]\nbase="low"\n'
        f"[study]\nhorizons=[{horizon}]\nprimary={horizon}\n"
    )
    if exit_table:
        text += '[exit]\ntime_bars=5\nstop="5 %"\ntarget="10 %"\n'
    return text


def make_find(home: Path, *, idea: str = "Volume spike", horizon: int = HORIZON) -> dict[str, Any]:
    path = home / f"spec-{hashlib.sha256(idea.encode()).hexdigest()[:6]}-{horizon}.toml"
    path.write_text(spec_text(idea, horizon=horizon))
    return setup_cmds.run_find(path, home=home)
