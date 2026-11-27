"""The run story code lives in its own module; the runs module keeps its readers."""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

MOVED = (
    "STORY_STAGES",
    "STORY_REFUSALS",
    "STORY_FIELDS",
    "_story_key",
    "_story_raw",
    "BEFORE_SHORTLIST",
    "_shortlisted",
    "_idea",
    "_story_trials",
    "_story_tasks",
    "_story_ending",
    "_story",
)
NEW = "alpha_web._rdagent_run_story"
OLD = "alpha_web._rdagent_runs"
DIGEST = "a" * 64


def _defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_every_moved_name_lives_in_the_story_module() -> None:
    story = importlib.import_module(NEW)
    defined = _defined_names(Path(inspect.getfile(story)))
    for name in MOVED:
        assert hasattr(story, name), name
        assert name in defined, name
        value = getattr(story, name)
        if inspect.isfunction(value):
            assert value.__module__ == NEW, name


def test_old_module_no_longer_defines_the_moved_names() -> None:
    runs = importlib.import_module(OLD)
    defined = _defined_names(Path(inspect.getfile(runs)))
    assert not defined & set(MOVED)
    for name in MOVED:
        value = getattr(runs, name, None)
        if inspect.isfunction(value):
            assert value.__module__ == NEW, name


def test_moved_story_key_keeps_its_behaviour() -> None:
    story = importlib.import_module(NEW)
    row = {"iteration": 2, "name": "Funding", "code_sha256": DIGEST}
    assert story._story_key(row) == (2, "Funding", DIGEST)
    assert story._story_key({"iteration": 2, "name": "Funding"}) is None
    with pytest.raises(ValueError, match="code hash"):
        story._story_key({**row, "code_sha256": "not-a-hash"})
    with pytest.raises(ValueError, match="identity"):
        story._story_key({**row, "iteration": "2"})
    assert "STORY_FIELDS" not in story._story_raw({})


def test_moved_shortlisted_keeps_its_behaviour() -> None:
    story = importlib.import_module(NEW)
    assert story._shortlisted({"shortlist": True}) is True
    assert story._shortlisted({"shortlist": False}) is False
    for status in story.BEFORE_SHORTLIST:
        assert story._shortlisted({"status": status}) is False
    assert story._shortlisted({"status": "some-status-never-recorded"}) is None
    assert story._story_trials([], [], {"run"}) == []


def test_runs_module_still_serves_its_public_readers() -> None:
    runs = importlib.import_module(OLD)
    for name in ("list_runs", "read_run", "read_journey", "read_journey_figure"):
        assert callable(getattr(runs, name)), name
