"""A long command prints a progress line every N seconds; a short one stays quiet (M112)."""

from __future__ import annotations

import time

import pytest

from alpha_cli import _progress


def test_a_long_run_prints_a_line_every_interval(capsys: pytest.CaptureFixture[str]) -> None:
    with _progress.heartbeat("Monte Carlo", every=0.05):
        time.sleep(0.28)
    lines = [line for line in capsys.readouterr().err.splitlines() if line]
    assert len(lines) >= 3
    assert all(line.startswith("Monte Carlo: still running") for line in lines)


def test_a_short_run_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    with _progress.heartbeat("Monte Carlo", every=5.0):
        pass
    assert capsys.readouterr().err == ""


def test_the_decorator_keeps_the_command_signature() -> None:
    import inspect

    from alpha_cli.forecast_cmds import evaluate
    from alpha_cli.monte_carlo_cmds import classical

    assert "from_run" in inspect.signature(classical).parameters
    assert inspect.signature(evaluate).parameters
