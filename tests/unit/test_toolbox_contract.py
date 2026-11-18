"""Every entry advertises checkable outputs and an independent reference."""

import ast
import hashlib
import json
import math
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


def _canonical(value: Any) -> Any:
    """Round every float to ten significant digits so CPU-dependent last bits cannot matter.

    Values below 1e-12 in size are zero: they are rounding residue, not results.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return value
        return 0.0 if abs(value) < 1e-12 else float(f"{value:.9e}")
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _digest(result: Any) -> str:
    return hashlib.sha256(json.dumps(_canonical(result), sort_keys=True).encode()).hexdigest()


# SHA-256 of the complete result objects from spine.tools on the same fixture, with every float
# rounded to ten significant digits (see _canonical).
BASELINE = {
    "market.attribution": "014854ca4a7c405d819c778ce4d5d664d0954ca4b82c7d2953eef91a8e7b9b03",
    "market.vol_regimes": "a01aa8ce7fd54f2f9b128991de309f6726015ad16c97f203aae02e1ae4d74621",
    "market.changepoints": "cd9da18d3cba6a753813ec28d04800e089b5caee206599e64023a0581a064427",
}


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
            parts.append("unavailable" if value is None else format(value, fmt or ""))
            if isinstance(value, (int, float)):
                parts.append(f" [{RUN}:{spec.id}.{key}]")
    diagnostics = home / "runs" / RUN / "diagnostics.json"
    diagnostics.write_text(json.dumps({"trials": {"total_trials": 1}}))
    draft = f"Quick look. {''.join(parts)}\n1 [{RUN}:total_trials]"
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
    digests = []
    for home in (tmp_path / "first", tmp_path / "second"):
        series = _series(home)
        series = replace(
            series, positions=tuple(i // 25 % 2 == 0 for i in range(len(series.dates)))
        )
        monkeypatch.setattr(inputs, "load_run", lambda home, run_id, result=series: result)
        doc = run(home, spec.id, RUN)
        assert doc["reading"] == spec.render(doc["values"])
        assert set(doc["values"]) == {output.key for output in spec.outputs}
        assert doc["elapsed_seconds"] < {"instant": 5, "seconds": 60, "minutes": 900}[spec.cost]
        digest = _digest(doc["result"])
        digests.append(digest)
        if spec.id in BASELINE:
            assert digest == BASELINE[spec.id]
        _check_reading(spec, doc, home)
        if not spec.seeded:
            break
    assert len(set(digests)) == 1


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
# (tool, always long, params) -> (SHA-256 of the result object, every fact by its old name).
LEGACY: dict[tuple[str, bool, tuple[str, ...]], tuple[str, dict[str, float | None]]] = {
    ("market.attribution", False, ()): (
        BASELINE["market.attribution"],
        {
            "market_beta": 0.48724361298425856,
            "market_alpha_annual": -0.10151191452002381,
            "market_alpha_p": 0.5022268139939561,
            "market_r_squared": 0.487322738962769,
        },
    ),
    ("market.vol_regimes", False, ()): (
        BASELINE["market.vol_regimes"],
        {
            "regime_turbulent_share_of_return": None,
            "regime_turbulent_share_of_time": 0.49642346208869814,
        },
    ),
    ("market.changepoints", False, ()): (BASELINE["market.changepoints"], {"changepoint_count": 0}),
    ("market.changepoints", False, ("on=equity",)): (
        "257a126f37013d3d5ef62cbb229a1f7d533c6487ec2da844c98acfdde7517bc7",
        {"changepoint_count": 7},
    ),
    ("market.attribution", True, ()): (
        "dfa1bd3e78dcc6d8f6202f53ce9b0a4e9390e18b25d357b81cec8dac6411089c",
        {
            "market_beta": 1.0,
            "market_alpha_annual": -7.716808962665578e-16,
            "market_alpha_p": 0.4841254415663766,
            "market_r_squared": 1.0,
        },
    ),
    ("market.vol_regimes", True, ()): (
        "734987b6cd208f356f05c16a198d205f7700117f72c6d3c8e03b1e429a70e58a",
        {
            "regime_turbulent_share_of_return": -0.3868048089390445,
            "regime_turbulent_share_of_time": 0.49642346208869814,
        },
    ),
    ("market.changepoints", True, ()): (
        "9c244b4404f82e32caa8acd4094e90db580c1d27ccc82286574eae981698b684",
        {"changepoint_count": 1},
    ),
    ("market.changepoints", True, ("on=equity",)): (
        "2219be01b08e444a8f0f48bdd4a810901d7e493d268422c708776d4fbca54d58",
        {"changepoint_count": 8},
    ),
}


@pytest.mark.parametrize("case", LEGACY, ids=lambda case: f"{case[0]}-long{case[1]}-{case[2]}")
def test_numbers_match_the_pre_registry_code(
    case: tuple[str, bool, tuple[str, ...]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, always_long, params = case
    digest, facts = LEGACY[case]
    series = _series(tmp_path, always_long=always_long)
    positions = tuple(always_long or i // 25 % 2 == 0 for i in range(len(series.dates)))
    series = replace(series, positions=positions)
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    doc = run(tmp_path, tool, RUN, list(params))
    assert _digest(doc["result"]) == digest
    by_old_name = {
        output.legacy_metric: doc["values"][output.key]
        for spec in SPECS
        if spec.id == tool
        for output in spec.outputs
    }
    assert by_old_name == {
        name: None if fact is None else pytest.approx(fact, rel=1e-9, abs=1e-12)
        for name, fact in facts.items()
    }
