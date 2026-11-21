"""The Workstation states a stored owner rule in one plain sentence, from the stored JSON only."""

from __future__ import annotations

from typing import Any

import pytest

from alpha_web._owner_rule_words import owner_rule_sentence as _sentence


def owner_rule_sentence(spec: Any) -> str:
    sentence = _sentence(spec)
    assert sentence is not None
    return sentence


CLOSE = {"source": "close"}


def _spec(*conditions: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "name": "owner-rule",
        "history": 300,
        "long_when": list(conditions),
        "short_when": [],
    }


def _cond(left: dict[str, Any], op: str, right: dict[str, Any]) -> dict[str, Any]:
    return {"left": left, "op": op, "right": right}


def test_the_brief_example_reads_in_plain_words() -> None:
    spec = _spec(
        _cond({"indicator": "rsi", "params": [14]}, "<", {"value": 30}),
        _cond(CLOSE, ">", {"indicator": "sma", "params": [200]}),
    )
    assert owner_rule_sentence(spec) == (
        "Buy at the next open when the 14-day RSI is below 30 "
        "and the close is above the 200-day average. "
        "Sell at the next open when that stops being true. Long or flat."
    )


@pytest.mark.parametrize(
    ("op", "words"),
    [(">", "is above"), ("<", "is below"), (">=", "is at or above"), ("<=", "is at or below")],
)
def test_every_operator_has_words(op: str, words: str) -> None:
    sentence = owner_rule_sentence(_spec(_cond(CLOSE, op, {"value": 5})))
    assert f"the close {words} 5" in sentence


@pytest.mark.parametrize(
    ("operand", "words"),
    [
        ({"source": "high"}, "the high"),
        ({"source": "low", "lag": 3}, "the low 3 days ago"),
        ({"source": "close", "lag": 1}, "the close 1 day ago"),
        ({"value": 2.5}, "2.5"),
        ({"indicator": "sma", "params": [20]}, "the 20-day average"),
        ({"indicator": "ema", "params": [12]}, "the 12-day exponential average"),
        ({"indicator": "rsi", "params": [14]}, "the 14-day RSI"),
        ({"indicator": "atr", "params": [10]}, "the 10-day ATR"),
        (
            {"indicator": "bbands", "params": [20, 2], "field": "upper"},
            "the upper Bollinger band (20 days, 2 deviations)",
        ),
        (
            {"indicator": "bbands", "params": [20, 2.5], "field": "lower"},
            "the lower Bollinger band (20 days, 2.5 deviations)",
        ),
        (
            {"indicator": "bbands", "params": [20, 2], "field": "middle"},
            "the middle Bollinger band (20 days, 2 deviations)",
        ),
        (
            {"indicator": "macd", "params": [12, 26, 9], "field": "line"},
            "the MACD line (12, 26, 9)",
        ),
        (
            {"indicator": "macd", "params": [12, 26, 9], "field": "signal"},
            "the MACD signal line (12, 26, 9)",
        ),
        (
            {"indicator": "macd", "params": [12, 26, 9], "field": "histogram"},
            "the MACD histogram (12, 26, 9)",
        ),
        (
            {"indicator": "hawkes", "params": [0.1, 50]},
            "the Hawkes activity measure (decay 0.1, 50 days)",
        ),
        (
            {"indicator": "cmma", "params": [20, 168]},
            "the close minus the 20-day average, scaled by the 168-day ATR",
        ),
        ({"indicator": "runs_z", "params": [30]}, "the 30-day runs z-score"),
        (
            {"indicator": "perm_entropy", "params": [3, 10]},
            "the permutation entropy (order 3, 10 times 6 patterns)",
        ),
        (
            {"indicator": "vg_path", "params": [30], "field": "price"},
            "the 30-day visibility-graph path length on price",
        ),
        (
            {"indicator": "vg_path", "params": [30], "field": "inverse"},
            "the 30-day visibility-graph path length on inverted price",
        ),
        ({"indicator": "reversibility", "params": [40]}, "the 40-day time reversibility"),
    ],
)
def test_every_operand_has_words(operand: dict[str, Any], words: str) -> None:
    sentence = owner_rule_sentence(_spec(_cond(operand, ">", {"value": 1})))
    assert f"when {words} is above 1." in sentence
    assert "not yet described" not in sentence


@pytest.mark.parametrize(
    "operand",
    [
        {"indicator": "vsa", "params": [20]},
        {"indicator": "sma", "params": [20, 5]},
        {"indicator": "rsi"},
        {"source": "open"},
        {"mystery": 1},
        "close",
    ],
)
def test_an_unknown_operand_shows_its_stored_text(operand: Any) -> None:
    import json

    sentence = owner_rule_sentence(_spec(_cond(operand, ">", {"value": 1})))
    assert f"{json.dumps(operand, sort_keys=True)} (not yet described)" in sentence


def test_an_unknown_operator_shows_its_stored_text() -> None:
    sentence = owner_rule_sentence(_spec(_cond(CLOSE, "crosses", {"value": 1})))
    assert '"crosses" (not yet described)' in sentence


def test_a_condition_that_is_not_an_object_is_shown_as_stored() -> None:
    sentence = owner_rule_sentence({**_spec(), "long_when": ["close>1"]})
    assert '"close>1" (not yet described)' in sentence


def test_a_stored_short_side_is_named_not_run() -> None:
    spec = _spec(_cond(CLOSE, ">", {"value": 1}))
    spec["short_when"] = [_cond(CLOSE, "<", {"value": 1})]
    assert "stored short side" in owner_rule_sentence(spec)


def test_no_buy_conditions_is_said_not_guessed() -> None:
    assert owner_rule_sentence(_spec()) == "The stored rule has no buy conditions. Long or flat."


@pytest.mark.parametrize("spec", [None, "text", [], {}, {"long_when": "x"}])
def test_no_stored_spec_gives_none(spec: Any) -> None:
    assert _sentence(spec) is None
