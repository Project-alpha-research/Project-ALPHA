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
