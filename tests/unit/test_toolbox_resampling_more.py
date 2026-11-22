"""Twelve extra resampling checks: hand answers, re-computation, short and repeat runs."""

import itertools
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.inputs import Inputs, resolve
from alpha_cli.toolbox.registry import get
from alpha_cli.toolbox.runner import run
from alpha_validation import FloatArray, risk_of_ruin
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_run_level_checks import END, START, stored_run, write_trades

MOVING = "resampling.moving_block_paths"
WILD = "resampling.wild_bootstrap"
RUIN = "resampling.risk_of_ruin"
SHUFFLE = "resampling.return_shuffle"
PHASE = "resampling.phase_surrogates"
YEARS = "resampling.calendar_year_shuffle"
HALVES = "resampling.interleaved_halves"
ORDER = "resampling.trade_order_drawdown"
JACK = "resampling.trade_jackknife"
YEAR_JACK = "resampling.year_jackknife"
STRESS = "resampling.stress_shocks"
TOOLS = (
    MOVING,
    WILD,
    RUIN,
    SHUFFLE,
    PHASE,
    YEARS,
    HALVES,
    ORDER,
    JACK,
    YEAR_JACK,
    STRESS,
)
TRADE_TOOLS = (ORDER, JACK)
APPROX: Any = {"rel": 1e-9, "abs": 1e-12}
SEED = 5
SMALL = {"n_paths": 40, "n_resamples": 40, "n_shuffles": 40, "n_splits": 40}


def put(
    home: Path,
    returns: list[float] | FloatArray,
    *,
    dates: list[datetime] | None = None,
    pnls: list[float] | None = None,
) -> None:
    folder = stored_run(home, "resampling_more")
    equity = np.r_[1.0, np.cumprod(1.0 + np.asarray(returns))]
    when = dates or [START + timedelta(days=i) for i in range(len(equity))]
    pl.DataFrame({"ts": when, "equity": equity}).write_parquet(folder / "equity_curve.parquet")
    if pnls is not None:
        write_trades(folder, pnls, ["BUY"] * len(pnls))


def read(home: Path, tool: str, seed: int = SEED, **params: Any) -> dict[str, Any]:
    spec = get(tool)
    settings = {p.name: p.default for p in spec.params} | params
    assert spec.compute is not None
    rng = np.random.default_rng(seed) if spec.seeded else None
    result = spec.compute(Inputs(resolve(home, RUN), seed=seed), settings, rng)
    return result.values


def drop(returns: FloatArray) -> float:
    equity = np.r_[1.0, np.cumprod(1.0 + returns)]
    return float(np.max(1.0 - equity / np.maximum.accumulate(equity)))


def wavy(n: int = 60) -> FloatArray:
    return np.array([0.012 * math.sin(i) + 0.002 * (i % 3) - 0.001 for i in range(n)])


def test_known_answer_blocks(tmp_path: Path) -> None:
    tool = MOVING
    # Constant gains: every redrawn history is identical, so the answer is (1.01)^12 - 1.
    put(tmp_path, [0.01] * 12)
    values = read(tmp_path, tool, n_paths=30, block_length=4)
    expected = 1.01**12 - 1
    assert values == pytest.approx(
        {"low": expected, "median": expected, "high": expected, "drop_q95": 0.0}, **APPROX
    )
    # Independent re-draw of the same blocks, one block and one path at a time.
    returns = wavy(30)
    put(tmp_path, returns)
    rng, n, b = np.random.default_rng(SEED), 30, 4
    starts = rng.integers(0, n - b + 1, size=(50, math.ceil(n / b)))
    finals, drops = [], []
    for row in starts:
        path = np.array([returns[(s + k) % n] for s in row for k in range(b)][:n])
        finals.append(np.prod(1 + path) - 1)
        drops.append(drop(path))
    values = read(tmp_path, tool, n_paths=50, block_length=b)
    assert values["median"] == pytest.approx(np.quantile(finals, 0.5), **APPROX)
    assert values["drop_q95"] == pytest.approx(np.quantile(drops, 0.95), **APPROX)


def test_known_answer_wild(tmp_path: Path) -> None:
    returns = wavy(40)
    put(tmp_path, returns)
    values = read(tmp_path, WILD, n_resamples=300)
    assert values["mean"] == pytest.approx(returns.mean(), **APPROX)
    assert values["lower"] < values["mean"] < values["upper"]
    # Mammen (1993) weights, drawn and applied one bar at a time.
    rng, root = np.random.default_rng(SEED), math.sqrt(5)
    draws = rng.random((300, 40)) < (root + 1) / (2 * root)
    means = []
    for row in draws:
        w = np.where(row, (1 - root) / 2, (1 + root) / 2)
        means.append(returns.mean() + np.mean(w * (returns - returns.mean())))
    assert values["lower"] == pytest.approx(np.quantile(means, 0.025), **APPROX)
    assert values["share_at_or_below_zero"] == pytest.approx(
        np.mean(np.array(means) <= 0), **APPROX
    )


