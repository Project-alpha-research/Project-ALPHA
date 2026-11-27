"""rdagent_factor_eval.py hands its series and replay helpers to two new modules: a pure move."""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

SERIES = "alpha_cli._factor_eval_series"
REPLAY = "alpha_cli._factor_eval_replay"
SERIES_NAMES = [
    "_bucket_frames",
    "_clock_series_frames",
    "_series_frames",
    "_series_file",
    "_write_series",
    "_record_series",
]
REPLAY_NAMES = ["_replay_clocks", "_gap_disclosure", "_chance_disclosure"]
KEPT_NAMES = [
    "evaluate",
    "main",
    "_inputs",
    "_deflate",
    "_report",
    "shown",
    "record_shortlist",
]


def _orchestrator_source() -> str:
    from alpha_cli import rdagent_factor_eval as ev

    return Path(inspect.getfile(ev)).read_text()


@pytest.mark.parametrize("name", SERIES_NAMES)
def test_series_names_live_in_series_module(name: str) -> None:
    module = importlib.import_module(SERIES)
    function = getattr(module, name)
    assert function.__module__ == SERIES


@pytest.mark.parametrize("name", REPLAY_NAMES)
def test_replay_names_live_in_replay_module(name: str) -> None:
    module = importlib.import_module(REPLAY)
    function = getattr(module, name)
    assert function.__module__ == REPLAY


@pytest.mark.parametrize("name", SERIES_NAMES + REPLAY_NAMES)
def test_moved_definitions_left_the_orchestrator(name: str) -> None:
    source = _orchestrator_source()
    assert f"def {name}(" not in source
    importlib.import_module(SERIES)
    importlib.import_module(REPLAY)


@pytest.mark.parametrize("module", [SERIES, REPLAY])
def test_new_modules_import_alone_without_cycle(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", KEPT_NAMES)
def test_orchestrator_keeps_its_own_names(name: str) -> None:
    from alpha_cli import rdagent_factor_eval as ev

    function = getattr(ev, name)
    assert function.__module__ == "alpha_cli.rdagent_factor_eval"
    assert f"def {name}(" in _orchestrator_source()
    assert hasattr(ev, "RESERVED_DAY")
    assert hasattr(ev, "RESERVED_START")


def test_rdagent_help_still_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alpha_cli.rdagent_factor_eval", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower()
