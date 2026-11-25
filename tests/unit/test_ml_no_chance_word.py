"""A stored model run with enough test days reads 'no chance test run', not a rule-test word."""

from __future__ import annotations

from alpha_cli import ml_glosses
from alpha_cli.spine import reading

NO_CHANCE = "no chance test run"


def _manifest(days: int) -> dict[str, object]:
    return {
        "metrics": {"total_return": -0.15, "sharpe": -6.5, "psr": 0.0, "dsr": 0.98},
        "n_oos_periods": days,
        "starting_cash": 1_000_000.0,
    }


def test_a_model_run_with_enough_test_days_reads_no_chance_test_run() -> None:
    word, because = ml_glosses.reading_word(_manifest(500))
    assert word == NO_CHANCE
    assert word != reading.NOT_CLEAR
    assert because, "the word comes with a reason"


def test_exactly_one_hundred_test_days_reads_no_chance_test_run() -> None:
    word, _ = ml_glosses.reading_word(_manifest(100))
    assert word == NO_CHANCE


def test_under_one_hundred_test_days_still_reads_too_little() -> None:
    word, because = ml_glosses.reading_word(_manifest(99))
    assert word == reading.TOO_LITTLE == "too little to read"
    assert "99" in " ".join(because)


def test_the_rule_test_words_are_unchanged() -> None:
    assert reading.CLEAR == "clear of chance"
    assert reading.SOME == "some evidence"
    assert reading.NOT_CLEAR == "not clear of chance"
    assert reading.TOO_LITTLE == "too little to read"
    assert reading.MIN_OOS_OBSERVATIONS == 100