def test_known_answer_ruin(tmp_path: Path) -> None:
    put(tmp_path, [-0.1] * 20)  # falls 88%, so every redraw is ruined
    assert read(tmp_path, RUIN, n_paths=50) == pytest.approx(
        {"ruin_share": 1.0, "std_error": 0.0}, **APPROX
    )
    returns = wavy(50)
    put(tmp_path, returns)
    values = read(tmp_path, RUIN, n_paths=200, ruin_drawdown=0.05)
    direct = risk_of_ruin(returns, ruin_drawdown=0.05, n_paths=200, mean_block=5.0, seed=SEED)
    assert values["ruin_share"] == pytest.approx(direct, **APPROX)


def test_known_answer_shuffle(tmp_path: Path) -> None:
    put(tmp_path, [0.01, -0.01] * 10)
    values = read(tmp_path, SHUFFLE, n_shuffles=200)
    # Hand: 19 products of -1e-4 over a sum of squares of 20e-4 gives -19/20.
    assert values["autocorr"] == pytest.approx(-0.95, rel=1e-9, abs=1e-9)
    assert values["p_value"] < 0.05
    assert values["null_low"] < 0 < values["null_high"]


def test_known_answer_phase(tmp_path: Path) -> None:
    put(tmp_path, [0.01] * 16)  # only the average has any spectrum, so every copy is the run
    values = read(tmp_path, PHASE, n_paths=20)
    assert values == pytest.approx(
        {"observed": 0.0, "median": 0.0, "q95": 0.0, "share_as_deep": 1.0}, rel=1e-9, abs=1e-12
    )
    returns = wavy(33)
    put(tmp_path, returns)
    logs, spectrum = np.log1p(returns), np.fft.rfft(np.log1p(returns))
    u = np.random.default_rng(SEED).random((25, len(spectrum)))
    drops = []
    for row in u:
        phase = np.exp(2j * np.pi * row)
        phase[0] = 1
        copy = np.expm1(np.fft.irfft(spectrum * phase, n=len(logs)))
        assert np.abs(np.fft.rfft(np.log1p(copy))).max() == pytest.approx(np.abs(spectrum).max())
        drops.append(drop(copy))
    values = read(tmp_path, PHASE, n_paths=25)
    assert values["median"] == pytest.approx(np.median(drops), **APPROX)
    assert values["observed"] == pytest.approx(drop(returns), **APPROX)


def test_known_answer_years(tmp_path: Path) -> None:
    returns = [0.1, 0.1, -0.5, 0.0, 0.2, -0.3]
    dates = [datetime(2021, 12, 31, tzinfo=UTC)] + [
        datetime(y, m, 1, tzinfo=UTC) for y in (2022, 2023, 2024) for m in (3, 4)
    ]
    put(tmp_path, returns, dates=dates)
    values = read(tmp_path, YEARS, n_paths=60)
    orders = [
        drop(np.concatenate([np.array(returns).reshape(3, 2)[list(o)].ravel()]))
        for o in itertools.permutations(range(3))
    ]
    assert values["observed"] == pytest.approx(drop(np.array(returns)), **APPROX)
    assert min(orders) - 1e-12 <= values["median"] <= max(orders) + 1e-12
    assert values["q95"] <= max(orders) + 1e-12
    rng = np.random.default_rng(SEED)
    mine = [drop(np.array(returns).reshape(3, 2)[rng.permutation(3)].ravel()) for _ in range(60)]
    assert values["median"] == pytest.approx(np.median(mine), **APPROX)


def test_known_answer_halves(tmp_path: Path) -> None:
    returns = 0.01 + 0.002 * np.sin(np.arange(30))  # every bar gains, so every half gains
    put(tmp_path, returns)
    values = read(tmp_path, HALVES, n_splits=50)
    assert values["share_both_positive"] == pytest.approx(1.0, **APPROX)
    order = np.random.default_rng(SEED).permuted(np.tile(np.arange(30), (50, 1)), axis=1)
    gaps = []
    for row in order:
        a, b = returns[row[:15]], returns[row[15:]]
        sharpe = [x.mean() / x.std(ddof=1) * math.sqrt(365) for x in (a, b)]
        gaps.append(abs(sharpe[0] - sharpe[1]))
    assert values["median_gap"] == pytest.approx(np.median(gaps), **APPROX)


def test_known_answer_trade_order(tmp_path: Path) -> None:
    put(tmp_path, [0.01] * 5, pnls=[-0.1] * 6)  # 1.0 falls to 0.4 whatever the order
    assert read(tmp_path, ORDER, n_paths=30) == pytest.approx(
        {"observed": 0.6, "median": 0.6, "q95": 0.6}, **APPROX
    )
    pnls = [0.3, -0.4, 0.2, -0.1, 0.5, -0.2]
    put(tmp_path, [0.01] * 5, pnls=pnls)
    rng = np.random.default_rng(SEED)
    drops = []
    for _ in range(40):
        equity = 1.0 + np.r_[0.0, np.cumsum(rng.permuted(np.array(pnls)))]
        drops.append(np.max(1 - equity / np.maximum.accumulate(equity)))
    values = read(tmp_path, ORDER, n_paths=40)
    assert values["median"] == pytest.approx(np.median(drops), **APPROX)
    equity = 1.0 + np.r_[0.0, np.cumsum(pnls)]
    assert values["observed"] == pytest.approx(
        np.max(1 - equity / np.maximum.accumulate(equity)), **APPROX
    )


