"""Holm correction over one immutable, preregistered secondary family."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from alpha_core import DataError
from alpha_research import (
    FrozenSecondaryFamily,
    SecondaryHypothesis,
    holm_adjust_secondary_family,
)


def test_holm_adjustment_preserves_registered_order_and_controls_family() -> None:
    family = FrozenSecondaryFamily(
        family_id="secondary-outcomes-v1",
        alpha=0.05,
        hypotheses=(
            SecondaryHypothesis("one-day", 0.01),
            SecondaryHypothesis("five-day", 0.04),
            SecondaryHypothesis("ten-day", 0.03),
        ),
    )

    adjusted = holm_adjust_secondary_family(family)

    assert [item.hypothesis_id for item in adjusted] == ["one-day", "five-day", "ten-day"]
    assert [item.adjusted_p_value for item in adjusted] == pytest.approx([0.03, 0.06, 0.06])
    assert [item.rejected for item in adjusted] == [True, False, False]
    assert family.contract_hash == family.contract_hash


def test_holm_ties_are_deterministic_and_monotone() -> None:
    family = FrozenSecondaryFamily(
        family_id="tie-family",
        alpha=0.05,
        hypotheses=(
            SecondaryHypothesis("b", 0.01),
            SecondaryHypothesis("a", 0.01),
            SecondaryHypothesis("c", 0.20),
        ),
    )

    first = holm_adjust_secondary_family(family)
    second = holm_adjust_secondary_family(family)

    assert first == second
    by_id = {item.hypothesis_id: item for item in first}
    assert by_id["a"].adjusted_p_value == pytest.approx(0.03)
    assert by_id["b"].adjusted_p_value == pytest.approx(0.03)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SecondaryHypothesis("", 0.01),
        lambda: SecondaryHypothesis("bad", float("nan")),
        lambda: SecondaryHypothesis("bad", 1.1),
        lambda: FrozenSecondaryFamily("", (SecondaryHypothesis("a", 0.1),)),
        lambda: FrozenSecondaryFamily("family", ()),
        lambda: FrozenSecondaryFamily(
            "family",
            (SecondaryHypothesis("same", 0.1), SecondaryHypothesis("same", 0.2)),
        ),
        lambda: FrozenSecondaryFamily("family", (SecondaryHypothesis("a", 0.1),), alpha=0.5),
    ],
)
def test_frozen_secondary_family_rejects_malformed_input(factory: Callable[[], object]) -> None:
    with pytest.raises(DataError):
        factory()


_ONE = (SecondaryHypothesis("a", 0.1),)
_ID = "SecondaryHypothesis.hypothesis_id must be non-empty"
_P = "SecondaryHypothesis.p_value must be finite in [0, 1]"
_FAMILY_ID = "FrozenSecondaryFamily.family_id must be non-empty"
_TUPLE = "FrozenSecondaryFamily.hypotheses must be a non-empty tuple"
_ALPHA = "FrozenSecondaryFamily.alpha must be finite in (0, 0.5)"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: SecondaryHypothesis("   ", 0.01), _ID),
        (lambda: SecondaryHypothesis(cast(str, 7), 0.01), _ID),
        (lambda: SecondaryHypothesis("a", -0.01), _P),
        (lambda: SecondaryHypothesis("a", float("inf")), _P),
        (lambda: FrozenSecondaryFamily("  ", _ONE), _FAMILY_ID),
        (lambda: FrozenSecondaryFamily(cast(str, 3), _ONE), _FAMILY_ID),
        (
            lambda: FrozenSecondaryFamily("f", cast(tuple[SecondaryHypothesis, ...], list(_ONE))),
            _TUPLE,
        ),
        (lambda: FrozenSecondaryFamily("f", ()), _TUPLE),
        (
            lambda: FrozenSecondaryFamily("f", (*_ONE, SecondaryHypothesis("a", 0.2))),
            "secondary hypothesis IDs must be unique within the frozen family",
        ),
        (lambda: FrozenSecondaryFamily("f", _ONE, alpha=0.0), _ALPHA),
        (lambda: FrozenSecondaryFamily("f", _ONE, alpha=float("nan")), _ALPHA),
    ],
)
def test_malformed_input_fails_with_its_exact_message(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(DataError) as caught:
        factory()
    assert str(caught.value) == message


def test_boundary_values_are_accepted_and_the_contract_is_exact() -> None:
    family = FrozenSecondaryFamily(
        "edges",
        (SecondaryHypothesis("zero", 0.0), SecondaryHypothesis("one", 1.0)),
        alpha=0.49,
    )
    assert family.to_dict() == {
        "alpha": 0.49,
        "family_id": "edges",
        "hypotheses": [
            {"hypothesis_id": "zero", "p_value": 0.0},
            {"hypothesis_id": "one", "p_value": 1.0},
        ],
        "method": "holm",
        "schema_version": 1,
    }


def test_an_adjusted_value_equal_to_alpha_is_rejected() -> None:
    family = FrozenSecondaryFamily("equal", (SecondaryHypothesis("only", 0.05),), alpha=0.05)
    (result,) = holm_adjust_secondary_family(family)
    assert result.adjusted_p_value == 0.05
    assert result.rejected is True
