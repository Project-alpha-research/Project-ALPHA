"""Stored-run builders shared by the risk and attribution check tests."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_run_level_checks import START, stored_run

TESTS = "tests/unit/test_toolbox_risk_sizing"


def put_equity(home: Path, equity: np.ndarray) -> None:
    dates = [START + timedelta(days=i) for i in range(len(equity))]
    frame = pl.DataFrame({"ts": dates, "equity": equity})
    frame.write_parquet(home / "runs" / RUN / "equity_curve.parquet")


def put_returns(home: Path, returns: np.ndarray) -> None:
    put_equity(home, np.r_[1.0, np.cumprod(1.0 + np.asarray(returns, dtype=float))])


def put_trades(
    home: Path,
    pnl: list[float],
    ret: list[float] | None = None,
    entry_days: list[int] | None = None,
    hold_days: list[int] | None = None,
) -> None:
    n = len(pnl)
    entry = entry_days if entry_days is not None else list(range(0, 2 * n, 2))
    hold = hold_days if hold_days is not None else [1] * n
    frame = pl.DataFrame(
        {
            "side": ["BUY"] * n,
            "realized_pnl": pnl,
            "realized_return": ret if ret is not None else [p / 100 for p in pnl],
            "entry_ts": [START + timedelta(days=d) for d in entry],
            "exit_ts": [START + timedelta(days=d + h) for d, h in zip(entry, hold, strict=True)],
        },
        schema_overrides={"side": pl.String, "realized_pnl": pl.Float64},
    )
    frame.write_parquet(home / "runs" / RUN / "trades.parquet")


def stored(home: Path) -> Path:
    return stored_run(home, "risk_sizing")


def read(home: Path, tool: str, *params: str) -> dict[str, Any]:
    return run(home, tool, RUN, list(params))
