"""An idea-card link is a label on a run, not part of the test.

The recheck and the final check compare the test, never the link: a run written with a card
rechecks the same with or without the card typed again, and its final check is not blocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_cli.spine import idea_card
from alpha_cli.spine.confirm_run import confirm_run
from alpha_cli.spine.recheck import recheck_idea
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec, load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def _spec(card: str = "") -> IdeaSpec:
    return load_spec(
        None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"], idea_card=card
    )


@pytest.fixture
def carded(tmp_path: Path) -> tuple[Path, str, str]:
    seed_store(tmp_path, symbol="SPY", n=1600)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    card, _ = idea_card.save(tmp_path, idea_card.IdeaCard(claim="Trends persist for weeks."))
    out = run_idea(_spec(card), home=tmp_path, quick=True, no_diagnose=True)["results"][0]
    assert out["error"] is None, out
    return tmp_path, card, str(out["run_id"])


@pytest.mark.parametrize("typed", [False, True])
def test_recheck_of_a_carded_run_matches_with_or_without_the_card(
    carded: tuple[Path, str, str], typed: bool
) -> None:
    home, card, run_id = carded
    spec = _spec(card if typed else "")
    found = recheck_idea(spec, home=home, quick=True, no_diagnose=True)["results"][0]["recheck"]
    assert found["compared_with"] == run_id
    assert found["differences"] == []
    assert found["match"] is True


def test_the_final_check_of_a_carded_run_is_not_blocked(carded: tuple[Path, str, str]) -> None:
    home, _, run_id = carded
    output = confirm_run(home, run_id)
    assert output["confirmed_run_id"] == run_id and output["slot"] == 1
