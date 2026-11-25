"""The literature helpers live in `alpha_cli.literature_call`, which imports no command module;
`library_papers_cmds` no longer reaches into `research_cmds` or `local_pdf_cmds`."""

from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import library_papers_cmds
from alpha_cli.main import app
from alpha_core import DataError

HELPERS = ("_run_literature_worker", "_read_owner_pdf", "_validated_extraction")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names.add(base)
            # `from alpha_cli import research_cmds` names the module in the alias.
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _is_command_module(name: str) -> bool:
    last = name.rsplit(".", 1)[-1]
    return (
        last.endswith("_cmds")
        or last == "main"
        or last.startswith("_research_cmd")
        or "_cmds." in name
    )


def _literature_call_path() -> Path:
    spec = importlib.util.find_spec("alpha_cli.literature_call")
    assert spec is not None and spec.origin is not None, "alpha_cli.literature_call is missing"
    return Path(spec.origin)


def test_literature_call_holds_the_three_helpers() -> None:
    module = importlib.import_module("alpha_cli.literature_call")
    for name in HELPERS:
        assert callable(getattr(module, name, None)), name


def test_literature_call_imports_no_command_module() -> None:
    imported = _imported_modules(_literature_call_path())
    offenders = sorted(name for name in imported if _is_command_module(name))
    assert offenders == []


def test_library_papers_cmds_imports_neither_research_nor_local_pdf_cmds() -> None:
    assert library_papers_cmds.__file__ is not None
    imported = _imported_modules(Path(library_papers_cmds.__file__))
    offenders = sorted(
        name for name in imported if name.rsplit(".", 1)[-1] in {"research_cmds", "local_pdf_cmds"}
    )
    assert offenders == []
    assert "alpha_cli.literature_call" in imported


def test_extraction_check_in_literature_call_rejects_a_foreign_schema() -> None:
    module = importlib.import_module("alpha_cli.literature_call")
    with pytest.raises(DataError):
        module._validated_extraction({"schema": "SomethingElse"}, source_sha256="0" * 64)


def test_import_pdf_help_still_works(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["library", "import-pdf", "--help"], env={"ALPHA_DATA_DIR": str(tmp_path)}
    )
    assert result.exit_code == 0, result.output
    assert "FILE" in result.output


def test_import_pdf_of_a_missing_file_fails_without_calling_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def worker(argv: list[str], **_: Any) -> dict[str, object]:
        calls.append(argv)
        return {}

    monkeypatch.setattr(library_papers_cmds, "_run_literature_worker", worker)
    missing = tmp_path / "absent.pdf"
    result = CliRunner().invoke(
        app,
        ["library", "import-pdf", str(missing)],
        env={"ALPHA_DATA_DIR": str(tmp_path / "home")},
    )
    assert result.exit_code != 0
    assert calls == []
