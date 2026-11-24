"""A code map made from the code: one line per module (path, line count, first docstring line).

``fs.py map apps/alpha-cli`` reads each Python module under ``<workspace>/src`` (or the workspace
itself when it has no ``src``) with ``ast`` (never imports it), and each ``.ts``/``.tsx`` file under
``<workspace>/frontend/src`` (first comment line).
Nothing is stored, so the map cannot be stale. ``--find WORDS`` keeps lines where every word occurs
in the path or description (case-insensitive).
"""

from __future__ import annotations

import ast
from pathlib import Path

SKIP_DIRS = {"__pycache__", "node_modules", "static", "tests", "dist", "build"}
NO_TEXT = "(no description)"
FRONTEND_SUFFIXES = {".ts", ".tsx"}


def _python_summary(path: Path) -> tuple[int, str]:
    text = path.read_text(encoding="utf-8")
    try:
        doc = ast.get_docstring(ast.parse(text))
    except SyntaxError:
        return len(text.splitlines()), "(unreadable)"
    first = next((ln.strip() for ln in (doc or "").splitlines() if ln.strip()), "")
    return len(text.splitlines()), first or NO_TEXT


def _frontend_summary(path: Path) -> tuple[int, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for raw in lines[:12]:
        line = raw.strip()
        if line.startswith("//"):
            return len(lines), line.lstrip("/ ").strip() or NO_TEXT
        if line.startswith("/*"):
            return len(lines), line.lstrip("/* ").rstrip("*/ ").strip() or NO_TEXT
    return len(lines), NO_TEXT


def _skipped(path: Path, base: Path) -> bool:
    parts = path.relative_to(base).parts
    return (
        any(p in SKIP_DIRS or p.startswith(".") or p.endswith(".egg-info") for p in parts[:-1])
        or "generated" in path.name
        or ".test." in path.name
    )


def _entries(root: Path, workspace: str) -> list[tuple[str, str, int, str]]:
    """(directory, file name, line count, description) for every module of the workspace."""
    found: list[tuple[str, str, int, str]] = []
    places = [
        ("src", {".py"}, _python_summary),
        ("frontend/src", FRONTEND_SUFFIXES, _frontend_summary),
    ]
    if not any((root / workspace / sub).is_dir() for sub, _, _ in places):
        places = [(".", {".py"}, _python_summary)]  # a worker keeps its modules at its top
    for sub, suffixes, summary in places:
        base = root / workspace / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in suffixes or not path.is_file() or _skipped(path, base):
                continue
            count, text = summary(path)
            folder = path.parent.relative_to(root).as_posix()
            found.append((folder, path.name, count, text))
    return found


def code_map(root: Path, workspace: str, find: list[str] | None = None) -> str:
    if not (root / workspace).is_dir():
        raise ValueError(f"no such workspace: {workspace}")
    words = [w.lower() for w in find or []]
    groups: dict[str, list[str]] = {}
    for folder, name, count, text in _entries(root, workspace):
        haystack = f"{folder}/{name} {text}".lower()
        if all(w in haystack for w in words):
            groups.setdefault(folder, []).append(f"  {name}  {count}  {text}")
    rows: list[str] = []
    for folder, lines in groups.items():
        rows.append(f"{folder}/ ({len(lines)})")
        rows.extend(lines)
    return "\n".join(rows) if rows else f"no module in {workspace} matches"
