"""Structural guard: only the session home talks to the exchange-calendars library.

Every other module asks `alpha_data.sessions`, which widens the library's moving window and has
one documented rule outside it. A source file may import or name the library only if it is the
home or is listed in ALLOWED with a reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = "exchange_calendars"
HOME = Path("packages/alpha-data/src/alpha_data/sessions.py")
ALLOWED: dict[Path, str] = {}


def reaches_library(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == LIBRARY for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == LIBRARY:
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.split(".")[0] == LIBRARY
        ):
            return True
        if isinstance(node, ast.Attribute) and node.attr == "get_calendar":
            return True
    return False


def source_files() -> list[Path]:
    roots = [*ROOT.glob("packages/*/src"), *ROOT.glob("apps/*/src"), ROOT / "workers"]
    return [p for r in roots for p in r.rglob("*.py") if ".venv" not in p.parts]


def test_only_the_session_home_reaches_the_calendar_library() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in source_files()
        if p.relative_to(ROOT) != HOME
        and p.relative_to(ROOT) not in ALLOWED
        and reaches_library(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"modules reach the calendar library directly: {offenders}"


def test_the_guard_sees_every_way_of_reaching_the_library() -> None:
    assert reaches_library("import exchange_calendars as xcals")
    assert reaches_library("from exchange_calendars.errors import CalendarError")
    assert reaches_library("import exchange_calendars.errors")
    assert reaches_library("importlib.import_module('exchange_calendars')")
    assert reaches_library("__import__('exchange_calendars')")
    assert reaches_library("calendars.get_calendar('XNYS')")
    assert not reaches_library("from alpha_data.sessions import sessions_between")


def test_the_home_still_uses_the_library_and_the_allow_list_is_real() -> None:
    assert reaches_library((ROOT / HOME).read_text(encoding="utf-8"))
    assert all((ROOT / path).exists() for path in ALLOWED)
