"""`alpha follow update` after new bars are appended to the store: each appended session is
booked exactly once, and a second run books nothing. Synthetic store, injected clock."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import follow_cmds, follow_store
from alpha_cli.main import app
from tests.fixtures.follow_fixtures import DAYS, F0, World


def _update(home: Path, follow: str) -> None:
    result = CliRunner().invoke(
        app, ["follow", "update", follow], env={"ALPHA_DATA_DIR": str(home)}
    )
    assert result.exit_code == 0, result.output


def _booked(home: Path, follow: str) -> list[str]:
    return [e.session_date.isoformat() for e in follow_store.entries_of(home, follow)[1:]]


def test_appended_bars_are_booked_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World(tmp_path, -0.2, [3.0, 3.0, 3.0, -8.0, -8.0, -8.0])
    follow = world.start()
    now: list[datetime] = [world.close_of(0)]
    monkeypatch.setattr(follow_cmds, "CLOCK", lambda: now[0])
    assert _booked(tmp_path, follow) == []
    for _ in range(2):  # two new sessions arrive at once
        world.grow()
    now[0] = world.close_of(1)
    _update(tmp_path, follow)
    first = [DAYS[F0 + k].isoformat() for k in range(2)]
    assert _booked(tmp_path, follow) == first
    _update(tmp_path, follow)  # nothing new: nothing booked
    assert _booked(tmp_path, follow) == first
    for _ in range(3):
        world.grow()
    now[0] = world.close_of(4)
    _update(tmp_path, follow)
    _update(tmp_path, follow)
    assert _booked(tmp_path, follow) == [DAYS[F0 + k].isoformat() for k in range(5)]
    kinds = [e.kind for e in follow_store.entries_of(tmp_path, follow)[1:]]
    # A session written after the next session's open is "missed"; the newest one is a bar.
    assert kinds == ["missed", "bar", "missed", "missed", "bar"]
