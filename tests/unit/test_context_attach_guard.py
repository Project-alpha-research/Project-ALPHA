"""Structural guard: only `context/attach.py` and the stores join context tables to bars.

Scans every source file. A file may name the COT or FINRA table reader (`table_path` of
`cftc_cot` or `finra_short`) only if it is the store, `attach.py` itself, or is listed in
READERS with a reason. `join_asof` may appear only in `align.py` and `attach.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path("packages/alpha-data/src/alpha_data")
ATTACH = DATA / "context/attach.py"
STORES = {DATA / "context/cftc_cot.py", DATA / "context/finra_short.py"}
JOIN_HOMES = {DATA / "align.py", ATTACH}
STORE_MODULES = {"cftc_cot", "finra_short"}
READERS: dict[Path, str] = {
    Path(
        "apps/alpha-cli/src/alpha_cli/context_free_cmds.py"
    ): "show-cftc-cot and show-finra-short-volume print stored rows; they join nothing to bars",
}


def names_store_reader(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "table_path"
            and isinstance(node.value, ast.Name)
            and node.value.id in STORE_MODULES
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.rsplit(".", 1)[-1] in STORE_MODULES
            and any(a.name == "table_path" for a in node.names)
        ):
            return True
        if isinstance(node, ast.Constant) and node.value in {
            "alpha_data.context.cftc_cot.table_path",
            "alpha_data.context.finra_short.table_path",
        }:
            return True
    return False


def names_join_asof(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == "join_asof":
            return True
        if isinstance(node, ast.Name) and node.id == "join_asof":
            return True
        if isinstance(node, ast.Constant) and node.value == "join_asof":
            return True
        if isinstance(node, ast.alias) and node.name == "join_asof":
            return True
    return False


def source_files() -> list[Path]:
    roots = [*ROOT.glob("packages/*/src"), *ROOT.glob("apps/*/src"), ROOT / "workers"]
    return [p for r in roots for p in r.rglob("*.py") if ".venv" not in p.parts]


def test_only_attach_the_stores_and_listed_readers_name_a_context_table_reader() -> None:
    allowed = {ATTACH, *STORES, *READERS}
    offenders = [
        str(p.relative_to(ROOT))
        for p in source_files()
        if p.relative_to(ROOT) not in allowed and names_store_reader(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"code reads COT or FINRA tables outside attach: {offenders}"


def test_join_asof_appears_only_in_align_and_attach() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in source_files()
        if p.relative_to(ROOT) not in JOIN_HOMES and names_join_asof(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"join_asof outside its homes: {offenders}"


def test_the_guard_sees_every_way_of_naming_the_readers() -> None:
    assert names_store_reader("cftc_cot.table_path(d, 'X')")
    assert names_store_reader("from alpha_data.context.finra_short import table_path")
    assert names_store_reader(
        "from alpha_data.context import finra_short\nf = finra_short.table_path"
    )
    assert not names_store_reader("osap_portfolios.table_path(d)")
    assert names_join_asof("df.join_asof(o, on='t')")
    assert names_join_asof("from polars import join_asof")
    assert names_join_asof("getattr(df, 'join_asof')")
    assert not names_join_asof("df.join(o, on='t')")


def test_every_home_and_reader_still_exists_and_attach_is_the_only_joiner() -> None:
    assert all((ROOT / p).exists() for p in {*JOIN_HOMES, *STORES, *READERS})
    assert names_join_asof((ROOT / ATTACH).read_text(encoding="utf-8"))
    for path in READERS:
        assert not names_join_asof((ROOT / path).read_text(encoding="utf-8")), path
