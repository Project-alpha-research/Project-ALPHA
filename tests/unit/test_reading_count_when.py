"""The paragraph stating a stored reading's counts says when: it opens with a fixed lead-in."""

from __future__ import annotations

import re
from typing import Any

from alpha_cli.spine.tries import reading_count_sentence

LEAD = "When this run was stored: "


def family(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "family_id": "spine:ma_cross",
        "n_trials_used": 6,
        "this_run": 1,
        "prior_trials": 3,
        "unknown_rows": 0,
        "same_asset_tests": 1,
        "variants_scored": 2,
    }
    base.update(over)
    return base


def numbers(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", text)]


def test_count_paragraph_starts_with_when_stored() -> None:
    text = reading_count_sentence(family(), "SPY")
    assert text is not None
    assert text.startswith(LEAD)
    assert text[len(LEAD) :].startswith("You have tested 2 ideas on SPY")
    assert "\n" not in text[: len(LEAD)]


def test_the_numbers_are_unchanged() -> None:
    text = reading_count_sentence(family(), "SPY")
    assert text is not None
    assert numbers(text) == [2, 4, 2, 6]


def test_mismatch_paragraph_also_starts_with_when_stored() -> None:
    text = reading_count_sentence(family(n_trials_used=9), "SPY")
    assert text is not None
    assert text.startswith(LEAD)


def test_mismatch_numbers_are_unchanged() -> None:
    text = reading_count_sentence(family(n_trials_used=9), "SPY")
    assert text is not None
    assert numbers(text) == [2, 9]


def test_no_stored_count_gives_no_paragraph() -> None:
    assert reading_count_sentence(family(n_trials_used=None), "SPY") is None
