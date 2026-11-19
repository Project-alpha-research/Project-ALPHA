"""A synthetic store that grows one daily bar at a time, for the forward-update tests.

Prices are explicit: a history that drifts up or down by a fixed step, then the forward moves
named by the test. Each bar opens at the previous close. Nothing here reads the wall clock.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from alpha_cli import follow_source
from alpha_cli import follow_store as store
from alpha_cli.spine.spec import IdeaSpec
from alpha_data.sessions import session_bounds, sessions_between
from alpha_data.store import ParquetStore

RUN = "a" * 16
START = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
FIRST = date(2026, 11, 19)
IDEA = IdeaSpec.model_validate(
    {"assets": ["SPY"], "rule": {"kind": "ma_cross", "fast": 3, "slow": 5}}
)
DAYS = sessions_between("XNYS", date(2026, 6, 1), date(2026, 12, 31))
F0 = DAYS.index(FIRST)
# Down history, then up 4, 4, 4 and a fall: long from the first forward session, out on the fifth.
BUY_AND_SELL = [3.0, 3.0, 3.0, -8.0, -8.0, -8.0, -2.0, -2.0]
# Up history (the rule is already long at the start), then a dip and a new rise.
LONG_AT_START = [2.0, 2.0, -6.0, -6.0, -6.0, 9.0, 9.0, 9.0, 9.0, -9.0, -9.0]


def closes_for(slope: float, forward: list[float]) -> list[float]:
    out: list[float] = []
    value = 100.0
    for i in range(len(DAYS)):
        value += (
            slope * (1.0 + 0.3 * (i % 3))
            if i < F0
            else (forward[i - F0] if i - F0 < len(forward) else 0.0)
        )
        out.append(value)
    return out


class World:
    """One followed rule test over a store that holds history plus `n` forward bars."""

    def __init__(self, home: Path, slope: float, forward: list[float]) -> None:
        self.home = home
        self.closes = closes_for(slope, forward)
        self.rows = [self._row(i) for i in range(len(DAYS))]
        self.stored = 0
        ParquetStore(home / "store").write_provenance(
            "SPY", source="alpaca", adapter_version="1", parser_version="1"
        )
        folder = home / "runs" / RUN
        folder.mkdir(parents=True)
        spine = {"spec_sha256": IDEA.spec_sha256, "store": "home", "idea_card": ""}
        manifest = {"run_id": RUN, "metadata": {"symbol": "SPY"}, "spine": spine}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        spec = {**IDEA.model_dump(mode="json"), "spec_sha256": IDEA.spec_sha256}
        (folder / "spec.json").write_text(json.dumps(spec, sort_keys=True))
        self.write(0)

    def _row(self, i: int) -> dict[str, object]:
        close = self.closes[i]
        opened = self.closes[i - 1] if i else close
        day = DAYS[i]
        return {
            "ts": datetime(day.year, day.month, day.day, tzinfo=UTC),
            "open": opened,
            "high": max(opened, close),
            "low": min(opened, close),
            "close": close,
            "volume": 1000.0,
        }

    def write(self, forward: int) -> None:
        """Store the history and the first `forward` forward bars (a wholesale write)."""
        self.stored = forward
        frame = pl.DataFrame(self.rows[: F0 + forward])
        ParquetStore(self.home / "store").write_bars("SPY", frame)

    def grow(self) -> None:
        self.write(self.stored + 1)

    def start(self, pct: float = 10.0) -> str:
        source = follow_source.rule_test_source(self.home, RUN)
        facts = store.start_follow(self.home, source, card="", size_pct=pct, clock=lambda: START)
        return str(facts["follow_id"])

    def close_of(self, k: int) -> datetime:
        """Half an hour after the close of forward session `k`."""
        return session_bounds("XNYS", DAYS[F0 + k])[1] + timedelta(minutes=30)

    def open_after(self, k: int) -> datetime:
        return session_bounds("XNYS", DAYS[F0 + k + 1])[0]

    def open_of(self, k: int) -> float:
        return float(self.closes[F0 + k - 1])

    def edit_close(self, index: int, value: float) -> None:
        """Change one stored close (a data revision). `index` is a forward session."""
        self.closes[F0 + index] = value
        for i in (F0 + index, F0 + index + 1):
            self.rows[i] = self._row(i)
        self.write(self.stored)
