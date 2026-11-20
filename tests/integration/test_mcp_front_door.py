"""The front-door tools run the REAL `alpha` command on a synthetic home."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from alpha_mcp import front_door_tools


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_next_step_on_an_empty_home(home: Path) -> None:
    result = front_door_tools.next_step()
    assert result["ideas"] == {"cards": 0, "without_test": 0}
    assert "paths" in result


def test_idea_list_sees_a_card_made_by_the_cli(home: Path) -> None:
    made = subprocess.run(
        [shutil.which("alpha") or "alpha", "idea", "new", "--claim", "Gaps fill", "--json"],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": os.environ["PATH"], "ALPHA_DATA_DIR": str(home)},
    )
    assert made.returncode == 0
    cards = front_door_tools.idea_list()["cards"]
    assert len(cards) == 1
    card_id = cards[0]["id"]
    assert front_door_tools.idea_show(card_id)
    assert front_door_tools.idea_file(card_id)


def test_idea_new_through_the_tool_writes_one_note(home: Path) -> None:
    saved = front_door_tools.idea_new(claim="Overnight drift")
    assert saved["created"] is True
    assert len(front_door_tools.idea_list()["cards"]) == 1


def test_an_unknown_card_returns_the_command_error_json(home: Path) -> None:
    result = front_door_tools.idea_show("abcd")
    assert result["error"]["code"] == "IDEA_CARD_UNKNOWN"
    assert result["error"]["next"]


def test_library_list_and_show(home: Path) -> None:
    listed = front_door_tools.library_list()
    assert listed["records"]
    first = listed["records"][0]["id"]
    assert front_door_tools.library_show(first)
    assert front_door_tools.library_list(market="crypto", tier="all")["records"]


def test_tool_find_and_situations(home: Path) -> None:
    found = front_door_tools.tool_find("the result looks too good")
    assert found["query"] == "the result looks too good"
    assert front_door_tools.tool_situations()


def test_follow_today_and_list_on_an_empty_home(home: Path) -> None:
    today = front_door_tools.follows_today()
    assert today["rows"] == []
    assert today["paper"] is True
    assert front_door_tools.follows_list() == {"follows": []}
    assert front_door_tools.follows_show("abcd")["error"]["code"] == "FOLLOW_UNKNOWN"


def test_nightly_status_on_an_empty_home(home: Path) -> None:
    status = front_door_tools.nightly_status()
    assert status["ready"] is False
    assert status["records"] == 0
