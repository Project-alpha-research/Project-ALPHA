"""The toolbox is found by the trader's question: plain words reach the checks that answer them."""

import pytest

from alpha_cli.toolbox.find import find
from alpha_cli.toolbox.registry import SPECS
from alpha_cli.toolbox.situations import QUESTIONS, SITUATIONS

IDS = {spec.id for spec in SPECS}


def test_every_question_names_registered_checks_and_has_a_label() -> None:
    for tag, ids in QUESTIONS.items():
        assert tag in SITUATIONS
        assert len(ids) >= 3 and len(set(ids)) == len(ids)
        assert set(ids) <= IDS, set(ids) - IDS


def test_the_registry_tags_each_check_with_its_questions() -> None:
    for spec in SPECS:
        for tag, ids in QUESTIONS.items():
            assert (tag in spec.situations) == (spec.id in ids)


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("how much should I bet on each trade", "risk.kelly"),
        ("how big can the loss on one day get", "risk.parametric_var"),
        ("is there enough history to trust the sharpe", "overfit_controls.min_track_record"),
        ("do returns trend or reverse", "timeseries.variance_ratio"),
        ("does it work on mondays", "regimes.day_of_week"),
        ("would real spreads and taxes change the result", "cost_realism.after_tax"),
        ("could I trade a bigger size", "cost_realism.capacity_curve"),
    ],
)
def test_plain_words_reach_the_check(words: str, expected: str) -> None:
    assert expected in [hit.tool_id for hit in find(words)][:10]


def test_every_situation_label_finds_every_check_that_carries_the_tag() -> None:
    for spec in SPECS:
        for tag in spec.situations:
            assert spec.id in {hit.tool_id for hit in find(SITUATIONS[tag])}, (spec.id, tag)
