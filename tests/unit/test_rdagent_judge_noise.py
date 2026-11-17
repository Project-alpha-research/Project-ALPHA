"""Seeded 40-name, 600-day noise panels; old-rule control and the real primary replay."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli import _rdagent_judge as judge
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli._rdagent_clocks import overall_status, trial_family
from alpha_cli._rdagent_stats import SCREEN_RULE


def test_noise_candidate_rate_and_slow_daily_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "BOOTSTRAP_RESAMPLES", 20)  # intervals are diagnostics, never gates
    rng = np.random.default_rng(20261117)
    n, names, factors = 600, 40, 300
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(n)]
    open_days = [days[0] + timedelta(days=i) for i in range(n + 2)]
    opens = 100 * np.cumprod(1 + rng.normal(0, 0.02, (n + 2, names)), axis=0)
    symbols = [f"C{i:02}" for i in range(names)]
    panel = pl.DataFrame(
        {
            "date": [day for day in open_days for _ in symbols],
            "instrument": symbols * (n + 2),
            "open": opens.ravel(),
            "close": opens.ravel(),
            "high": opens.ravel() * 1.01,
            "low": opens.ravel() * 0.99,
            "volume": np.ones(opens.size),
        }
    ).with_columns(pl.col("date").cast(pl.Date))
    history: list[dict[str, Any]] = []
    old_passes = daily_passes = slow_passes = candidates = 0
    for index in range(factors):
        signal = rng.normal(size=(n, names))
        if index % 2:
            cumulative = np.vstack([np.zeros(names), np.cumsum(signal, axis=0)])
            signal = cumulative[1:] - cumulative[np.maximum(0, np.arange(n) - 59)]
        digest = f"{index:064x}"
        series: dict[str, dict[str, Any]] = {digest: {c: {} for c in ev.CLOCKS}}
        trials: dict[str, Any] = {}
        for clock in ev.CLOCKS:
            stats = judge.screen_at_clock(
                signal,
                opens,
                days,
                digest,
                clock,
                open_days=open_days,
                declared_direction=1,
                n_resamples=20,
            )
            # With the declared positive sign, p cannot be smaller than today's one-sided p.
            historical_one_sided = 0.5 * math.erfc(stats["old_z"] / math.sqrt(2))
            assert stats["p"] + 1e-15 >= historical_one_sided
            assert stats["two_sided_p"] + 1e-15 >= stats["plain_p"]
            if clock == "daily":
                old_passes += stats["plain_p"] <= 0.1
                daily_passes += stats["p"] <= 0.05
                slow_passes += bool(index % 2 and stats["p"] <= 0.05)
            trials[clock] = {
                "status": "OK" if clock == "weekly" else "DIAGNOSTIC",
                "p": stats["p"],
                "q": 1.0,
                "screen": stats,
                "replay": {},
            }
            if clock == "weekly":
                trials[clock]["spread"] = judge.spread_at_clock(
                    signal,
                    opens,
                    days,
                    digest,
                    clock,
                    open_days=open_days,
                    direction=1,
                    symbols=symbols,
                    n_resamples=20,
                )
        row: dict[str, Any] = {
            "schema": ev.TRIAL_SCHEMA,
            "name": digest,
            "code_sha256": digest,
            "status": "OK",
            "primary_clock": "weekly",
            "lead_clock": "weekly",
            "clocks": trials,
            "screen_rule": SCREEN_RULE,
        }
        family = trial_family([*history, row])
        returns, _ = ev._replay_clocks(
            [row], panel, {digest: signal}, days, series, family, index + 1
        )
        ev._deflate([row], history, family, returns)
        status, _ = overall_status(trials, primary_clock="weekly")
        row["status"] = status
        candidates += status == "CANDIDATE"
        history.append(row)
    assert candidates / factors <= 0.01
    nominal, slow_n = 0.05, factors // 2
    assert slow_passes / slow_n <= nominal + 2 * math.sqrt(nominal * (1 - nominal) / slow_n)
    assert old_passes > 0 and old_passes >= 2 * daily_passes
    print(
        f"noise: candidates={candidates}/{factors}"
        f"; slow daily={slow_passes}/{slow_n}; new daily={daily_passes}/{factors}"
        f"; old two-sided={old_passes}/{factors}"
    )
