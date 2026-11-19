"""The Student-t Monte Carlo check agrees with the classical command's function."""

import json
import time
import tracemalloc
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli._rdagent_checks import FactorTarget
from alpha_cli._seeds import semantic_seed
from alpha_cli.spine.errors import SpineError
from alpha_cli.tool_cmds import tool_app
from alpha_cli.toolbox import runner
from alpha_cli.toolbox.families import montecarlo
from alpha_cli.toolbox.inputs import Inputs, resolve
from alpha_cli.toolbox.registry import SPECS, get
from alpha_cli.toolbox.runner import run
from alpha_validation import (
    FloatArray,
    student_t_return_paths,
    summarize_path_family,
    to_returns,
)
from tests.unit.test_rdagent_factor_eval import evaluate, fixture
from tests.unit.test_rdagent_factor_eval import recorded_time as recorded_time
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_resampling_checks import write_equity
from tests.unit.test_toolbox_run_level_checks import END, START, stored_run

STUDENT = "resampling.student_t_paths"
TOOLS = (STUDENT,)
PARAMS: dict[str, dict[str, Any]] = {STUDENT: {"n_paths": 200}}
SEEDS = {STUDENT: "monte_carlo.student_t"}
REFERENCE = Path(__file__).parents[1] / "fixtures/toolbox_montecarlo_checks.json"
PEAK_BYTES = 600 * 1024 * 1024


def sample_returns() -> FloatArray:
    """Alternating calm and stormy spells, so the tails are fat."""
    rng = np.random.default_rng(5)
    spell = np.repeat(np.tile([0.004, 0.02], 10), 20)
    return np.asarray(rng.normal(0.0008, spell), dtype=np.float64)


def prepare(home: Path) -> FloatArray:
    folder = stored_run(home, STUDENT)
    returns = sample_returns()
    write_equity(folder, np.r_[1.0, np.cumprod(1.0 + returns)])
    return to_returns(np.r_[1.0, np.cumprod(1.0 + returns)])


def command_numbers(tool: str, returns: FloatArray, params: dict[str, Any], seed: int) -> Any:
    """What `alpha monte-carlo classical` does for one family, with its own functions."""
    assert tool == STUDENT
    paths = student_t_return_paths(returns, n_paths=params["n_paths"], seed=seed)
    s = summarize_path_family(tool, paths)
    return {
        "low": s.terminal_return_q05,
        "median": s.terminal_return_q50,
        "high": s.terminal_return_q95,
        "drop_q95": s.maximum_drawdown_q95,
    }


@pytest.mark.parametrize("tool", TOOLS)
def test_agrees_with_classical_command(tool: str, tmp_path: Path) -> None:
    returns = prepare(tmp_path)
    spec = get(tool)
    assert spec.kind == spec.look == "test" and spec.needs == ("stored_equity",)
    settings = [f"{k}={v}" for k, v in PARAMS[tool].items()]
    doc = run(tmp_path, tool, RUN, settings)
    # The command's seed for this family at its default master seed 7.
    assert doc["result"]["seed"] == semantic_seed(7, SEEDS[tool])
    assert doc["values"] == pytest.approx(
        command_numbers(tool, returns, PARAMS[tool], doc["result"]["seed"]), rel=1e-9, abs=1e-12
    )
    assert run(tmp_path, tool, RUN, settings) == doc
    assert spec.compute is not None
    fixed = spec.compute(
        Inputs(resolve(tmp_path, RUN), seed=19), PARAMS[tool], np.random.default_rng(19)
    )
    assert fixed.values == pytest.approx(
        json.loads(REFERENCE.read_text())[tool], rel=1e-9, abs=1e-12
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_reading_is_plain_and_names_the_model(tool: str, tmp_path: Path) -> None:
    prepare(tmp_path)
    doc = run(tmp_path, tool, RUN, [f"{k}={v}" for k, v in PARAMS[tool].items()])
    text = doc["reading"]
    assert "profit" not in text.lower() and "not a forecast" in text and "re-draws" in text
    assert "Nine histories in ten" in text and "One in twenty" in text and "Student-t" in text


@pytest.mark.parametrize("tool", TOOLS)
def test_reserved_label_follows_the_input(tool: str, tmp_path: Path) -> None:
    prepare(tmp_path)
    settings = [f"{k}={v}" for k, v in PARAMS[tool].items()]
    assert "reserved-period-seen" in run(tmp_path, tool, RUN, settings)["labels"]
    path = tmp_path / "runs" / RUN / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["metadata"]["last_ts"] = (START + timedelta(days=500)).isoformat()
    path.write_text(json.dumps(manifest))
    assert "reserved-period-seen" not in run(tmp_path, tool, RUN, settings)["labels"]


@pytest.mark.parametrize("tool", TOOLS)
def test_short_history_is_unavailable(tool: str, tmp_path: Path) -> None:
    prepare(tmp_path)
    write_equity(tmp_path / "runs" / RUN, np.array([1.0, 1.1]))
    doc = run(tmp_path, tool, RUN)
    assert all(value is None for value in doc["values"].values())
    assert all("at least" in reason for reason in doc["reasons"].values())


@pytest.mark.parametrize("tool", TOOLS)
def test_future_input_rejected(tool: str, tmp_path: Path) -> None:
    prepare(tmp_path)
    path = tmp_path / "runs" / RUN / "equity_curve.parquet"
    frame = pl.read_parquet(path)
    frame.vstack(
        frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias("ts"))
    ).write_parquet(path)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)