def test_known_answer_jackknife(tmp_path: Path) -> None:
    put(tmp_path, [0.01] * 5, pnls=[1.0, 2.0, 3.0, 4.0, 10.0])
    # Leave-one-out means are (20 - p) / 4; the jackknife error of a mean is s / sqrt(n).
    assert read(tmp_path, JACK) == pytest.approx(
        {"mean": 4.0, "lowest": 2.5, "highest": 4.75, "std_error": math.sqrt(12.5 / 5)}, **APPROX
    )


def test_known_answer_year_jackknife(tmp_path: Path) -> None:
    dates = [datetime(2021, 12, 31, tzinfo=UTC)] + [
        datetime(y, 3, 1, tzinfo=UTC) for y in (2022, 2023, 2024)
    ]
    put(tmp_path, [0.1, 0.2, -0.1], dates=dates)
    values = read(tmp_path, YEAR_JACK)
    assert values["driver_year"] == "2023"
    del values["driver_year"]
    assert values == pytest.approx({"total": 0.188, "lowest": -0.01, "highest": 0.32}, **APPROX)


def test_known_answer_stress(tmp_path: Path) -> None:
    put(tmp_path, [0.1, -0.1, 0.1])
    values = read(tmp_path, STRESS, vol_scale=2.0, shock=-0.05)
    # Scaled bars are 1/6, -7/30, 1/6; the shock lands after the first bar: 1.1 falls to 0.9405.
    assert values == pytest.approx(
        {
            "observed_drop": 0.1,
            "scaled_total": (7 / 6) ** 2 * (23 / 30) - 1,
            "scaled_drop": 7 / 30,
            "shocked_drop": 1 - 0.9405 / 1.1,
        },
        **APPROX,
    )
    put(tmp_path, [-0.5, 0.1, 0.1])
    values = read(tmp_path, STRESS, vol_scale=5.0)
    assert values["scaled_total"] is None


@pytest.mark.parametrize("tool", TOOLS)
def test_too_little_data(tool: str, tmp_path: Path) -> None:
    put(tmp_path, [0.01], pnls=[1.0])
    doc = run(tmp_path, tool, RUN)
    assert all(value is None for value in doc["values"].values())
    assert all("at least" in reason for reason in doc["reasons"].values())
    assert set(doc["reasons"]) == set(doc["values"])


@pytest.mark.parametrize("tool", TOOLS)
def test_repeat_is_identical(tool: str, tmp_path: Path) -> None:
    put(tmp_path, wavy(60), pnls=[0.5, -0.2, 0.4, -0.1, 0.3, 0.2, -0.3, 0.1])
    params = [f"{k}={v}" for k, v in SMALL.items() if k in {p.name for p in get(tool).params}]
    doc = run(tmp_path, tool, RUN, params, seed=7)
    assert run(tmp_path, tool, RUN, params, seed=7) == doc
    first = read(tmp_path, tool, 7)
    assert read(tmp_path, tool, 7) == first
    if get(tool).seeded:
        assert doc["result"]["seed"] != 0 and "seed" in doc["result"]
        assert read(tmp_path, tool, 8) != first or tool in {YEARS, RUIN}


@pytest.mark.parametrize("tool", TOOLS)
def test_future_input_rejected(tool: str, tmp_path: Path) -> None:
    put(tmp_path, wavy(60), pnls=[0.5, -0.2, 0.4, -0.1, 0.3, 0.2])
    name, field = (
        ("trades.parquet", "exit_ts") if tool in TRADE_TOOLS else ("equity_curve.parquet", "ts")
    )
    path = tmp_path / "runs" / RUN / name
    frame = pl.read_parquet(path)
    frame.vstack(
        frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias(field))
    ).write_parquet(path)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)


def test_specs_are_readings() -> None:
    for tool in TOOLS:
        spec = get(tool)
        assert spec.family == "resampling" and spec.look in {"test", "describe"}
        assert spec.question.endswith("?") and spec.caveats


def test_halves_share_counts_flat_halves(tmp_path: Path) -> None:
    returns = np.zeros(20)
    returns[[3, 11]] = 0.01  # most random halves are flat, yet their means are defined
    put(tmp_path, returns)
    values = read(tmp_path, HALVES, n_splits=200)
    order = np.random.default_rng(SEED).permuted(np.tile(np.arange(20), (200, 1)), axis=1)
    both = np.mean([(returns[r[:10]].mean() > 0) and (returns[r[10:]].mean() > 0) for r in order])
    assert values["share_both_positive"] == pytest.approx(both, **APPROX)
    assert values["share_both_positive"] < 0.8
