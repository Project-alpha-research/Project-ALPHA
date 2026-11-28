"""The screening code of rdagent_factor_eval.py lives in _factor_eval_screen.py (a pure move)."""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]

MOVED = (
    "_keep_first_costs",
    "source_columns",
    "reads_funding",
    "funding_eligibility",
    "_factor_eligibility",
    "_screen_factors",
    "_spread_or_error",
    "_eligibility",
)


def screen_module() -> ModuleType:
    return importlib.import_module("alpha_cli._factor_eval_screen")


def test_moved_names_live_in_screen_module() -> None:
    module = screen_module()
    for name in MOVED:
        value = getattr(module, name)
        assert callable(value), name
        assert value.__module__ == "alpha_cli._factor_eval_screen", name


def test_screen_module_reads_literal_selectors() -> None:
    module = screen_module()
    code = b'# $ignored\nx = df["$close"] / df.get("$funding_rate")\n"$standalone"\n'
    assert module.source_columns(code) == ["$close", "$funding_rate"]


def test_screen_module_funding_rule() -> None:
    module = screen_module()
    assert module.reads_funding(b'v = df["$funding_rate"]') is True
    assert module.reads_funding(b'v = df["$close"]  # $funding_rate') is False


def test_orchestrator_keeps_its_names() -> None:
    ev = importlib.import_module("alpha_cli.rdagent_factor_eval")
    for name in ("evaluate", "main", "shown", "record_shortlist", "_deflate", "_report", "_inputs"):
        assert callable(getattr(ev, name)), name
        assert getattr(ev, name).__module__ == "alpha_cli.rdagent_factor_eval", name
    for name in ("spread", "spread_at_clock", "RESERVED_DAY", "RESERVED_START"):
        assert hasattr(ev, name), name


def test_rdagent_help_still_prints() -> None:
    result = subprocess.run(
        ["uv", "run", "alpha", "rdagent", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Usage" in result.stdout
