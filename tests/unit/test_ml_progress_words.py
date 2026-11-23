"""The ML progress line gives the fold count and names no fold in progress."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_cli.ml_progress import expected_sentence, record, seconds_per_fold, training_phrase


def test_the_line_says_the_fold_count_and_that_the_stage_reports_at_its_end() -> None:
    assert training_phrase(8) == "fold count 8; this stage reports when it ends"


def test_the_line_never_guesses_a_fold() -> None:
    assert "about fold" not in training_phrase(8)


def test_no_estimate_is_made_up_without_a_timed_run(tmp_path: Path) -> None:
    assert seconds_per_fold(tmp_path, 20) is None
    assert "No time estimate yet" in expected_sentence(None, 8)
    record(tmp_path, assets=20, folds=8, seconds=160.0)
    assert seconds_per_fold(tmp_path, 20) == pytest.approx(20.0, rel=1e-9, abs=1e-12)
    assert "about 3 minutes" in expected_sentence(160.0, 8)
