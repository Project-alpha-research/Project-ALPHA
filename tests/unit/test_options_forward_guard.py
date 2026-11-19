"""Structural guard: only the forward-use home may reach the options forward reader.

Research-side code (spine, toolbox, Setup Lab, RD-Agent modules, the hypothesis scan, validation)
must read options through the capped research reads. A source file may name `forward_chain_as_of`
only if it is the store that defines it or is listed in FORWARD_USE_HOMES with a reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORWARD_NAME = "forward_chain_as_of"
STORE = Path("packages/alpha-data/src/alpha_data/options/store.py")
FORWARD_USE_HOMES: dict[Path, str] = {}


def names_forward_reader(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == FORWARD_NAME:
            return True
        if isinstance(node, ast.Name) and node.id == FORWARD_NAME:
            return True
        if isinstance(node, ast.FunctionDef) and node.name == FORWARD_NAME:
            return True
        if isinstance(node, ast.alias) and node.name == FORWARD_NAME:
            return True
        if isinstance(node, ast.Constant) and node.value == FORWARD_NAME:
            return True
    return False


def source_files() -> list[Path]:
    roots = [*ROOT.glob("packages/*/src"), *ROOT.glob("apps/*/src"), ROOT / "workers"]
    return [p for r in roots for p in r.rglob("*.py") if ".venv" not in p.parts]


def test_only_the_store_and_listed_forward_homes_name_the_forward_reader() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in source_files()
        if p.relative_to(ROOT) != STORE
        and p.relative_to(ROOT) not in FORWARD_USE_HOMES
        and names_forward_reader(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"research-side code reaches the forward reader: {offenders}"


def test_the_guard_sees_every_way_of_naming_the_reader() -> None:
    assert names_forward_reader("store.forward_chain_as_of(a, b, c)")
    assert names_forward_reader("from x import forward_chain_as_of")
    assert names_forward_reader("f = forward_chain_as_of")
    assert names_forward_reader("getattr(s, 'forward_chain_as_of')")
    assert not names_forward_reader("store.chain_as_of(a, b, c)")


def test_the_store_still_defines_the_forward_reader() -> None:
    assert names_forward_reader((ROOT / STORE).read_text(encoding="utf-8"))
    assert all((ROOT / home).exists() for home in FORWARD_USE_HOMES)
