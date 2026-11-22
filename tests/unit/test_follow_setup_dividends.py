"""A followed setup trade books a cash dividend on the rule follow's point-in-time basis.

The event at bar 120 buys at the open of 121 and the target sells on 122. Only a dividend with its
ex date on 122 is owed: units are held before that open. Ex on 121 (the buy fills at that open)
and ex on 123 (after the sale) are not. Synthetic store; injected clock.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest

from alpha_cli import follow_source, follow_store, follow_update
from alpha_core import ActionType, CorporateAction
from alpha_data.store import ParquetStore
from tests.fixtures.follow_setup_fixtures import START, START_BAR, clock_after, day_of, make_study


def _dividend(i: int) -> CorporateAction:
    return CorporateAction(
        symbol="SPY",
        action_type=ActionType.DIVIDEND,
        ex_date=day_of(i),
        announce_date=day_of(i - 5),
        pay_date=day_of(i),
        amount=0.5,
    )


def test_a_setup_follow_books_only_the_dividend_of_a_held_session(tmp_path: Path) -> None:
    study = make_study(tmp_path)
    ParquetStore(tmp_path / "store").write_actions(
        "SPY", [_dividend(121), _dividend(122), _dividend(123)]
    )
    source = follow_source.setup_trade_source(tmp_path, study["trade_id"], "")
    follow = str(
        follow_store.start_follow(tmp_path, source, card="", size_pct=10.0, clock=lambda: START)[
            "follow_id"
        ]
    )
    for i in range(START_BAR, 126):
        follow_update.update_follow(tmp_path, follow, clock=partial(clock_after, i))
    entries = {e.session_date: e.payload for e in follow_store.entries_of(tmp_path, follow)[1:]}
    held = entries[day_of(121)]["book"]["units"]
    assert held > 0 and entries[day_of(122)]["book"]["units"] == 0
    paid = [(day, d) for day, p in entries.items() for d in p["dividends"]]
    assert [day for day, _ in paid] == [day_of(122)]
    assert paid[0][1]["cash"] == pytest.approx(held * 0.5, rel=1e-9, abs=1e-12)
    assert entries[day_of(125)]["book"]["dividends_cum"] == pytest.approx(held * 0.5)
