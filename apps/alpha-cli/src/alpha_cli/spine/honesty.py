"""Exercise the real answer checker on temporary fixture runs, without a model."""

import json
import tempfile
from pathlib import Path
from typing import Any

from alpha_cli.results_cmds import fact_lookup, flag_lookup
from alpha_cli.spine.check import check_text
from alpha_cli.spine.honesty_scenarios import FIXTURES, SCENARIOS

NOTE = (
    "What this shows: ALPHA's answer checker catches these planted mistakes. "
    "It checks numbers, labels and flags, not reasoning."
)


def build_fixture(home: Path) -> None:
    for run_id, documents in FIXTURES.items():
        folder = home / "runs" / run_id
        folder.mkdir(parents=True)
        for filename, value in documents.items():
            (folder / filename).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def run_selftest() -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="alpha-honesty-") as directory:
        home = Path(directory)
        build_fixture(home)
        lookup, flags = fact_lookup(home), flag_lookup(home)
        for scenario in SCENARIOS:
            result = check_text(scenario.draft, lookup, 0, flags)
            got = {problem["kind"] for problem in result["problems"]}
            scenarios.append(
                {
                    "id": scenario.id,
                    "title": scenario.title,
                    "honest": scenario.honest,
                    "expected": sorted(scenario.expected),
                    "got": sorted(got),
                    "ok": got == scenario.expected,
                }
            )
    passed = sum(row["ok"] for row in scenarios)
    return {
        "ok": passed == len(scenarios),
        "passed": passed,
        "total": len(scenarios),
        "scenarios": scenarios,
        "note": NOTE,
    }
