"""Structural guard: only `context/attach.py` and the stores join context tables to bars.

Scans every source file. A file may reach a COT or FINRA table (the store's `table_path`, `SOURCE`
or `SCHEMA` under any alias or through `getattr`, or the table path or source name as text) only
if it is the store, `attach.py` itself, or is listed in READERS with a reason. `join_asof` may
appear only in `align.py` and `attach.py`.
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


TOUCHES = {"table_path", "SOURCE", "SCHEMA"}
# Path parts and source names that reach the tables without the store module.
TABLE_TEXT = ("context/cftc", "context/finra", "cftc-cot", "finra-short-volume")


def _store_aliases(tree: ast.AST) -> set[str]:
    """Every local name bound to a store module, under any alias."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname or a.name for a in node.names if a.name in STORE_MODULES}
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.rsplit(".", 1)[-1] in STORE_MODULES and a.asname is not None:
                    names.add(a.asname)
    return names


def _is_store(node: ast.expr, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases or node.id in STORE_MODULES
    return isinstance(node, ast.Attribute) and node.attr in STORE_MODULES


def names_store_reader(source: str) -> bool:
    """True if the code can reach a COT or FINRA table: the store's path, source or schema."""
    tree = ast.parse(source)
    aliases = _store_aliases(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in TOUCHES
            and _is_store(node.value, aliases)
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.rsplit(".", 1)[-1] in STORE_MODULES
            and any(a.name in TOUCHES or a.name == "*" for a in node.names)
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and _is_store(node.args[0], aliases)
        ):
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and any(text in node.value for text in TABLE_TEXT)
        ):
            return True
    return False


ASOF_JOINS = {"join_asof", "merge_asof"}  # polars and pandas as-of joins


def names_join_asof(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in ASOF_JOINS:
            return True
        if isinstance(node, ast.Name) and node.id in ASOF_JOINS:
            return True
        if isinstance(node, ast.Constant) and node.value in ASOF_JOINS:
            return True
        if isinstance(node, ast.alias) and node.name in ASOF_JOINS:
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
    assert not names_store_reader(
        "from alpha_data.context import finra_short\nc = finra_short.CAVEAT"
    )
    assert names_store_reader("import alpha_data.context.cftc_cot as c\nc.table_path(d, 'X')")
    assert names_store_reader("from alpha_data.context import cftc_cot as c\np = c.table_path")
    assert names_store_reader(
        "import alpha_data.context.finra_short\nalpha_data.context.finra_short.SCHEMA"
    )
    assert names_store_reader(
        "from alpha_data.context import cftc_cot\ngetattr(cftc_cot, 'table_' + 'path')"
    )
    assert names_store_reader("from alpha_data.context.cftc_cot import *")
    assert names_store_reader(
        "pl.read_parquet(data_dir / 'context/finra/short_volume/SPY.parquet')"
    )
    assert names_store_reader("load_events(p, source='cftc-cot', schema=s)")
    assert names_join_asof("df.join_asof(o, on='t')")
    assert names_join_asof("from polars import join_asof")
    assert names_join_asof("getattr(df, 'join_asof')")
    assert names_join_asof("pd.merge_asof(a, b, on='t')")
    assert not names_join_asof("df.join(o, on='t')")


def test_every_home_and_reader_still_exists_and_attach_is_the_only_joiner() -> None:
    assert all((ROOT / p).exists() for p in {*JOIN_HOMES, *STORES, *READERS})
    assert names_join_asof((ROOT / ATTACH).read_text(encoding="utf-8"))
    for path in READERS:
        assert not names_join_asof((ROOT / path).read_text(encoding="utf-8")), path
