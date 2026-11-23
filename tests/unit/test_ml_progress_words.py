"""The ML progress line counts every fold, then names the closing stages."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_cli.ml_progress import expected_sentence, fold_phrase, record, seconds_per_fold


def test_the_count_reaches_the_last_fold() -> None:
    assert fold_phrase(0.0, 10.0, 8) == "about fold 1 of 8"
    assert fold_phrase(35.0, 10.0, 8) == "about fold 4 of 8"
    assert fold_phrase(79.0, 10.0, 8) == "about fold 8 of 8"


def test_past_the_estimate_the_line_names_the_closing_stages() -> None:
    said = fold_phrase(80.0, 10.0, 8)
    assert "scoring" in said and "writing the run" in said
    assert "fold 8 of 8" not in said


def test_no_estimate_is_made_up_without_a_timed_run(tmp_path: Path) -> None:
    assert seconds_per_fold(tmp_path, 20) is None
    assert "No time estimate yet" in expected_sentence(None, 8)
    record(tmp_path, assets=20, folds=8, seconds=160.0)
    assert seconds_per_fold(tmp_path, 20) == pytest.approx(20.0, rel=1e-9, abs=1e-12)
    assert "about 3 minutes" in expected_sentence(160.0, 8)
