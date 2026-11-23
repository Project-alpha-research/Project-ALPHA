"""`alpha tool run` text: short numbers, money with a unit, label meanings, "the model"."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha_cli.tool_cmds import _shown, _text
from alpha_cli.toolbox.registry import get


def test_numbers_are_rounded_and_money_has_a_unit() -> None:
    assert _shown(0.123456789012, "ratio") == "0.1235"
    assert _shown(1234.5678, "currency") == "$1,234.57"
    assert _shown(-5.0, "currency") == "-$5.00"
    assert _shown(3, "ratio") == 3
    assert _shown(None, "ratio") is None


def _output(tool: str, run_id: str) -> dict[str, object]:
    spec = get(tool)
    return {
        "tool": tool,
        "run_id": run_id,
        "labels": ["ad-hoc", "exploratory"],
        "reading": "The rule gained.",
        "facts": [
            {"metric": f"{tool}.{o.key}", "value": 0.123456789, "reason": None}
            for o in spec.outputs
        ],
        "result": {},
        "basis": "basis",
        "file": "diagnostics/x.json",
    }


def test_labels_print_with_their_meaning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    text = _text(_output("costs.break_even", "0123456789abcdef"))
    assert "ad-hoc: Run on its own" in text
    assert "exploratory: Exploratory test" in text
    assert "0.1235" in text and "0.123456789" not in text
    assert "The rule gained." in text


def test_a_check_on_a_model_run_says_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    run_id = "0123456789abcdef"
    rdir = tmp_path / "runs" / run_id
    rdir.mkdir(parents=True)
    from alpha_cli.ml_reading import COMMAND

    (rdir / "manifest.json").write_text(json.dumps({"command": COMMAND}))
    text = _text(_output("costs.break_even", run_id))
    assert "The model gained." in text and "The rule" not in text


def test_a_fraction_prints_as_a_percent() -> None:
    assert _shown(0.12345, "fraction") == "12.35%"
    assert _shown(-0.5, "fraction") == "-50%"


@pytest.mark.parametrize("value", [1.5e-7, -3.2e-9, 2.5e8, 1.23456e12, 0.00001234])
@pytest.mark.parametrize("unit", ["ratio", "fraction", "bps", "count"])
def test_no_number_prints_in_scientific_notation(value: float, unit: str) -> None:
    shown = str(_shown(value, unit))
    assert "e" not in shown.lower()
    assert shown.strip("-").replace(".", "").replace("%", "").isdigit()


def test_a_cost_sweep_on_a_model_run_says_where_its_no_cost_figure_comes_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    run_id = "0123456789abcdef"
    rdir = tmp_path / "runs" / run_id
    rdir.mkdir(parents=True)
    from alpha_cli.ml_reading import COMMAND

    (rdir / "manifest.json").write_text(json.dumps({"command": COMMAND}))
    said = "from the account's fills with costs added back; `alpha report` uses the planned weights"
    assert said in _text(_output("cost_realism.cost_sweep", run_id))
    assert said not in _text(_output("costs.break_even", run_id))
    (rdir / "manifest.json").write_text(json.dumps({"command": "validate"}))
    assert said not in _text(_output("cost_realism.cost_sweep", run_id))
