"""Every entry advertises checkable outputs and an independent reference."""

import ast
import json
from dataclasses import replace
from pathlib import Path
from string import Formatter
from typing import Any

import pytest

from alpha_cli.results_cmds import fact_lookup
from alpha_cli.spine.check import check_text
from alpha_cli.toolbox import inputs
from alpha_cli.toolbox.contract import Result, ToolSpec
from alpha_cli.toolbox.gates import GATES
from alpha_cli.toolbox.registry import SPECS
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN, _series

# The complete result objects printed by origin/main's spine/tools.py (commit 705ab13b) on the same
# fixture, kept as JSON (their SHA-256 digests matched the previously pinned ones). Floats are
# compared to 1e-9 relative, not bit for bit: the regime and regression fits are iterative and
# end in different last digits on different CPUs. Everything else is compared exactly.
REFERENCE: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "toolbox_results.json").read_text()
)
REL, ABS = 1e-9, 1e-12
# Tools the registry-entry test checks against the reference, by their default-case key.
BASELINE = {
    tool: f"{tool}|False|"
    for tool in ("market.attribution", "market.vol_regimes", "market.changepoints")
}


def _assert_close(actual: Any, expected: Any, where: str = "result") -> None:
    """Same shape, same ints, strings and None; floats equal within REL and ABS."""
    if isinstance(expected, float):
        assert isinstance(actual, float), where
        assert actual == pytest.approx(expected, rel=REL, abs=ABS, nan_ok=True), where
    elif isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys(), where
        for key, value in expected.items():
            _assert_close(actual[key], value, f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), where
        for index, value in enumerate(expected):
            _assert_close(actual[index], value, f"{where}[{index}]")
    else:
        assert type(actual) is type(expected) and actual == expected, where


def _test_exists(reference: str) -> bool:
    path, name = reference.split("::")
    tree = ast.parse((Path(__file__).parents[2] / path).read_text())
    return any(isinstance(node, ast.FunctionDef) and node.name == name for node in tree.body)


def _check_reading(spec: ToolSpec, doc: dict[str, Any], home: Path) -> None:
    """Tag the numeric fields as a report author would and verify against the stored files."""
    parts = []
    for literal, key, fmt, _ in Formatter().parse(spec.reading):
        parts.append(literal)
        if key is not None:
            value = doc["values"][key]
            text = "unavailable" if value is None else format(value, fmt or "")
            # Published-factor sentences carry per-factor and search numbers that are stored in
            # the result details, not as separate facts: their text is quoted as code.
            parts.append(
                f"`{text}`"
                if spec.id == "context.published_factors" and key in ("sentence",)
                else text
            )
            if isinstance(value, (int, float)):
                parts.append(f" [{RUN}:{spec.id}.{key}]")
    diagnostics = home / "runs" / RUN / "diagnostics.json"
    diagnostics.write_text(json.dumps({"trials": {"total_trials": 1}}))
    draft = f"Quick look. Reserved period seen. {''.join(parts)}\n1 [{RUN}:total_trials]"
    checked = check_text(draft, fact_lookup(home))
    assert checked["ok"], checked


