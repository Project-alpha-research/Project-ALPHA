"""The command line's labels table is the Workstation's labels table."""

from __future__ import annotations

import re
from pathlib import Path

from alpha_cli.spine.label_meaning import LABEL_MEANING, label_lines

TS = Path(__file__).parents[2] / "apps/alpha-web/frontend/src/panels/ruleTestModel.ts"


def _workstation_table() -> dict[str, str]:
    block = re.search(
        r"const LABEL_MEANING: Record<string, string> = \{\n(.*?)\n\}\n", TS.read_text(), re.S
    )
    assert block is not None
    table: dict[str, str] = {}
    for line in block.group(1).splitlines():
        found = re.match(r"\s*'?([\w-]+)'?:\s*(['\"])(.*)\2,$", line)
        assert found is not None, line
        table[found.group(1)] = found.group(3).replace("\\'", "'")
    return table


def test_both_tables_say_the_same_words() -> None:
    assert _workstation_table() == LABEL_MEANING


def test_label_lines_name_each_label_with_its_meaning() -> None:
    lines = label_lines(["all-in", "dev-machine-data", "made-up-label"])
    assert lines[0] == "  all-in: All capital goes into each position; no volatility sizing."
    assert lines[1].startswith("  dev-machine-data: Run on the data stored on this development")
    assert lines[2] == "  made-up-label"