@pytest.mark.parametrize("tool", TOOLS)
def test_chunks_match_one_draw(tool: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    returns = prepare(tmp_path)
    inputs = Inputs(resolve(tmp_path, RUN), seed=19)
    compute = get(tool).compute
    assert compute is not None
    whole = compute(inputs, PARAMS[tool], None).values
    one = command_numbers(tool, returns, PARAMS[tool], inputs.seed)
    assert whole == pytest.approx(one, rel=1e-9, abs=1e-12)
    for rows in (1, 7):
        monkeypatch.setattr(montecarlo, "PATH_CHUNK_CELLS", rows * len(returns))
        chunked = compute(inputs, PARAMS[tool], None).values
        assert chunked == pytest.approx(one, rel=1e-9, abs=1e-12)


def measured(tool: str, tmp_path: Path) -> tuple[int, float]:
    folder = stored_run(tmp_path, tool)
    rng = np.random.default_rng(137)
    returns = rng.normal(0.0002, np.repeat(np.tile([0.005, 0.02], 25), 150))
    dates = [END - timedelta(days=i) for i in reversed(range(7501))]
    pl.DataFrame({"ts": dates, "equity": np.r_[1.0, np.cumprod(1 + returns)]}).write_parquet(
        folder / "equity_curve.parquet"
    )
    inputs = Inputs(resolve(tmp_path, RUN), seed=19)
    compute: Callable[..., Any] | None = get(tool).compute
    assert compute is not None
    default = {p.name: p.default for p in get(tool).params}
    tracemalloc.start()
    began = time.monotonic()
    try:
        result = compute(inputs, default, None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert all(v is not None for v in result.values.values())
    return peak, time.monotonic() - began


@pytest.mark.parametrize("tool", TOOLS)
def test_peak_memory_at_default_paths_on_long_history(tool: str, tmp_path: Path) -> None:
    peak, seconds = measured(tool, tmp_path)
    print(f"{tool}: peak {peak / 2**20:.0f} MB, {seconds:.1f} s")
    assert peak < PEAK_BYTES


def test_runs_on_a_factor_replay(tmp_path: Path, recorded_time: None) -> None:
    run_dir = tmp_path / "run"
    req = fixture(run_dir)
    record = evaluate(run_dir, req, tmp_path / "ledger")
    source = FactorTarget.from_row(run_dir, record, record["factors"][0])
    returns = source.scored_returns()
    for tool in TOOLS:
        settings = ["n_paths=100"]
        doc = runner.run(run_dir / "checks", tool, source.run_id, settings, source=source)
        assert "rdagent-factor" in doc["labels"]
        assert all(isinstance(v, float) for v in doc["values"].values()), doc["reasons"]
        params = {**{p.name: p.default for p in get(tool).params}, "n_paths": 100}
        assert doc["values"] == pytest.approx(
            command_numbers(tool, returns, params, doc["result"]["seed"]), rel=1e-9, abs=1e-12
        )
        again = runner.run(run_dir / "checks", tool, source.run_id, settings, source=source)
        assert again == doc


def test_listed_and_described(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    cli = CliRunner()
    listed = json.loads(cli.invoke(tool_app, ["list", "--json"]).stdout)
    assert len(SPECS) == len(listed) == 15
    ids = {row["id"] for row in listed}
    assert set(TOOLS) <= ids and "resampling.regime_paths" not in ids
    for tool in TOOLS:
        card = json.loads(cli.invoke(tool_app, ["describe", tool, "--json"]).stdout)
        assert card["id"] == tool and card["seeded"] is True
