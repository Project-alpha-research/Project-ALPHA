"""The RD-Agent run reader's words and file helpers live in their own modules."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

WORDS = (
    "STATUS_SENTENCES",
    "REFUSED_STATUSES",
    "SCREENED",
    "SPREAD_CHECKED",
    "FUNNEL",
    "SCREEN",
    "SPREAD",
    "REPLAY",
    "DEFLATION",
    "UNIVERSE",
    "CACHE",
    "status_sentence",
)
FILES = (
    "MISSING",
    "RECEIPT_SCHEMA",
    "FACTOR_SCHEMAS",
    "MAX_FILE_BYTES",
    "TEXT_CHUNK",
    "_clean",
    "_text",
    "_get",
    "counted",
    "fact",
    "project",
    "_object",
    "_record_path",
    "_read",
    "_json",
    "_lines",
    "_stamp",
)


def _defined_names(module_name: str) -> set[str]:
    module = importlib.import_module(module_name)
    source_file = module.__file__
    assert source_file is not None
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
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


def test_run_words_module_holds_status_names() -> None:
    words = importlib.import_module("alpha_web._rdagent_run_words")
    for name in WORDS:
        assert hasattr(words, name), name
    assert WORDS and set(WORDS) <= _defined_names("alpha_web._rdagent_run_words")
    assert frozenset({"refused_closed_family", "no_admissible_idea"}) == words.REFUSED_STATUSES
    assert words.status_sentence("refused_closed_family", None)
    reason = next(iter(words.STATUS_SENTENCES))
    assert words.status_sentence("FAILED", reason) == words.STATUS_SENTENCES[reason]
    with pytest.raises(ValueError):
        words.status_sentence("NEW_UNMAPPED_STATUS", None)


def test_run_files_module_holds_record_helpers() -> None:
    files = importlib.import_module("alpha_web._rdagent_run_files")
    for name in FILES:
        assert hasattr(files, name), name
    assert set(FILES) <= _defined_names("alpha_web._rdagent_run_files")


def test_record_path_refuses_links_from_new_module(tmp_path: Path) -> None:
    files = importlib.import_module("alpha_web._rdagent_run_files")
    record_path = files._record_path

    (tmp_path / "real").mkdir()
    assert record_path(tmp_path, "real/file.json") == tmp_path / "real" / "file.json"
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(ValueError):
        record_path(tmp_path, "link/file.json")


def test_old_module_no_longer_defines_moved_names() -> None:
    defined = _defined_names("alpha_web._rdagent_runs")
    assert not defined & set(WORDS + FILES)
    reader = importlib.import_module("alpha_web._rdagent_runs")
    for name in ("list_runs", "read_run", "read_journey", "read_journey_figure"):
        assert callable(getattr(reader, name))


def test_rdagent_routes_unchanged() -> None:
    from alpha_web.api import rdagent

    paths = {getattr(route, "path", None) for route in rdagent.router.routes}
    assert {
        "/api/rdagent/runs",
        "/api/rdagent/runs/{run_id}",
        "/api/rdagent/runs/{run_id}/journeys/{idea_id}",
        "/api/rdagent/runs/{run_id}/journeys/{idea_id}/figures/{filename}",
    } <= paths
