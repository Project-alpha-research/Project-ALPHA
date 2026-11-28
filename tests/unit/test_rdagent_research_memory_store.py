"""The RD-Agent knowledge store lives in research_memory_store.py; research_memory.py uses it."""

from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
sys.path.insert(0, str(WORKER))
STORE_FILE = WORKER / "research_memory_store.py"
MEMORY_FILE = WORKER / "research_memory.py"

MOVED_FUNCTIONS = (
    "_json",
    "_hash",
    "_lock",
    "_write",
    "_fresh",
    "_fields",
    "_read",
    "_warning",
    "_quarantine",
    "completed_loops",
    "_load_knowledge",
)
MOVED_CONSTANTS = ("SCHEMA", "KNOWLEDGE")
# Names research_memory.py's remaining code (prepare, open_factor_loop, _record, _runtime_view)
# visibly calls, so it must still bind them, now from the store module.
USED_BY_MEMORY = ("completed_loops", "_quarantine", "_load_knowledge", "_read")


def _top_level(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text())
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assigned: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assigned |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)
    return functions, assigned


def _session(root: Path, folders: tuple[str, ...]) -> Path:
    session = root / "work/log/__session__"
    for folder in folders:
        (session / folder).mkdir(parents=True)
        (session / folder / "4_record").write_bytes(b"checkpoint")
    return session


def test_store_file_defines_moved_names() -> None:
    assert STORE_FILE.is_file()
    functions, assigned = _top_level(STORE_FILE)
    for name in MOVED_FUNCTIONS:
        assert name in functions, name
    for name in MOVED_CONSTANTS:
        assert name in assigned, name


def test_store_module_exposes_moved_names(tmp_path: Path) -> None:
    store = importlib.import_module("research_memory_store")
    assert store.SCHEMA == "AlphaRdagentResearchMemoryV1"
    assert isinstance(store.KNOWLEDGE, str)
    for name in MOVED_FUNCTIONS:
        assert callable(getattr(store, name)), name
    assert store.completed_loops(tmp_path / "missing") == 0
    assert store.completed_loops(_session(tmp_path / "two", ("3",))) == 4


def test_research_memory_no_longer_defines_moved_functions() -> None:
    functions, _ = _top_level(MEMORY_FILE)
    for name in MOVED_FUNCTIONS:
        assert name not in functions, name


def test_research_memory_binds_used_names_from_the_store() -> None:
    memory = importlib.import_module("research_memory")
    for name in USED_BY_MEMORY:
        assert getattr(memory, name).__module__.endswith("research_memory_store"), name


def test_store_file_imports_nothing_from_research_memory() -> None:
    tree = ast.parse(STORE_FILE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [alias.name for alias in node.names]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            names = (
                [value] if value == "research_memory" or value.endswith(".research_memory") else []
            )
        else:
            continue
        for name in names:
            assert name.split(".")[-1] != "research_memory", name


def test_prepare_and_loop_count_unchanged_through_research_memory(tmp_path: Path) -> None:
    memory = importlib.import_module("research_memory")
    plan = memory.prepare(
        tmp_path / "memory",
        run_id="one",
        run_dir=tmp_path / "one",
        source_sha256="source",
        judge_sha256="judge",
    )
    assert plan.continue_from is None and plan.loops_before == 0
    manifest = json.loads((tmp_path / "memory/memory.json").read_text())
    assert manifest["schema"] == "AlphaRdagentResearchMemoryV1"
    assert memory.completed_loops(_session(tmp_path / "one", ("0",))) == 1
    assert memory.completed_loops(_session(tmp_path / "two", ("3",))) == 4
