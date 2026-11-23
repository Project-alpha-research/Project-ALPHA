"""The ML progress line counts every fold, then names the closing stages."""

from __future__ import annotations

from alpha_cli.ml_progress import fold_phrase


def test_the_count_reaches_the_last_fold() -> None:
    assert fold_phrase(0.0, 10.0, 8) == "about fold 1 of 8"
    assert fold_phrase(35.0, 10.0, 8) == "about fold 4 of 8"
    assert fold_phrase(79.0, 10.0, 8) == "about fold 8 of 8"


def test_past_the_estimate_the_line_names_the_closing_stages() -> None:
    said = fold_phrase(80.0, 10.0, 8)
    assert "scoring" in said and "writing the run" in said
    assert "fold 8 of 8" not in said
