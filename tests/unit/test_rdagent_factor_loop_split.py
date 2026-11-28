"""The factor-loop launcher hands its call accounting and launch checks to sibling modules."""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
LAUNCHER = WORKER / "factor_loop_launch.py"

CALLS_NAMES = ("label_calls", "round_counts", "call_split")
CHECKS_NAMES = (
    "LaunchError",
    "MAX_CALLS",
    "SETUP_HINT",
    "GATEWAY_SECRETS",
    "_inside_git",
    "validate",
)


def _launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("factor_loop_launch", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sibling(name: str) -> ModuleType:
    if str(WORKER) not in sys.path:
        sys.path.insert(0, str(WORKER))
    return importlib.import_module(name)


def _args(tmp_path: Path, *extra: str) -> argparse.Namespace:
    (tmp_path / "ledger").mkdir(exist_ok=True)
    parsed: argparse.Namespace = (
        _launcher()
        .parser()
        .parse_args(
            [
                "run",
                "--data-dir",
                str(tmp_path / "data"),
                "--run-dir",
                str(tmp_path / "run"),
                "--gateway-data-dir",
                str(tmp_path / "gateway"),
                "--trial-ledger",
                str(tmp_path / "ledger" / "trials.jsonl"),
                "--run-id",
                "test-run",
                *extra,
            ]
        )
    )
    return parsed


def test_call_accounting_lives_in_factor_loop_calls(tmp_path: Path) -> None:
    calls = _sibling("factor_loop_calls")
    for name in CALLS_NAMES:
        assert hasattr(calls, name), name
        assert getattr(calls, name).__module__ == "factor_loop_calls", name
    assert calls.call_split([])["counted_calls"] == 0
    counts = calls.round_counts(tmp_path)
    assert counts["rounds_with_trial"] == 0
    assert counts["proposals_refused"] == 0
    assert calls.label_calls([], []) == []


def test_launch_checks_live_in_factor_loop_checks(tmp_path: Path) -> None:
    checks = _sibling("factor_loop_checks")
    for name in CHECKS_NAMES:
        assert hasattr(checks, name), name
    assert checks.LaunchError.__module__ == "factor_loop_checks"
    assert checks.validate.__module__ == "factor_loop_checks"
    with pytest.raises(checks.LaunchError, match="--loop-n"):
        checks.validate(_args(tmp_path, "--loop-n", "4"), {})


def test_launcher_binds_moved_names_from_new_modules() -> None:
    launch = _launcher()
    calls = _sibling("factor_loop_calls")
    checks = _sibling("factor_loop_checks")
    for name in CALLS_NAMES:
        assert getattr(launch, name) is getattr(calls, name), name
    assert launch.LaunchError is checks.LaunchError


def test_launcher_no_longer_defines_moved_names_and_shrinks() -> None:
    tree = ast.parse(LAUNCHER.read_text())
    moved = set(CALLS_NAMES) | set(CHECKS_NAMES)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert node.name not in moved, f"{node.name} still defined in the launcher"
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        for target in targets:
            if isinstance(target, ast.Name) and target.id in moved:
                assert isinstance(value, ast.Attribute), f"{target.id} still built in the launcher"
    assert len(LAUNCHER.read_text().splitlines()) < 800


def test_new_modules_do_not_import_the_launcher() -> None:
    for name in ("factor_loop_calls.py", "factor_loop_checks.py"):
        text = (WORKER / name).read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("factor_loop_launch" not in a.name for a in node.names), name
            if isinstance(node, ast.ImportFrom):
                assert "factor_loop_launch" not in (node.module or ""), name
                assert all(a.name != "factor_loop_launch" for a in node.names), name
        assert '"factor_loop_launch"' not in text, name


def test_launcher_parser_and_launch_class_stay(tmp_path: Path) -> None:
    launch = _launcher()
    parsed = _args(tmp_path)
    assert parsed.run_id == "test-run"
    assert parsed.loop_n >= 1
    assert isinstance(launch.Launch, type)
    assert callable(launch.main)
