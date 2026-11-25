"""A model run reads in plain words: a reading word, who won, glossed numbers, held-back bars."""

from __future__ import annotations

import pytest

from alpha_cli import ml_glosses
from alpha_cli.spine import reading

METRICS = {
    "total_return": -0.1544,
    "gross_total_return": 0.055,
    "benchmark_total_return": 0.0427,
    "costed_excess_total_return": -0.1971,
    "max_drawdown": -0.1548,
    "mean_turnover": 1.6111,
    "total_fees": 67557.2466,
    "total_slippage_cost": 135114.4952,
    "sharpe": -6.5089,
    "annualized_volatility": 0.0142,
    "cagr": -0.0883,
    "psr": 0.0,
    "dsr": 0.9784,
}


def _manifest(**metrics: float | None) -> dict[str, object]:
    return {"metrics": {**METRICS, **metrics}, "n_oos_periods": 500, "starting_cash": 1_000_000.0}


def test_the_reading_uses_the_no_chance_test_word() -> None:
    word, because = ml_glosses.reading_word(_manifest())
    assert word == ml_glosses.NO_CHANCE
    assert "random-data" in " ".join(because)


def test_too_few_test_days_read_too_little() -> None:
    word, because = ml_glosses.reading_word({**_manifest(), "n_oos_periods": 40})
    assert word == reading.TOO_LITTLE
    assert "40" in " ".join(because)


def test_a_model_that_trails_the_basket_says_so() -> None:
    assert ml_glosses.versus_basket(_manifest()) == (
        "The model returned less than holding the basket."
    )
    ahead = _manifest(
        total_return=0.1, benchmark_total_return=0.04, costed_excess_total_return=0.06
    )
    assert ml_glosses.versus_basket(ahead) == "The model returned more than holding the basket."
    level = _manifest(
        total_return=0.04, benchmark_total_return=0.04, costed_excess_total_return=0.0
    )
    assert ml_glosses.versus_basket(level) == "The model returned the same as holding the basket."


def test_a_missing_excess_never_reads_as_ahead_or_behind() -> None:
    assert ml_glosses.versus_basket(_manifest(costed_excess_total_return=None)) is None


def test_no_printed_number_keeps_its_raw_name() -> None:
    text = "\n".join(ml_glosses.number_lines(_manifest()))
    for raw in ("costed_excess_total_return", "dsr=", "psr=", "annualized_volatility"):
        assert raw not in text
    assert "-15.4%" in text and "-19.7" in text
    assert "0.98" in text
    for line in ml_glosses.number_lines(_manifest()):
        assert "(" in line and line.endswith(")."), line  # each number has a few words of gloss


def test_a_missing_number_is_not_shown_as_a_value() -> None:
    text = "\n".join(ml_glosses.number_lines(_manifest(sharpe=None, dsr=None)))
    assert "not computed" in text
    assert "Sharpe None" not in text and "nan" not in text.lower()


@pytest.mark.parametrize(
    ("held", "assets", "words"),
    [
        (2160, 20, "108 bars for each of 20 assets"),
        (14468, 20, "about 723 bars for each of 20 assets"),
    ],
)
def test_held_back_bars_are_counted_per_asset(held: int, assets: int, words: str) -> None:
    said = ml_glosses.held_back_sentence(
        {"reserved_start": "2024-01-01", "held_back_bars": held}, assets
    )
    assert words in said
    assert "2024-01-01" in said and str(held) not in said
