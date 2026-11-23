"""The tries paragraph says what each count is and why they differ."""

from __future__ import annotations

from alpha_cli.spine.tries import reading_count_sentence

FAMILY = {
    "n_trials_used": 12,
    "this_run": 1,
    "variants_scored": 5,
    "unknown_rows": 0,
    "prior_trials": 6,
    "same_asset_tests": 4,
    "family_id": "spine:ma_cross",
}


def test_each_count_says_what_it_counts() -> None:
    text = reading_count_sentence(dict(FAMILY), "SPY")
    assert text is not None
    assert "5 ideas on SPY, counting this asset alone" in text
    assert "7 times across all assets, which can be more than the first count" in text
    assert "plus 5 nearby settings tried inside this test" in text
    assert text.endswith("plus the nearby settings: 12.")


def _reading(word: str, because: list[str], sharpe: float, lower: float, dsr: float) -> dict:
    return {
        "sentence": "x.",
        "evidence": {"word": word, "because": because},
        "measures": [
            {"name": "out-of-sample Sharpe", "value": sharpe, "interval_95": [lower, 2.0]},
            {"name": "deflated Sharpe", "value": dsr, "interval_95": None},
        ],
    }


def test_the_bridge_names_the_random_price_tests_when_they_decided() -> None:
    from alpha_cli.spine.reading import deciding_sentence

    found = _reading(
        "not clear of chance",
        ["Random-data tests held: 1 of 3.", "Sharpe interval 0.10 to 2.00 (95%)."],
        1.0,
        0.1,
        0.999,
    )
    text = deciding_sentence(found)
    assert text is not None
    assert "random-price tests" in text and "1 of 3" in text
    assert "deflated Sharpe" not in text


def test_the_bridge_names_the_trade_count_when_it_decided() -> None:
    from alpha_cli.spine.reading import deciding_sentence

    found = _reading(
        "too little to read", ["8 closed trades (fewer than 30 make too few to judge)."], 1, 1, 1
    )
    assert deciding_sentence(found) == (
        "What decided it: 8 closed trades (fewer than 30 make too few to judge)."
    )


def test_the_bridge_is_absent_for_a_reading_without_evidence() -> None:
    from alpha_cli.spine.reading import deciding_sentence

    assert deciding_sentence({"sentence": "x."}) is None
