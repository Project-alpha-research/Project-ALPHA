"""The run list relays the evidence word a run stored; it works out nothing for an older run."""

from __future__ import annotations

from typing import Any

import pytest

from alpha_web._runs import _stored_evidence


def _reading(word: Any, state: str = "sound") -> dict[str, Any]:
    return {"evidence": {"word": word}, "checks": [{"name": "audit", "state": state}]}


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        (_reading("some evidence"), "some evidence"),
        (_reading("too little to read"), "too little to read"),
        (_reading(None, "fault"), "fault"),
        (_reading(None, "sound"), None),
        (None, None),
        ("odd", None),
        ({"evidence": "odd", "checks": "odd"}, None),
    ],
)
def test_the_list_shows_the_stored_word_a_fault_or_nothing(reading: Any, expected: Any) -> None:
    assert _stored_evidence(reading) == expected
