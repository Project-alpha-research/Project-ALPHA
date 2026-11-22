"""A re-run input built in memory: synthetic daily bars, a classic rule and its engine run.

``load_rerun`` reads a stored run; this builds the same ``RunSeries`` directly (no gauntlet), so
the toolbox's re-run checks can be tested in seconds. The check tests also test ``load_rerun``
itself on a stored ``alpha test`` run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from alpha_cli.spine.diagnose import full_sample
from alpha_cli.spine.diagnostics import buy_and_hold
from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import periods_per_year
from alpha_cli.toolbox.inputs import RunSeries
from alpha_core import Bar

RUN = "0123456789abcdef"
START = datetime(2020, 1, 1, tzinfo=UTC)


def synthetic_bars(n: int = 900, seed: int = 0, symbol: str = "SPY") -> list[Bar]:
    """A noisy uptrend with real dispersion, one bar per calendar day from 2020-01-01."""
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1.0 + 0.0008 + rng.normal(0.0, 0.012, n))
    return [
        Bar(
            symbol=symbol,
            ts=START + timedelta(days=i),
            open=float(close),
            high=float(close),
            low=float(close),
            close=float(close),
            volume=1000.0,
        )
        for i, close in enumerate(closes)
    ]


def synthetic_series(
    home: Path, rule: dict[str, Any] | None = None, *, n: int = 900, seed: int = 0
) -> RunSeries:
    """The re-run input of a rule test on synthetic bars, with its run folder written."""
    idea = IdeaSpec.model_validate(
        {"assets": ["SPY"], "rule": rule or {"kind": "ma_cross", "fast": 5, "slow": 20}}
    )
    bars = synthetic_bars(n, seed)
    ppy = periods_per_year([bar.ts for bar in bars])
    spec = assemble_run_spec(idea, "SPY", ppy, len(bars))
    full, dates, equity = full_sample(bars, [], spec)
    manifest = {
        "command": "validate",
        "idea_id": f"synthetic-{seed}-{n}",
        "source_fingerprint": f"synthetic-{seed}-{n}",
        "metadata": {"symbol": "SPY", "last_ts": dates[-1].isoformat()},
        "spine": {"test_id": "t1", "name": "demo", "store": "home", "labels": []},
    }
    rdir = home / "runs" / RUN
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "manifest.json").write_text(json.dumps(manifest))
    (rdir / "spec.json").write_text(json.dumps(idea.model_dump(mode="json")))
    states = {row.ts: row.net_exposure != 0 for row in full.portfolio_state_trace}
    return RunSeries(
        home=home,
        run_id=RUN,
        manifest=manifest,
        asset="SPY@home",
        ppy=ppy,
        dates=dates,
        equity=tuple(float(value) for value in equity),
        opens={bar.ts: float(bar.open) for bar in bars},
        benchmark_equity=dict(zip(dates, buy_and_hold(bars, []), strict=True)),
        positions=tuple(states[ts] for ts in dates),
        bars=tuple(bars),
        dividends=(),
        idea=idea,
        spec=spec,
        full=full,
    )
