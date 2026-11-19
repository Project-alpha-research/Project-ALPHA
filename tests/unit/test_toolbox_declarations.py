"""Declared before the result, or exploratory: decided by time order, never refused."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.spine.errors import SpineError
from alpha_cli.tool_cmds import tool_app
from alpha_cli.toolbox import declarations, inputs
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN, _series
from tests.unit.test_toolbox_contract import BASELINE, REFERENCE, _assert_close

T0 = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> Callable[[], datetime]:
    return lambda: T0 + timedelta(minutes=minutes)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    series = _series(tmp_path)
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return tmp_path


def test_declared_before_the_result_is_marked_declared(home: Path) -> None:
    declarations.declare(home, RUN, tools=("market.changepoints",), why="plan", now=_at(0))
    doc = run(home, "market.changepoints", RUN, now=_at(5))
    assert "declared" in doc["labels"] and "exploratory" not in doc["labels"]
    assert doc["recorded_at"] == (T0 + timedelta(minutes=5)).isoformat()


def test_declared_after_the_result_stays_exploratory(home: Path) -> None:
    first = run(home, "market.vol_regimes", RUN, now=_at(0))
    declarations.declare(home, RUN, tools=("market.vol_regimes",), now=_at(10))
    assert "exploratory" in first["labels"]
    again = run(home, "market.vol_regimes", RUN, now=_at(20))  # stored answer is reused
    assert again == first


def test_a_declaration_for_another_tool_or_run_does_not_count(home: Path) -> None:
    declarations.declare(home, RUN, tools=("market.attribution",), now=_at(0))
    declarations.declare(home, "fedcba9876543210", tools=("market.changepoints",), now=_at(0))
    assert "exploratory" in run(home, "market.changepoints", RUN, now=_at(1))["labels"]


def test_a_declared_set_names_its_members(home: Path) -> None:
    row = declarations.declare(home, RUN, set_name="market-context", now=_at(0))
    assert row["tools"] == ["market.attribution", "market.vol_regimes", "market.changepoints"]
    doc = run(home, "market.attribution", RUN, now=_at(1))
    assert "declared" in doc["labels"]


def test_declarations_are_append_only_and_timed(home: Path) -> None:
    declarations.declare(home, RUN, tools=("market.changepoints",), why="one", now=_at(0))
    declarations.declare(home, RUN, set_name="market-context", why="two", now=_at(1))
    rows = declarations.read(home, RUN)
    assert [r["why"] for r in rows] == ["one", "two"]
    assert [r["declared_at"] for r in rows] == [_at(0)().isoformat(), _at(1)().isoformat()]


def test_unknown_tool_or_set_is_an_error_and_writes_nothing(home: Path) -> None:
    with pytest.raises(SpineError):
        declarations.declare(home, RUN, tools=("nope.nothing",), now=_at(0))
    with pytest.raises(SpineError):
        declarations.declare(home, RUN, set_name="no-such-set", now=_at(0))
    with pytest.raises(SpineError):
        declarations.declare(home, RUN, now=_at(0))
    assert declarations.read(home, RUN) == []


def test_counts_and_listing(home: Path) -> None:
    declarations.declare(home, RUN, tools=("market.changepoints",), now=_at(0))
    run(home, "market.changepoints", RUN, now=_at(1))
    run(home, "market.vol_regimes", RUN, now=_at(2))
    run(home, "market.attribution", RUN, now=_at(3))
    shown = CliRunner().invoke(tool_app, ["results", RUN, "--json"])
    payload = json.loads(shown.stdout)
    assert payload["counts"] == {
        "total": 3,
        "declared": 1,
        "exploratory": 2,
        "text": "3 checks run on this result: 1 declared, 2 exploratory",
    }
    status = {item["tool"]: item["status"] for item in payload["results"]}
    assert status["market.changepoints"] == "declared"
    assert status["market.vol_regimes"] == "exploratory"
    text = CliRunner().invoke(tool_app, ["results", RUN]).stdout
    assert "3 checks run on this result: 1 declared, 2 exploratory" in text
    assert "exploratory" in text
    from alpha_cli.results_cmds import results_app

    report = json.loads(CliRunner().invoke(results_app, ["show", RUN, "--json"]).stdout)
    run_json = report["runs"][0]
    assert run_json["tool_counts"]["text"].startswith("3 checks run on this result")
    assert {t["status"] for t in run_json["tools"]} == {"declared", "exploratory"}


def test_declare_command_writes_before_results(home: Path) -> None:
    done = CliRunner().invoke(
        tool_app,
        ["declare", RUN, "--tools", "market.changepoints,market.attribution", "--why", "x"],
    )
    assert done.exit_code == 0, done.output
    assert "Declared before any result" in done.stdout
    both = CliRunner().invoke(tool_app, ["declare", RUN, "--set", "market-context", "--tools", "a"])
    assert both.exit_code != 0
    assert "declared" in run(home, "market.changepoints", RUN)["labels"]


def test_values_and_result_ids_do_not_depend_on_a_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = {}
    for name, declare_first in (("plain", False), ("declared", True)):
        home = tmp_path / name
        series = _series(home)
        series = replace(
            series, positions=tuple(i // 25 % 2 == 0 for i in range(len(series.dates)))
        )
        monkeypatch.setattr(inputs, "load_run", lambda home, run_id, s=series: s)
        if declare_first:
            declarations.declare(home, RUN, set_name="market-context", now=_at(0))
        docs[name] = {t: run(home, t, RUN, now=_at(1)) for t in BASELINE}
    for tool, key in BASELINE.items():
        plain, declared = docs["plain"][tool], docs["declared"][tool]
        _assert_close(plain["result"], REFERENCE[key], tool)
        _assert_close(declared["result"], REFERENCE[key], tool)
        assert plain["file"] == declared["file"] and plain["cache_key"] == declared["cache_key"]
        assert plain["values"] == declared["values"] and plain["reading"] == declared["reading"]
        assert "exploratory" in plain["labels"] and "declared" in declared["labels"]
        others = [
            [w for w in doc["labels"] if w not in {"declared", "exploratory"}]
            for doc in (plain, declared)
        ]
        assert others[0] == others[1]
