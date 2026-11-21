"""`alpha research compare` holds the reserved period back, as the other search commands do."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.research_cmds import research_app
from alpha_cli.spine.reserve import sentence
from alpha_core.reserve import RESERVED_START
from alpha_web.api.models.research_hub import ResearchReport
from tests.fixtures.reserve_read_fixtures import (
    HELD,
    LONG,
    SHORT,
    Spy,
    watch_loaders,
    write_store,
)

SENTENCE = f"Held back {HELD} bars from {RESERVED_START} on"
ARGS = ["compare", "SPY", "--strategies", "ts_momentum,ma_crossover"]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    return watch_loaders(monkeypatch)


def _compare(home: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> str:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = CliRunner().invoke(research_app, [*ARGS, *extra])
    assert result.exit_code == 0, result.output
    return result.output


def _payload(home: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_compare(home, monkeypatch, "--json"))
    return loaded


def test_compare_reads_no_held_back_bar_and_equals_the_cut_store(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, cut = tmp_path / "poisoned", tmp_path / "cut"
    write_store(poisoned, LONG, poisoned=True)
    write_store(cut, SHORT, poisoned=False)
    held = _payload(poisoned, monkeypatch)
    spy.assert_nothing_from_the_reserved_day()
    plain = _payload(cut, monkeypatch)
    for key in ("symbol", "n_bars", "ranked", "preferred_strategy", "comparison_status"):
        assert held[key] == plain[key], key
    assert held["n_bars"] == SHORT


def test_compare_names_what_it_held_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "poisoned"
    write_store(home, LONG, poisoned=True)
    payload = _payload(home, monkeypatch)
    assert payload["reserve"] == {"reserved_start": RESERVED_START, "held_back_bars": HELD}
    assert payload["research_cutoff"] == "2023-12-31"
    assert payload["reserve_sentence"] == sentence(HELD)
    text = _compare(home, monkeypatch)
    assert SENTENCE in text and "Held back" in text


def test_compare_with_nothing_to_hold_back_says_nothing_and_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "cut"
    write_store(home, SHORT, poisoned=False)
    payload = _payload(home, monkeypatch)
    assert "reserve" not in payload and "reserve_sentence" not in payload
    assert "research_cutoff" not in payload
    assert "Held back" not in _compare(home, monkeypatch)


def test_the_workstation_report_model_accepts_the_held_back_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "poisoned"
    write_store(home, LONG, poisoned=True)
    report = ResearchReport.model_validate(_payload(home, monkeypatch))
    assert report.reserve == {"reserved_start": RESERVED_START, "held_back_bars": HELD}
    assert report.reserve_sentence == sentence(HELD)
