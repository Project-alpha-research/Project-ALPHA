"""`alpha ml capabilities` prints plain lines, not raw dictionaries; --json stays the same."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import ml_cmds
from alpha_cli.main import app
from alpha_cli.ml_contract import tabular_model_names


@pytest.fixture
def worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A worker folder with no installed entrypoint: the command reports missing dependencies."""
    root = tmp_path / "worker"
    root.mkdir()
    monkeypatch.setattr(ml_cmds, "_worker_project", lambda _project: (root, root / "uv.lock"))
    return root


def _lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.strip()]


def test_capabilities_text_is_one_plain_line_per_item(worker: Path) -> None:
    result = CliRunner().invoke(app, ["ml", "capabilities", "--worker-project", str(worker)])
    assert result.exit_code == 0, result.output
    for raw in ("{", "}", "[", "]", "'name'", '"name"'):
        assert raw not in result.output
    lines = _lines(result.output)
    for name in tabular_model_names():
        matching = [line for line in lines if re.search(rf"\b{re.escape(name)}\b", line)]
        assert len(matching) == 1, (name, lines)
    recipe_lines = [line for line in lines if "alpha158" in line]
    assert len(recipe_lines) == 3, lines


def test_capabilities_json_output_keeps_its_contract(worker: Path) -> None:
    result = CliRunner().invoke(
        app, ["ml", "capabilities", "--worker-project", str(worker), "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["qlib_version"] is None
    assert [item["version"] for item in payload["feature_recipes"]] == [1, 2, 3]
    assert all(item["name"] == "alpha158" for item in payload["feature_recipes"])
    assert [item["name"] for item in payload["backends"]] == list(tabular_model_names())
    assert all(item["status"] == "missing_dependency" for item in payload["backends"])
