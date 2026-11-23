"""Every label a run can carry has a one-line plain meaning in the one labels table."""

from __future__ import annotations

import re
from pathlib import Path

from alpha_cli.spine import cost_classes, reserve

ROOT = Path(__file__).resolve().parents[2]
SPINE = ROOT / "apps/alpha-cli/src/alpha_cli/spine"
TABLE = ROOT / "apps/alpha-web/frontend/src/panels/ruleTestModel.ts"
_LITERAL = re.compile(r"[\"']([a-z]+(?:-[a-z0-9]+)+)[\"']")
_ENTRY = re.compile(r"^\s*'?([a-z][\w-]*)'?:\s*(['\"])(.+)\2,?\s*$", re.MULTILINE)
#: Kebab words on a "label" line that are not run labels.
_NOT_LABELS = {"utf-8", "data-health"}


def _table() -> dict[str, str]:
    body = TABLE.read_text(encoding="utf-8").split("const LABEL_MEANING")[1].split("\n}\n")[0]
    return {key: text for key, _quote, text in _ENTRY.findall(body)}


def _labels_in_spine() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(SPINE.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search("label", line, re.IGNORECASE):
                for word in _LITERAL.findall(line):
                    found.setdefault(word, f"{path.name}:{number}")
    named = (
        reserve.HELD_BACK,
        reserve.SEEN,
        reserve.CONFIRMATION,
        reserve.CONFIRMED,
        cost_classes.CLASS_DEFAULT_LABEL,
        cost_classes.ASSUMED_LABEL,
        cost_classes.BORROW_LABEL,
        cost_classes.BORROW_NOT_CHARGED,
    )
    for word in named:
        found.setdefault(word, "named constant")
    return {word: where for word, where in found.items() if word not in _NOT_LABELS}


def test_every_label_in_the_spine_has_a_plain_meaning() -> None:
    table = _table()
    missing = {w: where for w, where in _labels_in_spine().items() if w not in table}
    assert not missing, f"labels without a meaning in ruleTestModel.ts: {missing}"


def test_every_meaning_is_one_plain_line() -> None:
    for label, text in _table().items():
        assert text.strip() == text and len(text) >= 20, label
        assert text.endswith("."), label
