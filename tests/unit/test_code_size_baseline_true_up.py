"""The code-size baseline holds only live offenders, each at today's measured size.

Measurement is the size gate's own (tests/unit/test_code_size.py, loaded unchanged), so keys and
counts match exactly what the gate measures. An entry for deleted code, or for code that shrank
to the limit or below, must be gone; every remaining entry must equal the current size.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).parents[2]
BASELINE = ROOT / ".claude" / "code-size-baseline.json"
GATE = ROOT / "tests" / "unit" / "test_code_size.py"


def _gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_code_size_gate_for_true_up", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _baseline() -> dict[str, dict[str, int]]:
    return cast(dict[str, dict[str, int]], json.loads(BASELINE.read_text(encoding="utf-8")))


def test_baseline_is_a_files_and_functions_map_of_line_counts() -> None:
    baseline = _baseline()
    assert isinstance(baseline.get("files"), dict)
    assert isinstance(baseline.get("functions"), dict)
    for section in ("files", "functions"):
        for key, value in baseline[section].items():
            assert isinstance(key, str) and key
            assert isinstance(value, int) and value > 0


def test_every_baseline_entry_is_a_live_oversized_item_at_its_measured_size() -> None:
    gate = _gate()
    measured_files, measured_functions = gate.measure_tree()
    baseline = _baseline()
    problems: list[str] = []
    for section, measured, limit in (
        ("files", measured_files, gate.FILE_LIMIT),
        ("functions", measured_functions, gate.FUNCTION_LIMIT),
    ):
        for key, ceiling in sorted(baseline[section].items()):
            if key not in measured:
                problems.append(f"{section}: {key} no longer exists (entry {ceiling})")
            elif measured[key] <= limit:
                problems.append(
                    f"{section}: {key} is {measured[key]} lines, within the {limit} limit"
                )
            elif measured[key] != ceiling:
                problems.append(f"{section}: {key} baseline {ceiling} but measured {measured[key]}")
    assert not problems, "\n".join(problems)
