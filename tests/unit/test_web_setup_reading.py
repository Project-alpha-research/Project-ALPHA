"""Setup Lab reads a stored study or trade as an evidence word and a place in its family.

The words and the family count belong to the command line; this module only relays them from stored
files. The tests below fail if the web copy of either drifts from the command line's own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine import reading as cli_reading
from alpha_cli.spine.setup_reading import family_context
from alpha_web import _setup_reading
from tests.unit.test_reading_ledger_setup import setup_row, write_ledger


def test_the_old_words_and_the_three_new_ones_are_the_command_lines() -> None:
    assert _setup_reading.OLD_OUTCOMES == cli_reading.OLD_SETUP_OUTCOMES
    assert _setup_reading.EVIDENCE_WORDS == cli_reading.SETUP_WORDS


@pytest.mark.parametrize("word", _setup_reading.EVIDENCE_WORDS)
def test_a_new_record_reads_as_its_stored_evidence(word: str) -> None:
    found = _setup_reading.reading_of(
        {"outcome": "not supported", "evidence": word}, None, "study", "s1"
    )
    assert found is not None and (found.evidence, found.old_wording) == (word, False)


@pytest.mark.parametrize("old", list(_setup_reading.OLD_OUTCOMES))
def test_an_old_record_reads_as_the_word_it_came_from_and_says_so(old: str) -> None:
    found = _setup_reading.reading_of({"outcome": old}, None, "trade", "t1")
    assert found is not None
    assert (found.evidence, found.old_wording) == (_setup_reading.OLD_OUTCOMES[old], True)


def test_an_unreadable_word_or_no_summary_gives_no_word_and_no_guess() -> None:
    odd = _setup_reading.reading_of({"outcome": "great"}, None, "study", "s1")
    assert odd is not None and odd.evidence is None
    assert _setup_reading.reading_of(None, None, "study", "s1") is None


def _rows() -> list[dict[str, Any]]:
    kinds = [
        ("setup_study", "Volume spike", "s1", []),
        ("setup_study", "  volume   SPIKE ", "s2", []),
        ("setup_trade", "Volume spike", "t1", []),
        ("setup_study", "Volume spike", "s3", ["repeat"]),
        ("setup_study", "Another idea", "s4", []),
        ("setup_study", "Volume spike", "s5", []),
    ]
    rows = []
    for index, (kind, idea, run_id, labels) in enumerate(kinds, 1):
        key = "trade_id" if kind == "setup_trade" else "study_id"
        rows.append(
            setup_row(
                trial_index=index,
                total_trials=index,
                kind=kind,
                idea=idea,
                run_id=run_id,
                labels=labels,
                random_date_p=0.01 * index,
                **{key: run_id},
            )
        )
    return rows


def test_the_place_in_the_family_is_the_command_lines_own(tmp_path: Path) -> None:
    rows = _rows()
    write_ledger(tmp_path, rows)
    for row in rows:
        kind = "trade" if row["kind"] == "setup_trade" else "study"
        run_id = row[f"{kind}_id"]
        place = _setup_reading._place(rows, kind, run_id, row["idea"])
        expected = family_context(tmp_path, row["kind"], row["idea"], run_id)
        if "repeat" in row["labels"]:  # a repeat is not counted: no place, the family count stands
            assert place == (None, expected["studies"])
        else:
            assert place == (expected["position"], expected["studies"])


def test_no_ledger_or_no_idea_gives_no_place() -> None:
    assert _setup_reading._place(None, "study", "s1", "Volume spike") == (None, None)
    assert _setup_reading._place(_rows(), "study", "s1", None) == (None, None)
    assert _setup_reading._place(_rows(), "study", "s1", "   ") == (None, None)
