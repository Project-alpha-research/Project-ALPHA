"""The Kronos report helpers live in alpha_cli._monte_carlo_kronos_report (pure move)."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import alpha_cli.monte_carlo_cmds as monte_carlo_cmds
from alpha_core import DataError

MOVED = ("_calibration_assessment", "_kronos_report", "_same_model", "_kronos_caveats")
NEW_MODULE = "alpha_cli._monte_carlo_kronos_report"


def _new() -> ModuleType:
    return importlib.import_module(NEW_MODULE)


def _cmds_tree() -> ast.Module:
    source = Path(monte_carlo_cmds.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def _manifest(**overrides: float | int) -> dict[str, object]:
    summary: dict[str, float | int] = {
        "n_origins": 20,
        "skill_vs_rw": 0.1,
        "skill_vs_bootstrap": 0.05,
        "coverage50": 0.5,
        "coverage80": 0.8,
        "coverage90": 0.9,
    }
    summary.update(overrides)
    return {"summary_post_cutoff": summary}


def test_report_helpers_live_in_kronos_report_module() -> None:
    module = _new()
    for name in MOVED:
        function = getattr(module, name)
        assert callable(function)
        assert function.__module__ == NEW_MODULE
        assert function.__name__ == name


def test_monte_carlo_cmds_imports_helpers_instead_of_defining_them() -> None:
    tree = _cmds_tree()
    defined = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for name in MOVED:
        assert name not in defined, f"{name} is still defined in monte_carlo_cmds.py"
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == NEW_MODULE:
            imported.update(alias.name for alias in node.names)
    for name in MOVED:
        assert name in imported, f"monte_carlo_cmds.py does not import {name} from {NEW_MODULE}"


def test_command_and_cut_helper_stay_in_monte_carlo_cmds() -> None:
    tree = _cmds_tree()
    defined = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "kronos" in defined
    assert "_source_as_of" in defined
    assert "_project_forecast_path" in defined
    assert "_causal_regime_states" in defined


def test_calibration_assessment_from_new_module_keeps_policy() -> None:
    assess = _new()._calibration_assessment
    assert assess(_manifest())["status"] == "adequate"
    weak = assess(_manifest(coverage80=0.95))
    assert weak["status"] == "weak_or_insufficient"
    assert "70%-90%" in str(weak["reasons"])
    sparse = assess(_manifest(n_origins=4, skill_vs_rw=0.0, skill_vs_bootstrap=-0.1))
    assert len(sparse["reasons"]) == 3
    missing = assess({})
    assert missing == {
        "status": "weak_or_insufficient",
        "reasons": ["no post-cutoff forecast origins"],
        "summary": None,
    }


def test_same_model_from_new_module_rejects_a_different_generator() -> None:
    same_model = _new()._same_model
    model = {
        "model_id": "fake",
        "model_revision": "r1",
        "tokenizer_id": "tok",
        "tokenizer_revision": "t1",
        "device": "cpu",
    }
    assert same_model({"model": dict(model)}, dict(model)) is None
    with pytest.raises(DataError, match="no pinned model provenance"):
        same_model({}, dict(model))
    with pytest.raises(DataError, match="device"):
        same_model({"model": dict(model)}, {**model, "device": "cuda"})


def test_kronos_caveats_from_new_module_flag_warnings() -> None:
    kronos_caveats = _new()._kronos_caveats
    adequate = {"status": "adequate", "reasons": []}
    caveats, warning = kronos_caveats(
        {"model_id": "fake", "determinism": "exact"}, {"overlap": False}, adequate
    )
    assert caveats == ["Kronos pretraining overlap remains permanently disclosed when present"]
    assert warning is False

    caveats, warning = kronos_caveats(
        {
            "model_id": "real",
            "determinism": "best_effort",
            "device": "cuda",
            "model_revision": "main",
            "tokenizer_revision": "abc123",
        },
        {"overlap": False},
        {"status": "weak_or_insufficient", "reasons": ["only 3 post-cutoff origins"]},
    )
    assert warning is True
    assert "cuda inference is best-effort rather than bit-exact" in caveats
    assert "model revision is a mutable branch name rather than an immutable commit" in caveats
    assert not any(c.startswith("tokenizer revision") for c in caveats)
    assert caveats[-1] == "only 3 post-cutoff origins"


def test_kronos_report_from_new_module_keeps_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli import _mc_reading

    monkeypatch.setattr(_mc_reading, "built_from_sentence", lambda _info: "Built from run `v1`.")
    report = _new()._kronos_report(
        {"run": "v1"},
        "eval-9",
        8,
        SimpleNamespace(caveats=("first caveat", "second caveat")),
        (3, 2),
    )
    assert report.startswith("# Kronos synthetic-OHLCV Monte Carlo report\n\n")
    assert "Built from run `v1`. Evaluation run `eval-9`. Paths: 8.\n\n" in report
    assert "Caveats: first caveat; second caveat. Raw model values" in report
    assert "3 high/low enclosure adjustments were recorded." in report
    assert "negative volume on 2 simulated bars" in report
    assert report.endswith("Prices were not changed.\n")
