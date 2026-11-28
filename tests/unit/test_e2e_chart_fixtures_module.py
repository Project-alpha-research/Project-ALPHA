"""The e2e chart-bundle fixtures live in e2e/support/chartFixtures.ts, not in workstationHarness.ts.

A pure move: the harness and the specs that use a moved name import it from its new module, with
no re-export shim from the harness and no import cycle back into the harness.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "apps" / "alpha-web" / "frontend" / "e2e"
SUPPORT = E2E / "support"
HARNESS = SUPPORT / "workstationHarness.ts"
FIXTURES = SUPPORT / "chartFixtures.ts"

MOVED = [
    "HEAVY_RUN_ID",
    "HEAVY_BAR_COUNT",
    "HEAVY_ANNOTATION_COUNT",
    "HEAVY_START_TS",
    "heavyChartBundle",
    "CAUSAL_START_TS",
    "CAUSAL_TRADES",
    "traceEvent",
    "causalChartBundle",
    "denseCausalChartBundle",
    "EMPTY_NATIVE_TEARSHEET",
]
EXPORTED = [
    "heavyChartBundle",
    "causalChartBundle",
    "denseCausalChartBundle",
    "EMPTY_NATIVE_TEARSHEET",
]
SPECS = ["market-performance.spec.ts", "quant-workspace.spec.ts", "scientific-performance.spec.ts"]


def _definition(name: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*(?:export\s+)?(?:async\s+)?(?:function|const|let)\s+{name}\b", re.M)


def _imported_names(text: str, module: str) -> set[str]:
    mod = re.escape(module)
    names: set[str] = set()
    patterns = [
        rf"import\s*(?:type\s*)?\{{([^}}]*)\}}\s*from\s*['\"]{mod}['\"]",
        rf"export\s*\{{([^}}]*)\}}\s*from\s*['\"]{mod}['\"]",
        rf"\{{([^}}]*)\}}\s*=\s*await\s+import\(\s*['\"]{mod}['\"]\s*\)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            for part in match.group(1).split(","):
                token = part.strip().split(" as ")[0].split(":")[0].strip()
                token = token.removeprefix("type ").strip()
                if token:
                    names.add(token)
    return names


def test_chart_fixtures_module_defines_every_moved_fixture() -> None:
    assert FIXTURES.is_file(), FIXTURES
    text = FIXTURES.read_text(encoding="utf-8")
    missing = [name for name in MOVED if not _definition(name).search(text)]
    assert not missing, missing


def test_chart_fixtures_module_exports_the_bundles_and_tearsheet() -> None:
    text = FIXTURES.read_text(encoding="utf-8")
    for name in EXPORTED:
        exported = re.search(
            rf"^\s*export\s+(?:async\s+)?(?:function|const)\s+{name}\b", text, re.M
        ) or re.search(rf"export\s*\{{[^}}]*\b{name}\b[^}}]*\}}", text)
        assert exported, name


def test_harness_no_longer_defines_the_moved_fixtures() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    still_defined = [name for name in MOVED if _definition(name).search(text)]
    assert not still_defined, still_defined


def test_harness_does_not_reexport_the_moved_fixtures() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    assert not re.search(r"export\s*\*\s*from\s*['\"]\./chartFixtures['\"]", text)
    reexported = _imported_names(
        "\n".join(
            m.group(0) for m in re.finditer(r"export\s*\{[^}]*\}\s*from\s*['\"][^'\"]+['\"]", text)
        ),
        "./chartFixtures",
    )
    assert not (reexported & set(MOVED)), reexported
    for name in MOVED:
        assert not re.search(rf"export\s*\{{[^}}]*\b{name}\b[^}}]*\}}", text), name


def test_harness_imports_its_fixtures_from_chart_fixtures() -> None:
    text = HARNESS.read_text(encoding="utf-8")
    imported = _imported_names(text, "./chartFixtures")
    for name in [
        "heavyChartBundle",
        "causalChartBundle",
        "denseCausalChartBundle",
        "EMPTY_NATIVE_TEARSHEET",
    ]:
        assert name in imported, (name, sorted(imported))


def test_chart_fixtures_does_not_import_the_harness() -> None:
    text = FIXTURES.read_text(encoding="utf-8")
    assert not re.search(r"from\s*['\"][^'\"]*workstationHarness['\"]", text)
    assert not re.search(r"import\s*['\"][^'\"]*workstationHarness['\"]", text)


def test_specs_import_heavy_chart_bundle_from_chart_fixtures() -> None:
    for spec in SPECS:
        text = (E2E / spec).read_text(encoding="utf-8")
        assert "heavyChartBundle" not in _imported_names(text, "./support/workstationHarness"), spec
        assert "heavyChartBundle" in _imported_names(text, "./support/chartFixtures"), spec


def test_performance_and_workspace_specs_keep_their_file_names() -> None:
    for spec in SPECS:
        assert (E2E / spec).is_file(), spec
    assert HARNESS.is_file()
