"""monte_carlo_cmds.py hands its source and frame helpers to two new modules, unchanged."""

from __future__ import annotations

import importlib
import inspect
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from alpha_core import DataError

SOURCES = "alpha_cli._monte_carlo_sources"
FRAMES = "alpha_cli._monte_carlo_frames"
OLD = "alpha_cli.monte_carlo_cmds"

SOURCE_FUNCS = (
    "_verified_validation_source",
    "_verified_forecast_eval",
    "_only_fitting_eval",
    "_resolve_eval",
    "_horizon_steps",
    "_spec_from_validation",
)
FRAME_FUNCS = (
    "_regime_caveats",
    "_path_frame",
    "_metric_frame",
    "_summarize_families",
    "_observed_frame",
)
STAYING = (
    "_forecaster_factory",
    "_source_as_of",
    "_causal_regime_states",
    "_project_forecast_path",
    "classical",
    "kronos",
)


def test_sources_module_holds_its_moved_names() -> None:
    module = importlib.import_module(SOURCES)
    for name in SOURCE_FUNCS:
        func = getattr(module, name)
        assert func.__module__ == SOURCES, name


def test_frames_module_holds_its_moved_names() -> None:
    module = importlib.import_module(FRAMES)
    for name in FRAME_FUNCS:
        func = getattr(module, name)
        assert func.__module__ == FRAMES, name
    assert hasattr(module, "MIN_STATE_SHARE")
    text = inspect.getsource(module)
    assert re.search(r"^MIN_STATE_SHARE\b[^\n]*=", text, re.MULTILINE)


@pytest.mark.parametrize("module", [SOURCES, FRAMES])
def test_new_modules_import_on_their_own(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_monte_carlo_cmds_no_longer_defines_moved_names() -> None:
    text = inspect.getsource(importlib.import_module(OLD))
    for name in (*SOURCE_FUNCS, *FRAME_FUNCS):
        assert not re.search(rf"^def {name}\(", text, re.MULTILINE), name
    assert not re.search(r"^MIN_STATE_SHARE\b[^\n]*=", text, re.MULTILINE)


def test_moved_helpers_behave_as_before() -> None:
    sources = importlib.import_module(SOURCES)
    frames = importlib.import_module(FRAMES)
    with pytest.raises(DataError, match="must be a sequence"):
        sources._spec_from_validation({"metadata": {"strategy_params": {"lookback": 20}}})
    with pytest.raises(DataError, match="at least one"):
        frames._path_frame(())
    start = datetime(2024, 1, 2, tzinfo=UTC)
    equity = [(start + timedelta(days=i), 100.0 + i) for i in range(3)]
    frame = frames._observed_frame(equity)
    assert frame.columns == ["step", "ts", "equity"]
    assert frame["step"].to_list() == [0, 1, 2]
    assert frame["equity"].to_list() == [100.0, 101.0, 102.0]


def test_monte_carlo_help_lists_both_commands() -> None:
    from alpha_cli.monte_carlo_cmds import monte_carlo_app

    result = CliRunner().invoke(monte_carlo_app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "classical" in result.output
    assert "kronos" in result.output


def test_pinned_helpers_stay_in_monte_carlo_cmds() -> None:
    module = importlib.import_module(OLD)
    text = inspect.getsource(module)
    for name in STAYING:
        assert hasattr(module, name), name
        pattern = rf"^(?:def {name}\(|{name}\b[^\n]*=)"
        assert re.search(pattern, text, re.MULTILINE), name
