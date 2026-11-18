import re
from collections.abc import Iterator
from pathlib import Path

from alpha_core.reserve import RESERVED_START

ROOT = Path(__file__).resolve().parents[2]
CORE_HOME = Path("packages/alpha-core/src/alpha_core/reserve.py")
WORKER_HOME = Path("workers/rdagent/alpha_factor_data.py")
WORKER_ASSIGNMENT = re.compile(r'^RESERVED_START = "([0-9]{4}-[0-9]{2}-[0-9]{2})"$', re.MULTILINE)
DATE_LITERAL = re.compile(r"2024-01-01|\b2024\s*,\s*1\s*,\s*1\b")


def _raise_walk_error(error: OSError) -> None:
    raise error


def _source_files() -> Iterator[Path]:
    source_roots = [*ROOT.glob("packages/*/src"), *ROOT.glob("apps/*/src"), ROOT / "workers"]
    for source_root in source_roots:
        for directory, subdirectories, filenames in source_root.walk(on_error=_raise_walk_error):
            subdirectories[:] = [
                name
                for name in subdirectories
                if name not in {"tests", "fixtures", "docs", ".venv", "__pycache__"}
            ]
            for name in filenames:
                source = directory / name
                if (
                    source.suffix in {".py", ".pyi", ".template"}
                    and not source.stem.startswith("test_")
                    and not source.stem.endswith("_test")
                    and source.stem != "conftest"
                ):
                    yield source


def test_reserved_date_has_one_home() -> None:
    violations: list[str] = []
    for source in _source_files():
        relative = source.relative_to(ROOT)
        if relative == CORE_HOME:
            continue
        contents = source.read_text(encoding="utf-8")
        assignment = WORKER_ASSIGNMENT.search(contents) if relative == WORKER_HOME else None
        for match in DATE_LITERAL.finditer(contents):
            if assignment is not None and match.span() == assignment.span(1):
                continue
            line = contents.count("\n", 0, match.start()) + 1
            violations.append(f"{relative}:{line}")
    details = "\n".join(sorted(violations))
    assert not violations, f"Reserved date literals outside their homes:\n{details}"


def test_isolated_worker_reserved_start_matches_core() -> None:
    contents = (ROOT / WORKER_HOME).read_text(encoding="utf-8")
    assert WORKER_ASSIGNMENT.findall(contents) == [RESERVED_START]
