"""ml_contract.py hands the result-bundle validation to ml_result_validation.py (pure move)."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO = Path(__file__).parents[2]
PKG = REPO / "apps/alpha-cli/src/alpha_cli"
CONTRACT = PKG / "ml_contract.py"
NEW = PKG / "ml_result_validation.py"

MOVED = [
    "_RESULT_V2_FIELDS",
    "_PREDICTION_SORT",
    "_expected_prediction_schema",
    "_validate_result_payload",
    "_expected_ensemble_diagnostic_schema",
    "_validate_ensemble_diagnostics",
    "_validate_predictions",
    "validate_result_bundle",
]

IMPORTERS = ["_ml_replay.py", "ml_cmds.py", "ml_compare.py", "ml_replay_signal.py"]


def _top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
    return found


def test_moved_names_live_in_ml_result_validation() -> None:
    assert NEW.is_file()
    defined = _top_level_names(NEW)
    missing = [name for name in MOVED if name not in defined]
    assert not missing, f"not defined in ml_result_validation.py: {missing}"
    module = importlib.import_module("alpha_cli.ml_result_validation")
    for name in MOVED:
        assert hasattr(module, name)


def test_ml_contract_no_longer_defines_moved_names() -> None:
    defined = _top_level_names(CONTRACT)
    still = [name for name in MOVED if name in defined]
    assert not still, f"still defined in ml_contract.py: {still}"
    contract = importlib.import_module("alpha_cli.ml_contract")
    assert not hasattr(contract, "validate_result_bundle"), "no re-export shim"


def test_ml_contract_is_under_800_lines() -> None:
    lines = len(CONTRACT.read_text(encoding="utf-8").splitlines())
    assert lines < 800, f"ml_contract.py has {lines} lines"


def test_importers_take_validate_result_bundle_from_new_module() -> None:
    for filename in IMPORTERS:
        modules = _imported_modules(PKG / filename)
        assert "alpha_cli.ml_contract.validate_result_bundle" not in modules, filename
    assert "alpha_cli.ml_result_validation.validate_result_bundle" in _imported_modules(
        PKG / "ml_replay_signal.py"
    )


def test_validate_result_bundle_from_new_module_rejects_empty_exchange(tmp_path: Path) -> None:
    from alpha_cli.ml_contract import MLContractError

    module = importlib.import_module("alpha_cli.ml_result_validation")
    with pytest.raises(MLContractError):
        module.validate_result_bundle(tmp_path)


def test_ml_contract_never_imports_ml_result_validation() -> None:
    modules = _imported_modules(CONTRACT)
    assert not any(m.startswith("alpha_cli.ml_result_validation") for m in modules)


def test_ml_contract_keeps_constants_and_request_checks() -> None:
    from alpha_cli.ml_contract import (  # noqa: F401
        MIN_ALIGNED_SESSIONS,
        MIN_SYMBOLS,
        PREDICTION_COLUMNS,
        MLContractError,
        ValidatedRequest,
        ValidatedResult,
        canonical_json_bytes,
        sha256_file,
        validate_request_bundle,
    )

    assert MIN_SYMBOLS > 0
    assert MIN_ALIGNED_SESSIONS > 0


def test_ml_help_still_lists_commands() -> None:
    from alpha_cli.main import app

    result = CliRunner().invoke(app, ["ml", "--help"])
    assert result.exit_code == 0, result.output
    for command in ("import", "replay", "compare", "train", "evaluate"):
        assert command in result.output
