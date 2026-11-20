"""The descriptive reference read is used only by descriptive toolbox entries."""

import ast
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.toolbox import runner
from alpha_cli.toolbox.contract import REFERENCE_LABEL, Result, ToolSpec
from alpha_cli.toolbox.families.context import PUBLISHED_FACTORS
from alpha_cli.toolbox.families.market import ATTRIBUTION
from tests.unit.published_factors_support import planted_home
from tests.unit.test_spine_tools import RUN

ROOT = Path(__file__).resolve().parents[2]
HELPER = "read_reference_for_period"
PACKAGE = "alpha_cli.toolbox"
MODULE = f"{PACKAGE}.reference"
# The one file that may name the helper; inputs.py may import only the cache-key fingerprint.
CALLERS = {"apps/alpha-cli/src/alpha_cli/toolbox/families/context.py"}
FINGERPRINT_ONLY = {"apps/alpha-cli/src/alpha_cli/toolbox/inputs.py"}
FINGERPRINT_IMPORT = f"from {MODULE} import vintage_fingerprint\n"
HOME = "apps/alpha-cli/src/alpha_cli/toolbox/reference.py"


def _sources() -> list[Path]:
    roots = [*ROOT.glob("packages/*/src"), *ROOT.glob("apps/*/src"), ROOT / "workers"]
    return [p for root in roots for p in root.rglob("*.py") if ".venv" not in p.parts]


def _imported(tree: ast.AST) -> list[tuple[str, str]]:
    """(module, imported name) for every import of the reference module, however spelled."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, "*") for a in node.names if a.name.startswith(MODULE)]
        elif isinstance(node, ast.ImportFrom) and node.module == PACKAGE:
            found += [(PACKAGE, a.name) for a in node.names if a.name in {"reference", "*"}]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(MODULE):
            found += [(MODULE, a.name) for a in node.names]
    return found


def misuse(rel: str, text: str) -> list[str]:
    """Why a source file breaks the separation; empty when it does not."""
    if rel == HOME:
        return []
    found: list[str] = []
    rest = text.replace(FINGERPRINT_IMPORT, "") if rel in FINGERPRINT_ONLY else text
    if rel not in CALLERS and HELPER in rest:
        found.append(f"{rel} names {HELPER}")
    if rel not in CALLERS and "toolbox.reference" in rest:
        found.append(f"{rel} names {MODULE}")
    for module, name in _imported(ast.parse(text)):
        allowed = rel in CALLERS or (rel in FINGERPRINT_ONLY and name == "vintage_fingerprint")
        if not allowed:
            found.append(f"{rel} imports {module}:{name}")
    return found


def test_only_descriptive_entries_use_the_reference_read() -> None:
    found = [m for p in _sources() for m in misuse(p.relative_to(ROOT).as_posix(), p.read_text())]
    assert not found, "\n".join(found)


@pytest.mark.parametrize(
    "text",
    [
        "from alpha_cli.toolbox.reference import read_reference_for_period\n",
        "from alpha_cli.toolbox import reference as r\nr.read_reference_for_period\n",
        "from alpha_cli.toolbox import reference as r\n",
        "import alpha_cli.toolbox.reference as quiet\n",
        "import importlib\nimportlib.import_module('alpha_cli.toolbox.reference')\n",
        "from alpha_cli.toolbox import *\n",
    ],
)
def test_the_guard_fires_on_a_strategy_module(text: str) -> None:
    for rel in (
        "packages/alpha-strategies/src/alpha_strategies/fixture.py",
        "apps/alpha-cli/src/alpha_cli/toolbox/inputs.py",
    ):
        assert misuse(rel, text), (rel, text)


def test_inputs_may_import_only_the_fingerprint() -> None:
    assert not misuse("apps/alpha-cli/src/alpha_cli/toolbox/inputs.py", FINGERPRINT_IMPORT)


def test_the_guard_sees_the_real_files() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in _sources()}
    assert HOME in names and names >= CALLERS | FINGERPRINT_ONLY
    assert any(n.startswith("workers/") for n in names)
    assert any("alpha-strategies" in n for n in names)


@pytest.mark.parametrize(
    "change", [{"look": "test"}, {"time_safety": "causal"}, {"kind": "control"}]
)
def test_reference_input_is_for_descriptive_entries_only(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="descriptive"):
        replace(PUBLISHED_FACTORS, **change)
    with pytest.raises(ValueError, match="descriptive"):
        replace(ATTRIBUTION, needs=(*ATTRIBUTION.needs, "reference_factors"), **change)


def test_results_from_the_reference_input_are_labelled_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bare(*_: object) -> Result:
        return Result({"explained_share": 0.5, "sentence": "x"}, {})

    spec: ToolSpec = replace(PUBLISHED_FACTORS, compute=bare)
    monkeypatch.setattr(runner, "get", lambda _: spec)
    planted_home(tmp_path, weights={"Mom12m": 0.5})
    doc = runner.run(tmp_path, spec.id, RUN)
    assert REFERENCE_LABEL in doc["labels"]
