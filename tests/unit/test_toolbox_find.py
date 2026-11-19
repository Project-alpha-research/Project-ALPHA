"""Finding a check from plain words: entry metadata, matching and the situation index."""

import json
import re
from pathlib import Path
from typing import get_args

import pytest
from typer.testing import CliRunner

from alpha_cli.tool_cmds import tool_app
from alpha_cli.toolbox.contract import ToolSpec
from alpha_cli.toolbox.find import INPUT_WORDS, find, index, markdown_index
from alpha_cli.toolbox.registry import SPECS
from alpha_cli.toolbox.sets import SETS
from alpha_cli.toolbox.situations import SITUATIONS, Situation

ROOT = Path(__file__).parents[2]
BEGIN, END = "<!-- situations:begin -->", "<!-- situations:end -->"


def test_situation_list_is_closed_and_defined_once() -> None:
    assert tuple(SITUATIONS) == get_args(Situation)
    assert all(label.strip() for label in SITUATIONS.values())


@pytest.mark.parametrize("spec", SPECS, ids=lambda spec: spec.id)
def test_every_entry_carries_find_metadata(spec: ToolSpec) -> None:
    assert 1 <= len(spec.answers) <= 3, "answers: one to three plain questions"
    assert all(a.endswith("?") and len(a) > 15 for a in spec.answers)
    assert spec.situations and len(set(spec.situations)) == len(spec.situations)
    assert set(spec.situations) <= set(SITUATIONS), "unknown situation tag"
    assert spec.cost in {"instant", "seconds", "minutes"}
    assert spec.needs and set(spec.needs) <= set(INPUT_WORDS)


def _ids(query: str) -> list[str]:
    return [hit.tool_id for hit in find(query)]


def test_drawdown_question_finds_the_drawdown_entries() -> None:
    found = _ids("how bad could drawdown get")
    wanted = {
        "resampling.drawdown_distribution",
        "resampling.block_bootstrap_paths",
        "resampling.student_t_paths",
    }
    assert wanted <= set(found[:4])


@pytest.mark.parametrize("words", ["is this overfit", "looks too good"])
def test_overfit_question_finds_the_overfitting_entries(words: str) -> None:
    found = _ids(words)
    assert {"overfit.deflated_sharpe", "robustness.start_end_dates"} <= set(found)
    assert found.index("overfit.deflated_sharpe") < 4


def test_a_hit_says_what_it_answers_what_it_costs_and_how_to_run_it() -> None:
    hit = find("how bad could drawdown get")[0]
    assert hit.answers and hit.cost in {"instant", "seconds", "minutes"}
    assert hit.command == f"alpha tool run {hit.tool_id} <run_id>"
    members = [name for name, tools in SETS.items() if hit.tool_id in tools]
    assert list(hit.sets) == members
    assert [h.sets for h in find("calm or turbulent")][0] == ("market-context",)


def test_nothing_found_says_so_and_lists_the_situations() -> None:
    assert find("zebra banana") == []
    shown = CliRunner().invoke(tool_app, ["find", "zebra banana"])
    assert shown.exit_code == 0
    assert "No check matches" in shown.stdout
    assert all(label in shown.stdout for label in SITUATIONS.values())
    as_json = json.loads(CliRunner().invoke(tool_app, ["find", "zebra banana", "--json"]).stdout)
    assert as_json["matches"] == [] and set(as_json["situations"]) == set(SITUATIONS)


def test_find_is_deterministic_and_prints_json() -> None:
    first = CliRunner().invoke(tool_app, ["find", "drawdown", "--json"])
    again = CliRunner().invoke(tool_app, ["find", "drawdown", "--json"])
    assert first.stdout == again.stdout
    assert json.loads(first.stdout)["matches"][0]["command"].startswith("alpha tool run ")


def test_situation_index_covers_every_entry_in_a_sensible_order() -> None:
    table = index()
    assert set(table) == set(SITUATIONS)
    assert {s.id for specs in table.values() for s in specs} == {s.id for s in SPECS}
    rank = {"instant": 0, "seconds": 1, "minutes": 2}
    for specs in table.values():
        costs = [rank[s.cost] for s in specs]
        assert costs == sorted(costs), "cheapest first"
    printed = CliRunner().invoke(tool_app, ["situations"]).stdout
    assert "drawdown" in printed and "resampling.drawdown_distribution" in printed
    as_json = json.loads(CliRunner().invoke(tool_app, ["situations", "--json"]).stdout)
    assert set(as_json) == set(SITUATIONS)


def test_card_situation_table_is_the_generated_one() -> None:
    text = (ROOT / "research/tools/toolbox-by-situation.md").read_text()
    block = re.search(f"{BEGIN}\n(.*)\n{END}", text, re.DOTALL)
    assert block, "card needs the generated situations block"
    assert block.group(1) == markdown_index(), "paste `alpha tool situations --markdown`"


OWNER_WORDS = [
    ("is this overfit", {"overfit.deflated_sharpe"}),
    ("looks too good", {"overfit.deflated_sharpe"}),
    ("why big drawdown", {"resampling.drawdown_distribution"}),
    ("only works some years", {"robustness.start_end_dates"}),
    ("is it just the market going up", {"market.attribution"}),
    ("too few trades", set()),
]


@pytest.mark.parametrize(("words", "wanted"), OWNER_WORDS)
def test_owner_words_find_sensible_entries(words: str, wanted: set[str]) -> None:
    hits = find(words)
    assert hits, words
    assert wanted <= {hit.tool_id for hit in hits[:6]}
    if "few trades" in words:
        assert any("few-trades" in hit.situations for hit in hits[:3])


@pytest.mark.parametrize(
    ("words", "command"),
    [
        ("does it hold out of sample", "alpha test"),
        ("would a different data feed change it", "alpha data health"),
    ],
)
def test_situations_without_a_check_point_to_the_command_that_answers(
    words: str, command: str
) -> None:
    shown = CliRunner().invoke(tool_app, ["find", words])
    assert shown.exit_code == 0 and command in shown.stdout
    assert json.loads(CliRunner().invoke(tool_app, ["find", words, "--json"]).stdout)["pointers"]
    assert command in CliRunner().invoke(tool_app, ["situations"]).stdout