@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.id)
def test_registry_entry(spec: ToolSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert spec.outputs and all(output.gloss.strip() for output in spec.outputs)
    assert _test_exists(spec.reference)
    if spec.time_safety != "order_free":
        assert spec.poison_test and _test_exists(spec.poison_test)
    if spec.look == "search":
        assert spec.evaluations is not None
    results = []
    for home in (tmp_path / "first", tmp_path / "second"):
        series = _series(home)
        series = replace(
            series, positions=tuple(i // 25 % 2 == 0 for i in range(len(series.dates)))
        )
        monkeypatch.setattr(inputs, "load_run", lambda home, run_id, result=series: result)
        if "run_rerun" in spec.needs:
            from tests.unit.parameter_robustness_support import synthetic_series

            rerun = synthetic_series(home)
            monkeypatch.setattr(inputs, "load_rerun", lambda home, target, result=rerun: result)
        if spec.id == "context.published_factors":
            from tests.unit.published_factors_support import planted_home

            planted_home(home, weights={"Mom12m": 0.5})
        elif set(spec.needs) & inputs.STORED_FILES.keys():
            from tests.unit.test_toolbox_resampling_checks import TOOLS, prepare_sample
            from tests.unit.test_toolbox_run_level_checks import stored_run

            if spec.id in TOOLS:
                prepare_sample(home)
            else:
                stored_run(home, spec.id)
        doc = run(home, spec.id, RUN)
        assert doc["reading"] == spec.render(doc["values"])
        assert set(doc["values"]) == {output.key for output in spec.outputs}
        assert doc["elapsed_seconds"] < {"instant": 5, "seconds": 60, "minutes": 900}[spec.cost]
        results.append(doc["result"])
        pinned = {**BASELINE, "context.published_factors": "context.published_factors|planted|"}
        if spec.id in pinned:
            _assert_close(doc["result"], REFERENCE[pinned[spec.id]], spec.id)
        _check_reading(spec, doc, home)
        if not spec.seeded:
            break
    for later in results[1:]:
        _assert_close(later, results[0])


def test_gate_freeze_and_contract_guards() -> None:
    assert GATES == ()
    with pytest.raises(ValueError, match="gate"):
        replace(SPECS[0], kind="gate")
    with pytest.raises(ValueError, match="evaluations"):
        replace(SPECS[0], look="search")
    with pytest.raises(ValueError, match="reason"):
        Result(values={"beta": None}, reasons={})
    with pytest.raises(ValueError, match="reading"):
        replace(SPECS[0], reading="{unstored}")


def test_describe_prints_a_readable_card() -> None:
    from typer.testing import CliRunner

    from alpha_cli.tool_cmds import tool_app

    card = CliRunner().invoke(tool_app, ["describe", "market.attribution"])
    assert card.exit_code == 0
    assert card.stdout.startswith("market.attribution")
    assert "benchmark" in card.stdout and "Market beta" in card.stdout
    assert SPECS[0].caveats[0] in card.stdout


# Values printed by origin/main's spine/tools.py (commit 705ab13b) on the same synthetic runs:
# (tool, always long, params) -> (reference key, every fact by its old name).
LEGACY: dict[tuple[str, bool, tuple[str, ...]], tuple[str, dict[str, float | None]]] = {
    ("market.attribution", False, ()): (
        "market.attribution|False|",
        {
            "market_beta": 0.48724361298425856,
            "market_alpha_annual": -0.10151191452002381,
            "market_alpha_p": 0.5022268139939561,
            "market_r_squared": 0.487322738962769,
        },
    ),
    ("market.vol_regimes", False, ()): (
        "market.vol_regimes|False|",
        {
            "regime_turbulent_share_of_return": None,
            "regime_turbulent_share_of_time": 0.49642346208869814,
        },
    ),
    ("market.changepoints", False, ()): ("market.changepoints|False|", {"changepoint_count": 0}),
    ("market.changepoints", False, ("on=equity",)): (
        "market.changepoints|False|on=equity",
        {"changepoint_count": 7},
    ),
    ("market.attribution", True, ()): (
        "market.attribution|True|",
        {
            "market_beta": 1.0,
            "market_alpha_annual": -7.716808962665578e-16,
            "market_alpha_p": 0.4841254415663766,
            "market_r_squared": 1.0,
        },
    ),
    ("market.vol_regimes", True, ()): (
        "market.vol_regimes|True|",
        {
            "regime_turbulent_share_of_return": -0.3868048089390445,
            "regime_turbulent_share_of_time": 0.49642346208869814,
        },
    ),
    ("market.changepoints", True, ()): (
        "market.changepoints|True|",
        {"changepoint_count": 1},
    ),
    ("market.changepoints", True, ("on=equity",)): (
        "market.changepoints|True|on=equity",
        {"changepoint_count": 8},
    ),
}


@pytest.mark.parametrize("case", LEGACY, ids=lambda case: f"{case[0]}-long{case[1]}-{case[2]}")
def test_numbers_match_the_pre_registry_code(
    case: tuple[str, bool, tuple[str, ...]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, always_long, params = case
    key, facts = LEGACY[case]
    series = _series(tmp_path, always_long=always_long)
    positions = tuple(always_long or i // 25 % 2 == 0 for i in range(len(series.dates)))
    series = replace(series, positions=positions)
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    doc = run(tmp_path, tool, RUN, list(params))
    _assert_close(doc["result"], REFERENCE[key], key)
    by_old_name = {
        output.legacy_metric: doc["values"][output.key]
        for spec in SPECS
        if spec.id == tool
        for output in spec.outputs
    }
    assert by_old_name == {
        name: None if fact is None else pytest.approx(fact, rel=REL, abs=ABS)
        for name, fact in facts.items()
    }
