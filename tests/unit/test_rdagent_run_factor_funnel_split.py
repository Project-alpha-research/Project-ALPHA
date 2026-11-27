"""_rdagent_runs.py hands its factor and funnel helpers to two new modules, unchanged."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

FACTOR_NAMES = ("_clock", "_derived_status", "_honesty_sentence", "_factor")
FUNNEL_NAMES = ("_ledger_factor_rows", "_funnel", "_any_clock", "_passed_deflation", "_ledger")


@pytest.mark.parametrize("name", FACTOR_NAMES)
def test_factor_names_live_in_run_factor(name: str) -> None:
    module = importlib.import_module("alpha_web._rdagent_run_factor")
    func = getattr(module, name)
    assert func.__module__ == "alpha_web._rdagent_run_factor"


@pytest.mark.parametrize("name", FUNNEL_NAMES)
def test_funnel_names_live_in_run_funnel(name: str) -> None:
    module = importlib.import_module("alpha_web._rdagent_run_funnel")
    func = getattr(module, name)
    assert func.__module__ == "alpha_web._rdagent_run_funnel"


def test_runs_module_holds_no_moved_name() -> None:
    runs = importlib.import_module("alpha_web._rdagent_runs")
    for name in FACTOR_NAMES + FUNNEL_NAMES:
        held = getattr(runs, name, None)
        # Importing a moved name for use is fine; defining it again here is not.
        assert held is None or held.__module__ != "alpha_web._rdagent_runs", name


def test_moved_status_and_deflation_behave_the_same() -> None:
    from alpha_web._rdagent_run_factor import _derived_status, _honesty_sentence
    from alpha_web._rdagent_run_funnel import _passed_deflation

    failing = {
        "status": "CANDIDATE",
        "replay": {"deflated_sharpe": {"dsr": 0.5, "threshold": 0.95, "passed": False}},
    }
    passing = {
        "status": "CANDIDATE",
        "replay": {"deflated_sharpe": {"dsr": 0.99, "threshold": 0.95, "passed": True}},
    }
    assert _derived_status(failing) == "DEFLATION_FAIL"
    assert _derived_status(passing) == "CANDIDATE"
    assert _passed_deflation(passing) is True
    assert _passed_deflation(failing) is False
    assert _honesty_sentence({"status": "OK"}) == ""
    assert "old rule" in _honesty_sentence(passing)


def test_moved_ledger_rows_behave_the_same(tmp_path: Path) -> None:
    from alpha_web._rdagent_run_files import FACTOR_SCHEMAS
    from alpha_web._rdagent_run_funnel import _ledger_factor_rows

    schema = sorted(FACTOR_SCHEMAS)[0]
    folder = tmp_path / "old-folder"
    rows = [
        {"run_id": "run-1", "schema": schema},
        {"run_id": "old-folder", "schema": schema},
        {"run_id": "run-1", "schema": "AlphaRuleTrialV1"},
        {"run_id": "other", "schema": schema},
    ]
    assert _ledger_factor_rows(rows, "run-1", folder) == rows[:2]


def test_runs_module_keeps_public_readers() -> None:
    runs = importlib.import_module("alpha_web._rdagent_runs")
    for name in ("list_runs", "read_run", "read_journey", "read_journey_figure"):
        assert callable(getattr(runs, name)), name


def test_list_runs_on_empty_store_unchanged(tmp_path: Path) -> None:
    from alpha_web._rdagent_runs import list_runs

    root = tmp_path / "runs"
    root.mkdir()
    result = list_runs(root, tmp_path / "ledger.jsonl")
    assert result.items == []
    assert result.reason == "No RD-Agent run is stored yet. Start one with: alpha rdagent run"
