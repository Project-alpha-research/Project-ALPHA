"""Replay a followed rule over stored bars with the rule test's own engine step. Paper only.

The warm-up bars before the first forward bar only prime the indicators (`prime_history`):
no order, fill or position can come from them. The engine then runs from a flat start over the
forward bars. A decision for session t uses bars up to the close of t, and a fill is the open of
t+1. This is the same `_runner.run_full_backtest` call the rule test makes. It is never
`run_idea`, so no run folder and no ledger row exist. Dividends are not read: the paper book is
price only. Nothing here reads a clock or the `forward/` folder.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import alpha_backtest
import alpha_strategies
from alpha_cli import _runner
from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import annualisation
from alpha_core import Bar, DataError
from alpha_data.timeframe import DAILY


@dataclass(frozen=True)
class Decision:
    """What the rule decided on the close of one session, and the numbers it used."""

    long: bool
    signal: int | None
    reason: str
    readings: dict[str, float]


@dataclass(frozen=True)
class Fill:
    ts: datetime
    side: str
    price: float


@dataclass(frozen=True)
class Replay:
    sessions: dict[date, Decision]
    fills: dict[date, Fill]
    long_before: bool


def engine_code_sha256() -> str:
    """One hash of the source of the engine, the strategies and the run glue. A change to any of
    them shows later as a replay that disagrees, not as a silent new number."""
    here = Path(__file__).parent
    roots = [
        Path(alpha_backtest.__file__ or "").parent,
        Path(alpha_strategies.__file__ or "").parent,
    ]
    files = [here / "_runner.py", here / "_strategies.py"]
    files += [p for root in roots for p in root.glob("*.py")]
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: (p.parent.name, p.name)):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _spec(idea: IdeaSpec, bars: Sequence[Bar]) -> _runner.RunSpec:
    ppy, _ = annualisation([bar.ts for bar in bars], bar_size=DAILY)
    return assemble_run_spec(idea, bars[0].symbol, ppy, len(bars))


def _day_of(ts: datetime) -> date:
    return ts.date()


def replay(bars: Sequence[Bar], idea: IdeaSpec, first: int) -> Replay:
    """Decisions and fills for the bars from index `first` on, after priming on those before."""
    if not 2 <= first < len(bars):
        raise DataError("the replay needs bars before the first forward bar and the bar itself")
    spec = _spec(idea, bars)
    before = _runner.run_full_backtest(bars[first - 1 : first], spec, warmup_bars=bars[: first - 1])
    result = _runner.run_full_backtest(bars[first:], spec, warmup_bars=bars[:first])
    readings: dict[date, dict[str, float]] = {}
    for row in result.indicator_trace:
        readings.setdefault(_day_of(row.ts), {})[row.name] = row.value
    sessions = {
        _day_of(d.ts): Decision(
            d.target_quantity > 0, d.signal, d.reason, readings.get(_day_of(d.ts), {})
        )
        for d in result.decision_trace
    }
    fills = {_day_of(f.ts): Fill(f.ts, f.side.lower(), f.price) for f in result.fill_trace}
    return Replay(sessions, fills, any(d.target_quantity > 0 for d in before.decision_trace))
