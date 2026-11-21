"""Structural guard: a research read of bars or dividends is cut at the held-back boundary.

`_runner.load_bars` and `load_dividends` read everything stored when `as_of` is missing or None,
and `ParquetStore.read_bars` takes no cut-off at all. So the cut lives only in each caller.
This test scans `apps/alpha-cli/src` for every call that passes no cut-off and checks it against
an allow-list with one reason per entry. Two kinds of entry exist:

- exempt: the read is forward use, a display, a check of stored bytes or already cut by other means.
- open: a known leak that a later change fixes. Remove its entry in the same change.

A new bare call fails the test. An entry that matches no call also fails it: a stale list is a lie.

Limit: the scan sees a missing `as_of` and a literal `as_of=None`. It cannot see a variable that is
None at run time (`as_of=as_of`). Those reads are covered by the per-command tests named in
`docs/reference/project/reserved-period.md`.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "apps" / "alpha-cli" / "src" / "alpha_cli"
LOADERS = frozenset({"load_bars", "load_dividends"})
STORE_READER = "read_bars"
RUNNER = "alpha_cli._runner"

# (file under alpha_cli/, enclosing function) -> reason. `exempt:` or `open:` comes first.
ALLOWED: dict[tuple[str, str], str] = {
    ("_data_health.py", "_stock_peers"): "exempt: data health checks every stored bar by design",
    ("_data_health.py", "compute_report"): "exempt: data health checks every stored bar by design",
    ("_ibkr_paper.py", "load_ibkr_warmup"): "exempt: forward paper use reads the newest bars",
    ("_paper.py", "load_paper_warmup"): "exempt: forward paper use reads the newest bars",
    ("daily_scheduler.py", "execute_cycle"): "exempt: the daily scheduler is forward paper use",
    ("follow_source.py", "latest_bar_hashes"): "exempt: follow is forward use (follow separation)",
    ("market_overview_cmds.py", "build_market_overview"): "exempt: a display of the newest bars",
    ("nightly_refresh.py", "_bars"): "exempt: reads only the stored time span to plan a refresh",
    ("context_derived_cmds.py", "_bars_and_calendar"): (
        "exempt: show-derived passes the frame to attach_context(cutoff=CUTOFF), which cuts it"
    ),
    ("_native_rule_projection.py", "_snapshot"): (
        "exempt: compares a synthetic snapshot with its own disclosed rows; no research read"
    ),
    ("_native_daily_rule_projection.py", "chart_snapshot"): (
        "exempt: compares a chart snapshot with its own frozen query rows; no research read"
    ),
    ("comparison_acquisition_evidence.py", "_replay"): (
        "exempt: verifies stored acquisition artifacts byte for byte; no research read"
    ),
    ("comparison_acquisition_evidence.py", "_result"): (
        "exempt: verifies stored acquisition artifacts byte for byte; no research read"
    ),
}


def _runner_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Local names bound to a loader, and local names bound to the `_runner` module."""
    loaders: set[str] = set()
    modules: set[str] = {"_runner"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            home = node.module or ""
            for alias in node.names:
                if home == RUNNER and alias.name in LOADERS:
                    loaders.add(alias.asname or alias.name)
                if home == "alpha_cli" and alias.name == "_runner":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == RUNNER and alias.asname:
                    modules.add(alias.asname)
    for node in ast.walk(tree):  # a seam such as `_load_bars = _runner.load_bars`
        if isinstance(node, ast.Assign) and _names_loader(node.value, loaders):
            loaders.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return loaders, modules


def _names_loader(node: ast.expr, loaders: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in loaders
    return isinstance(node, ast.Attribute) and node.attr in LOADERS


def _cut_is_missing(call: ast.Call) -> bool:
    """True when the call has no `as_of`, `as_of=None`, or `**kwargs` that may hide it."""
    for keyword in call.keywords:
        if keyword.arg is None:
            return True
        if keyword.arg == "as_of":
            value = keyword.value
            return isinstance(value, ast.Constant) and value.value is None
    return True


class _Scan(ast.NodeVisitor):
    def __init__(self, loaders: set[str], modules: set[str]) -> None:
        self.loaders, self.modules = loaders, modules
        self.scope: list[str] = []
        self.found: list[tuple[str, int, str]] = []
        self.call_funcs: set[int] = set()

    def _enter(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _enter

    def _where(self) -> str:
        return ".".join(self.scope) or "<module>"

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        self.call_funcs.add(id(func))
        name = self._loader_name(func)
        if name is not None and _cut_is_missing(node):
            self.found.append((self._where(), node.lineno, name))
        self.generic_visit(node)

    def _loader_name(self, func: ast.expr) -> str | None:
        if isinstance(func, ast.Name) and func.id in self.loaders:
            return func.id
        if isinstance(func, ast.Attribute):
            if func.attr == STORE_READER:
                return STORE_READER
            if func.attr in LOADERS:
                return func.attr
        return None

    def visit_Assign(self, node: ast.Assign) -> None:
        if _names_loader(node.value, self.loaders):
            self.call_funcs.add(id(node.value))  # a seam declaration, not a read
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        is_read = isinstance(node.ctx, ast.Load) and node.id in self.loaders
        if is_read and id(node) not in self.call_funcs:
            self.found.append((self._where(), node.lineno, f"{node.id} (used as a value)"))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in LOADERS and id(node) not in self.call_funcs:
            self.found.append((self._where(), node.lineno, f"{node.attr} (used as a value)"))
        self.generic_visit(node)


def bare_reads(source: str) -> list[tuple[str, int, str]]:
    """Every (function, line, loader) in ``source`` that reads without a cut-off."""
    tree = ast.parse(source)
    scan = _Scan(*_runner_names(tree))
    scan.visit(tree)
    return scan.found


def all_bare_reads() -> dict[tuple[str, str], list[int]]:
    found: dict[tuple[str, str], list[int]] = {}
    for path in sorted(CLI.rglob("*.py")):
        rel = path.relative_to(CLI).as_posix()
        for where, line, _name in bare_reads(path.read_text(encoding="utf-8")):
            found.setdefault((rel, where), []).append(line)
    return found


def test_every_bare_read_is_listed_with_a_reason() -> None:
    new = sorted(set(all_bare_reads()) - set(ALLOWED))
    assert not new, f"a read of bars or dividends passes no cut-off; cut it or list it: {new}"


def test_no_listed_entry_is_stale() -> None:
    stale = sorted(set(ALLOWED) - set(all_bare_reads()))
    assert not stale, f"these entries match no bare read any more; remove them: {stale}"


def test_every_entry_has_a_kind_and_a_reason() -> None:
    bad = [k for k, why in ALLOWED.items() if not why.startswith(("exempt: ", "open: "))]
    assert not bad, f"each reason starts with 'exempt: ' or 'open: ': {bad}"


def test_the_scan_sees_every_way_of_naming_a_loader() -> None:
    cases = {
        "from alpha_cli._runner import load_bars\nload_bars(s, data_dir=d)": 1,
        "from alpha_cli._runner import load_bars as lb\nlb(s, data_dir=d)": 1,
        "from alpha_cli import _runner\n_runner.load_dividends(s, data_dir=d)": 1,
        "from alpha_cli import _runner as r\nr.load_bars(s, data_dir=d, as_of=None)": 1,
        "import alpha_cli._runner as r\nr.load_bars(s, data_dir=d, **kw)": 1,
        "store.read_bars(s)": 1,
        "from alpha_cli._runner import load_bars\nmap(load_bars, xs)": 1,
        "from alpha_cli._runner import load_bars\nload_bars(s, data_dir=d, as_of=held.as_of)": 0,
        "from alpha_cli import _runner\n_runner.load_bars(s, data_dir=d, as_of=cut)": 0,
        "from alpha_cli import _runner\nseam = _runner.load_bars\nseam(s, data_dir=d)": 1,
        "from alpha_cli import _runner\nseam = _runner.load_bars": 0,
        "other.load_things(s)": 0,
    }
    for source, expected in cases.items():
        assert len(bare_reads(source)) == expected, source
