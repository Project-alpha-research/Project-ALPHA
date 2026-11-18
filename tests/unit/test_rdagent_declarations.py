"""The proposer must supply an unambiguous direction and primary clock."""

from __future__ import annotations

import pytest

from tests.unit._rdagent_support import judge_namespace
from workers.rdagent.idea_families import declaration


def test_declaration_prompt_has_no_filled_choice() -> None:
    template = judge_namespace()["DECLARATION_TEMPLATE"]
    assert "declared_direction: <+1 or -1>" in template
    assert "primary_clock: <weekly or monthly>" in template
    assert "direction_reason: <one sentence of economic reasoning>" in template
    assert "follow from the idea" in template
    with pytest.raises(ValueError):
        declaration(template)


@pytest.mark.parametrize("direction,clock", [("+1 or -1", "weekly"), ("+1", "weekly or monthly")])
def test_ambiguous_declarations_still_refused(direction: str, clock: str) -> None:
    with pytest.raises(ValueError):
        declaration(
            f"declared_direction: {direction}; primary_clock: {clock}; "
            "direction_reason: Demand persists."
        )
