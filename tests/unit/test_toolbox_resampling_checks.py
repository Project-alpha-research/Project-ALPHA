"""Stored-run checks against the public validation calls, planted effects and short histories."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli._seeds import semantic_seed
from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.inputs import Inputs, resolve
from alpha_cli.toolbox.registry import get
from alpha_cli.toolbox.runner import run
from alpha_validation import (
    FloatArray,
    block_bootstrap_ci,
    cagr,
    empirical_return_paths,
    expected_max_sharpe,
    path_metric_arrays,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    stationary_bootstrap_indices,
    summarize_path_family,
    to_returns,
    trade_runs_test,
)
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_run_level_checks import END, START, stored_run, write_trades

SHARPE = "resampling.sharpe_interval"
YEAR = "resampling.return_interval"
DROP = "resampling.drawdown_distribution"
RUNS = "trades.dependence"
DSR = "overfit.deflated_sharpe"
PATHS = "resampling.block_bootstrap_paths"
TOOLS = (SHARPE, YEAR, DROP, RUNS, DSR, PATHS)
PARAMS: dict[str, dict[str, Any]] = {
    SHARPE: {"n_resamples": 60, "mean_block": 5.0, "confidence": 0.95},
    YEAR: {"n_resamples": 60, "mean_block": 5.0, "confidence": 0.95},
    DROP: {"n_paths": 60},
    RUNS: {},
    DSR: {},
    PATHS: {"n_paths": 60, "mean_block": 5.0},
}
PRIOR = [-0.14, 0.11, -0.21, 0.25]
PNLS = [2.0, -1.0] * 15
REFERENCE = Path(__file__).parents[1] / "fixtures/toolbox_resampling_checks.json"


def write_equity(folder: Path, equity: FloatArray) -> None:
    dates = [START + timedelta(days=i) for i in range(len(equity))]
    pl.DataFrame({"ts": dates, "equity": equity}).write_parquet(folder / "equity_curve.parquet")


def prepare_sample(home: Path) -> FloatArray:
    folder = stored_run(home, SHARPE)
    # A net gain with losses bunched together at the end.
    steps = np.r_[np.linspace(0.001, 0.007, 50), np.linspace(-0.0035, -0.001, 10)]
    equity = np.r_[1.0, np.cumprod(1.0 + steps)]
    write_equity(folder, equity)
    write_trades(folder, PNLS, ["BUY"] * len(PNLS))
    # Physical row order is not the contract for a runs test.
    trades = folder / "trades.parquet"
    pl.read_parquet(trades).sort("realized_pnl").write_parquet(trades)
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["dsr"] = {
        "family_id": "spine:ma_cross",
        "family_count": 8,
        "n_trials": 9,
        "comparable_trials": 5,
        "repeats": 0,
        "prior_sharpes": PRIOR,
    }
    path.write_text(json.dumps(manifest))
    return to_returns(equity)


def direct(tool: str, returns: FloatArray, seed: int) -> dict[str, float]:
    if tool in (SHARPE, YEAR):

        def statistic(sample: FloatArray) -> float:
            if tool == SHARPE:
                return sharpe_ratio(sample, periods_per_year=365)
            return cagr(np.r_[1.0, np.cumprod(1 + sample)], periods_per_year=365)

        ci = block_bootstrap_ci(returns, statistic, seed=seed, **PARAMS[tool])
        return {"point": ci.point, "lower": ci.lower, "upper": ci.upper}
    if tool == DROP:
        paths = empirical_return_paths(returns, n_paths=60, seed=seed)
        summary = summarize_path_family("iid_empirical", paths)
        return {
            "observed": float(path_metric_arrays(returns[None, :]).maximum_drawdown[0]),
            "median": summary.maximum_drawdown_q50,
            "q95": summary.maximum_drawdown_q95,
        }
    if tool == RUNS:
        result = trade_runs_test(PNLS)
        assert result is not None
        return {
            "runs": result.n_runs,
            "expected": result.expected_runs,
            "z": result.z,
            "p_value": result.p_value,
        }
    if tool == DSR:
        spread = float(np.var([*PRIOR, sharpe_ratio(returns, periods_per_year=1)], ddof=1))
        hurdle = expected_max_sharpe(spread, 9)
        return {
            "dsr": probabilistic_sharpe_ratio(returns, benchmark_sr=hurdle),
            "trials": 9,
            "benchmark": hurdle,
        }
    assert tool == PATHS
    rows = stationary_bootstrap_indices(
        len(returns), mean_block=5.0, n_resamples=60, rng=np.random.default_rng(seed)
    )
    block = summarize_path_family("stationary_bootstrap", returns[rows])
    return {
        "low": block.terminal_return_q05,
        "median": block.terminal_return_q50,
        "high": block.terminal_return_q95,
        "drop_q95": block.maximum_drawdown_q95,
    }


@pytest.mark.parametrize("tool", TOOLS)
def test_public_function_parity(tool: str, tmp_path: Path) -> None:
    returns = prepare_sample(tmp_path)
    spec = get(tool)
    assert spec.kind == spec.look == "test"
    settings = [f"{k}={v}" for k, v in PARAMS[tool].items()]
    doc = run(tmp_path, tool, RUN, settings, seed=19)
    seed = 0
    if spec.seeded:
        seed = doc["result"]["seed"]
        assert "non-default-params" in doc["labels"]
        assert doc["settings_tried"] == [{**PARAMS[tool], "seed": 19}]
    assert doc["values"] == pytest.approx(direct(tool, returns, seed), rel=1e-9, abs=1e-12)
    assert run(tmp_path, tool, RUN, settings, seed=19) == doc
    # Keep platform-specific parquet byte hashes out of the numerical reference seed.
    assert spec.compute is not None
    fixed = spec.compute(
        Inputs(resolve(tmp_path, RUN), seed=19),
        PARAMS[tool],
        np.random.default_rng(19) if spec.seeded else None,
    )
    assert fixed.values == pytest.approx(
        json.loads(REFERENCE.read_text())[tool], rel=1e-9, abs=1e-12
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_planted_direction(tool: str, tmp_path: Path) -> None:
    returns = prepare_sample(tmp_path)
    if tool == PATHS:
        # Every possible path gains, independently of the seed derived from the stored bytes.
        gains = np.linspace(0.001, 0.007, 60)
        write_equity(tmp_path / "runs" / RUN, np.r_[1.0, np.cumprod(1.0 + gains)])
    doc = run(tmp_path, tool, RUN)
    values = doc["values"]
    if tool in (SHARPE, YEAR):
        assert values["upper"] > values["lower"] > 0
        which = "sharpe_ci" if tool == SHARPE else "cagr_ci"
        assert doc["result"]["seed"] == semantic_seed(7, f"validation.{which}")
    elif tool == DROP:
        assert values["observed"] > values["q95"] >= values["median"]
        assert doc["result"]["seed"] == semantic_seed(7, "monte_carlo.iid")
    elif tool == RUNS:
        assert values["z"] > 0 and values["p_value"] < 0.001
    elif tool == DSR:
        assert values["dsr"] < probabilistic_sharpe_ratio(returns)
    else:
        assert 0 < values["low"] < values["median"] < values["high"]


@pytest.mark.parametrize("tool", TOOLS)
def test_insufficient_observations(tool: str, tmp_path: Path) -> None:
    prepare_sample(tmp_path)
    folder = tmp_path / "runs" / RUN
    write_equity(folder, np.array([1.0, 1.1]))
    write_trades(folder, [2.0], ["BUY"])
    doc = run(tmp_path, tool, RUN)
    numeric = {key for key in doc["values"] if key != "trials"}
    assert all(doc["values"][key] is None for key in numeric)
    assert all("at least" in doc["reasons"][key].lower() for key in numeric)


@pytest.mark.parametrize("tool", TOOLS)
def test_future_input_rejected(tool: str, tmp_path: Path) -> None:
    prepare_sample(tmp_path)
    folder = tmp_path / "runs" / RUN
    name, field = ("trades.parquet", "exit_ts") if tool == RUNS else ("equity_curve.parquet", "ts")
    path = folder / name
    frame = pl.read_parquet(path)
    frame.vstack(
        frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias(field))
    ).write_parquet(path)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)


def test_missing_family_snapshot(tmp_path: Path) -> None:
    stored_run(tmp_path, DSR)
    doc = run(tmp_path, DSR, RUN)
    assert doc["values"]["dsr"] is None and "family" in doc["reasons"]["dsr"]


def test_undefined_sharpe_and_runs(tmp_path: Path) -> None:
    prepare_sample(tmp_path)
    folder = tmp_path / "runs" / RUN
    write_equity(folder, np.ones(12))
    write_trades(folder, [1.0] * 8, ["BUY"] * 8)
    for tool, key in [(SHARPE, "point"), (DSR, "dsr"), (RUNS, "p_value")]:
        doc = run(tmp_path, tool, RUN)
        assert doc["values"][key] is None and doc["reasons"][key]


def test_invalid_family_count_fails_loud(tmp_path: Path) -> None:
    prepare_sample(tmp_path)
    path = tmp_path / "runs" / RUN / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["dsr"]["n_trials"] = 0
    path.write_text(json.dumps(manifest))
    with pytest.raises(SpineError, match="n_trials"):
        run(tmp_path, DSR, RUN)


@pytest.mark.parametrize("tool", (SHARPE, YEAR))
def test_constant_history_has_no_reportable_interval(tool: str, tmp_path: Path) -> None:
    prepare_sample(tmp_path)
    write_equity(tmp_path / "runs" / RUN, np.ones(10))
    doc = run(tmp_path, tool, RUN)
    assert all(value is None for value in doc["values"].values())
    assert all("varying" in reason for reason in doc["reasons"].values())


def test_drawdown_peak_memory(tmp_path: Path) -> None:
    import tracemalloc

    from alpha_cli.toolbox.families.resampling import drawdowns

    folder = stored_run(tmp_path, DROP)
    returns = np.random.default_rng(137).normal(0.0002, 0.01, 7500)
    dates = [END - timedelta(days=i) for i in reversed(range(7501))]
    pl.DataFrame({"ts": dates, "equity": np.r_[1.0, np.cumprod(1 + returns)]}).write_parquet(
        folder / "equity_curve.parquet"
    )
    inputs = Inputs(resolve(tmp_path, RUN), seed=19)
    n_paths = 10_000  # The entry's default: the size that used about 3.7 GB on a real run.
    tracemalloc.start()
    try:
        drawdowns(inputs, {"n_paths": n_paths}, np.random.default_rng(inputs.seed))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Traced bytes do not depend on the machine. One full paths-by-bars float matrix is 600 MB,
    # and the unchunked entry held several at once; the chunked entry stays near 130 MB.
    assert peak < n_paths * len(returns) * 8


@pytest.mark.parametrize("chunk_size", [1, 7, 31])
def test_drawdown_chunk_sizes_match_one_draw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk_size: int
) -> None:
    from alpha_cli.toolbox.families import resampling
    from alpha_validation import path_montecarlo

    returns = prepare_sample(tmp_path)
    # Odd horizons also exercise the generator's saved half-word across chunk boundaries.
    returns = returns[:-1]
    write_equity(tmp_path / "runs" / RUN, np.r_[1.0, np.cumprod(1.0 + returns)])
    inputs = Inputs(resolve(tmp_path, RUN), seed=19)
    sizes = []

    def draw(values: FloatArray, *, n_paths: int, seed: Any) -> FloatArray:
        sizes.append(n_paths)
        return empirical_return_paths(values, n_paths=n_paths, seed=seed)

    monkeypatch.setattr(path_montecarlo, "empirical_return_paths", draw)
    monkeypatch.setattr(resampling, "PATH_CHUNK_CELLS", chunk_size * len(returns))
    got = resampling.drawdowns(inputs, PARAMS[DROP], np.random.default_rng(inputs.seed))
    assert got.values == pytest.approx(
        direct(DROP, inputs.stored.scored_returns(), 19), rel=1e-9, abs=1e-12
    )
    assert sum(sizes) == PARAMS[DROP]["n_paths"] and max(sizes) <= chunk_size


def test_the_deflated_sharpe_sentence_says_what_it_is_and_why_the_test_can_differ(
    tmp_path: Path,
) -> None:
    prepare_sample(tmp_path)
    doc = run(tmp_path, DSR, RUN, [], seed=19)
    text = " ".join(str(value) for value in doc.values() if isinstance(value, str))
    assert "same count and formula as the test" in text
    assert "not clear of chance" in text and "null test" in text
