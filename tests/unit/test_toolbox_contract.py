"""Every entry advertises checkable outputs and an independent reference."""

import ast
import hashlib
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

# SHA-256 of the complete result objects from spine.tools on the same fixture.
BASELINE = {
    "market.attribution": "a3ea82ed65e6b0fabad2ecf0ae381abcd95f1a382376a297ab610c2c282009c7",
    "market.vol_regimes": "93a13b7caab05b950340b5aa64fa6fc60f6f9a441255726707fa0b3282e79eec",
    "market.changepoints": "7fc06246b93857dde04b212435d7ce19b0467ea8218e629778f5975fb4c9638a",
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
        digest = hashlib.sha256(json.dumps(doc["result"], sort_keys=True).encode()).hexdigest()
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
LEGACY = {
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
        "70d42ca85d4870ac60ae045f26abf28ecdd5701a3f4b987a5d2d56e0be760f15",
        {"changepoint_count": 7},
    ),
    ("market.attribution", True, ()): (
        "6d1ca4a98ba14c4b0dde1486969689dd56465ef937bb024089fbf5aaf2c11fde",
        {
            "market_beta": 1.0,
            "market_alpha_annual": -7.716808962665578e-16,
            "market_alpha_p": 0.4841254415663766,
            "market_r_squared": 1.0,
        },
    ),
    ("market.vol_regimes", True, ()): (
        "16adb39da2d368b4456a14a6dd5be6dd1db5d9f5aafac626f8e13a6c5863e88b",
        {
            "regime_turbulent_share_of_return": -0.3868048089390445,
            "regime_turbulent_share_of_time": 0.49642346208869814,
        },
    ),
    ("market.changepoints", True, ()): (
        "aa1db5ab6663432aea865c87d677f6d9a865d36abcfb666abff19bb0a3d0b0c5",
        {"changepoint_count": 1},
    ),
    ("market.changepoints", True, ("on=equity",)): (
        "be3cacd479d9989bce4af3f6ccdab28c7a425310b3803ba05031ab0e8a182909",
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
    assert hashlib.sha256(json.dumps(doc["result"], sort_keys=True).encode()).hexdigest() == digest
    by_old_name = {
        output.legacy_metric: doc["values"][output.key]
        for spec in SPECS
        if spec.id == tool
        for output in spec.outputs
    }
    assert by_old_name == facts  # exact equality, no tolerance
