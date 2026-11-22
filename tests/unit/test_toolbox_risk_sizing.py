"""All risk and attribution checks: registration, too little data, repeats and future inputs."""

from datetime import timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
import pytest

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.families.risk_sizing import CHECKS
from alpha_cli.toolbox.registry import SPECS, get
from tests.unit.risk_sizing_support import put_returns, put_trades, read, stored
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_run_level_checks import END

IDS = tuple(spec.id for spec in CHECKS)
TRADE_ONLY = {
    "risk.kelly",
    "risk.fractional_kelly",
    "risk.optimal_f",
    "risk.loss_streaks",
    "attribution.hold_period",
    "attribution.weekday",
}
EQUITY_TOOLS = set(IDS) - TRADE_ONLY
# Keys that stay available on the tiny fixtures below; every other output must say why not.
STILL_READ = {"risk.worst_windows": {"worst_1", "end_1"}}


def test_the_checks_are_registered_once() -> None:
    assert 10 <= len(CHECKS) <= 14
    assert len(set(IDS)) == len(IDS)
    registered = {spec.id for spec in SPECS}
    assert set(IDS) <= registered
    assert all(get(tool_id).question.endswith("?") for tool_id in IDS)


@pytest.mark.parametrize("tool", IDS)
def test_too_little_data_gives_a_reason_with_the_count(tmp_path: Path, tool: str) -> None:
    stored(tmp_path)
    put_returns(tmp_path, np.array([0.01, -0.02, 0.015]))
    put_trades(tmp_path, [1.0, -2.0, 3.0])
    doc = read(tmp_path, tool)
    keep = STILL_READ.get(tool, set())
    values = {k: v for k, v in doc["values"].items() if k not in keep}
    assert values
    assert all(v is None for v in values.values()), values
    assert doc["reasons"], "every unavailable output carries a reason"
    assert all(doc["reasons"][k] for k in values)
    text = " ".join(doc["reasons"].values())
    assert any(ch.isdigit() for ch in text), text


def sample_returns() -> npt.NDArray[np.float64]:
    steps = np.linspace(-0.02, 0.025, 400)
    return np.asarray(np.sin(np.arange(400) * 0.9) * 0.01 + steps * 0.1, dtype=np.float64)


def sample_trades() -> tuple[list[float], list[float]]:
    ret = [0.06, -0.03, 0.02, -0.01, 0.04, -0.02, 0.05, -0.04, 0.01, 0.03] * 3
    return [r * 1000 for r in ret], ret


@pytest.mark.parametrize("tool", IDS)
def test_repeat_is_identical(tmp_path: Path, tool: str) -> None:
    results = []
    for home in (tmp_path / "one", tmp_path / "two"):
        stored(home)
        put_returns(home, sample_returns())
        pnl, ret = sample_trades()
        put_trades(home, pnl, ret, hold_days=[1 + i % 9 for i in range(30)])
        results.append(read(home, tool)["result"])
    assert results[0] == results[1]
    assert str(results[0]) == str(results[1])


@pytest.mark.parametrize("tool", IDS)
def test_future_input_rejected(tmp_path: Path, tool: str) -> None:
    stored(tmp_path)
    put_returns(tmp_path, sample_returns())
    pnl, ret = sample_trades()
    put_trades(tmp_path, pnl, ret)
    folder = tmp_path / "runs" / RUN
    later = END + timedelta(days=1)
    if tool in EQUITY_TOOLS:
        path, field = folder / "equity_curve.parquet", "ts"
    else:
        path, field = folder / "trades.parquet", "exit_ts"
    frame = pl.read_parquet(path)
    frame.vstack(frame.tail(1).with_columns(pl.lit(later).alias(field))).write_parquet(path)
    with pytest.raises(SpineError, match="run period"):
        read(tmp_path, tool)
