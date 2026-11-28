"""The replay half of the judge lives in _rdagent_judge_replay, unchanged in behaviour."""

from __future__ import annotations

import importlib
import math
from datetime import date, timedelta
from types import ModuleType

import numpy as np
import polars as pl

from alpha_cli import _factor_eval_screen as screen
from alpha_cli import _rdagent_judge as judge
from alpha_cli import rdagent_factor_eval as ev

MOVED = ("_return_metrics", "replay", "_gap_replay", "panel_membership")


def _new_module() -> ModuleType:
    return importlib.import_module("alpha_cli._rdagent_judge_replay")


def panel(n: int = 80) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "date": date(2020, 12, 1) + timedelta(days=i),
                "instrument": f"C{j}",
                "open": 100.0 + i + j,
                "close": 100.0 + i + j,
                "high": 200.0 + i,
                "low": 1.0,
                "volume": 100.0,
                "quote_volume": 10000.0,
            }
            for i in range(n)
            for j in range(6)
        ]
    )


def test_replay_names_live_in_new_module() -> None:
    module = _new_module()
    for name in MOVED:
        obj = getattr(module, name)
        assert callable(obj)
        assert obj.__module__ == "alpha_cli._rdagent_judge_replay", name


def test_judge_no_longer_holds_moved_names() -> None:
    # Pure move with no facade: the old module neither defines nor re-exports them.
    for name in MOVED:
        assert not hasattr(judge, name), name


def test_factor_eval_reexports_from_new_module() -> None:
    module = _new_module()
    assert vars(screen)["panel_membership"] is module.panel_membership
    assert ev.replay is module.replay


def test_return_metrics_unchanged_from_new_module() -> None:
    module = _new_module()
    values = np.array([0.01, -0.005, 0.02, 0.0, -0.01, 0.015])
    metrics = module._return_metrics(values)
    sd = float(values.std(ddof=1))
    curve = np.concatenate(([1.0], np.cumprod(1 + values)))
    assert math.isclose(metrics["annualized_return"], float(values.mean()) * ev.ANNUAL_DAYS)
    assert math.isclose(metrics["compounded_return"], float(curve[-1] - 1))
    assert math.isclose(metrics["per_observation_sharpe"], float(values.mean()) / sd)
    assert math.isclose(metrics["sharpe"], float(values.mean()) / sd * math.sqrt(ev.ANNUAL_DAYS))
    assert math.isclose(
        metrics["max_drawdown"], float(np.min(curve / np.maximum.accumulate(curve) - 1))
    )


def test_panel_membership_behaviour_through_factor_eval_screen() -> None:
    bars = panel()
    symbols = sorted(bars["instrument"].unique().to_list())
    days = [date(2020, 12, 1) + timedelta(days=i) for i in range(40, 80)]
    mask = vars(screen)["panel_membership"](bars, days, symbols)
    assert mask.shape == (len(days), len(symbols))
    assert mask.dtype == bool
    assert mask.all()


def test_judge_keeps_shared_names() -> None:
    for name in (
        "sha",
        "matrix",
        "SPREAD_REASON",
        "EXPLORATION",
        "freeze",
        "lineage",
        "screen",
        "screen_at_clock",
        "tie_diagnostics",
        "CONFIG",
    ):
        assert hasattr(judge, name), name
