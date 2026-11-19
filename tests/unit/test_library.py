"""The library of published ideas: records, the private overlay, and `alpha library card`."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.spine import idea_card as cards
from alpha_cli.spine import library
from alpha_cli.spine.errors import SpineError

RUNNER = CliRunner()
PUBLIC = Path(__file__).resolve().parents[2] / "research" / "library" / "published"
PRIVATE_RECORD = """
id = "my-own-note"
name = "My own note"
year_published = 2020
market = "us-equities"
idea = "Stocks that gap down on no news tend to close the gap."
mechanism_claimed = "My own reading: thin early trading overreacts."
data_needed = ["daily bars"]
direction = "long"
holding_clock = "days"
decay_evidence = "none found"
can_test_today = "yes - daily bars are held"
notes = "Private."

[source]
authors = "Me"
year = 2020
title = "My note"
venue = "private"
url = "https://example.org/mine"
"""


def _cli(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, ["library", *args], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def _private(home: Path, text: str = PRIVATE_RECORD) -> None:
    folder = home / "library" / "private"
    folder.mkdir(parents=True)
    (folder / "my-own-note.toml").write_text(text, encoding="utf-8")


def test_every_public_record_passes_the_schema() -> None:
    files = sorted(PUBLIC.glob("*.toml"))
    assert 20 <= len(files) <= 30
    for path in files:
        record = library.load_record(path)
        assert record.id == path.stem
        assert record.source.url.startswith("https://")
        assert 1960 <= record.year_published <= 2026
        assert len(record.idea) <= 300 and len(record.mechanism_claimed) <= 500


def test_an_unknown_key_fails_the_schema(tmp_path: Path) -> None:
    path = tmp_path / "my-own-note.toml"
    path.write_text(PRIVATE_RECORD + 'abstract = "copied text"\n', encoding="utf-8")
    with pytest.raises(SpineError) as caught:
        library.load_record(path)
    assert caught.value.payload["code"] == "LIBRARY_RECORD_INVALID"


def test_a_bad_market_or_a_wrong_file_name_fails(tmp_path: Path) -> None:
    path = tmp_path / "my-own-note.toml"
    path.write_text(PRIVATE_RECORD.replace("us-equities", "bonds"), encoding="utf-8")
    with pytest.raises(SpineError):
        library.load_record(path)
    other = tmp_path / "other.toml"
    other.write_text(PRIVATE_RECORD, encoding="utf-8")
    with pytest.raises(SpineError):
        library.load_record(other)


def test_no_record_claims_money_or_quotes_at_length() -> None:
    banned = re.compile(r"guarantee|will make money|risk-free|profitable strategy", re.I)
    for path in PUBLIC.glob("*.toml"):
        text = path.read_text(encoding="utf-8")
        assert not banned.search(text), path.name
        assert "abstract" not in tomllib.loads(text)


def test_list_prints_the_map_line_once_and_filters_by_market(tmp_path: Path) -> None:
    code, output = _cli(tmp_path, "list")
    assert code == 0
    assert output.count("starting map, not a claim") == 1
    code, output = _cli(tmp_path, "list", "--market", "crypto", "--json")
    rows = json.loads(output)["records"]
    assert code == 0 and rows and {row["market"] for row in rows} == {"crypto"}
    code, output = _cli(tmp_path, "list", "--market", "bonds")
    assert code == 1


def test_the_private_overlay_is_read_and_marked(tmp_path: Path) -> None:
    _private(tmp_path)
    code, output = _cli(tmp_path, "list", "--json")
    rows = {row["id"]: row for row in json.loads(output)["records"]}
    assert code == 0
    assert rows["my-own-note"]["origin"] == "private"
    assert rows["time-series-momentum"]["origin"] == "public"
    code, text = _cli(tmp_path, "list")
    assert any("private" in line and "my-own-note" in line for line in text.splitlines())
    code, shown = _cli(tmp_path, "show", "my-own-note")
    assert code == 0 and "private" in shown


def test_a_private_note_cannot_reuse_a_public_id(tmp_path: Path) -> None:
    folder = tmp_path / "library" / "private"
    folder.mkdir(parents=True)
    text = PRIVATE_RECORD.replace("my-own-note", "time-series-momentum")
    (folder / "time-series-momentum.toml").write_text(text, encoding="utf-8")
    code, output = _cli(tmp_path, "list")
    assert code == 1 and "time-series-momentum" in output


def test_show_names_the_decay_evidence_and_the_data_gap(tmp_path: Path) -> None:
    code, output = _cli(tmp_path, "show", "cross-sectional-momentum")
    assert code == 0
    for label in ("Idea", "Why the authors say it works", "Decay evidence", "Can test today"):
        assert label in output
    assert "No idea card was made from this record yet." in output
    code, output = _cli(tmp_path, "show", "no-such-record")
    assert code == 1 and "alpha library list" in output


def test_card_fills_the_card_and_writes_nothing_else(tmp_path: Path) -> None:
    code, output = _cli(tmp_path, "card", "short-term-reversal", "--json")
    assert code == 0, output
    made = json.loads(output)
    card = cards.load(tmp_path, made["card"])
    record = library.load_record(PUBLIC / "short-term-reversal.toml")
    assert record.idea in card.claim
    assert f"from library record {record.id}, published {record.year_published}" in card.claim
    assert card.mechanism == record.mechanism_claimed
    assert card.held_for == record.holding_clock
    assert card.disproved_by == "" and card.baseline == ""
    assert {"disproved_by", "baseline"} <= set(card.not_stated())
    assert not (tmp_path / "ideas" / cards.LINKS_FILE).exists()
    assert not list(tmp_path.rglob("*.sqlite*")) and not (tmp_path / "ledger").exists()


def test_card_twice_is_one_card_and_show_lists_it_with_its_tests(tmp_path: Path) -> None:
    first = json.loads(_cli(tmp_path, "card", "short-term-reversal", "--json")[1])
    again = json.loads(_cli(tmp_path, "card", "short-term-reversal", "--json")[1])
    assert first["card"] == again["card"] and again["created"] is False
    assert len(cards.all_ids(tmp_path)) == 1
    cards.note_link(tmp_path, first["card"], "rule", "run-1")
    cards.note_link(tmp_path, first["card"], "rule", "run-2")
    code, output = _cli(tmp_path, "show", "short-term-reversal")
    assert code == 0
    assert first["card"] in output and "2 test(s) linked" in output
    facts = json.loads(_cli(tmp_path, "show", "short-term-reversal", "--json")[1])
    assert facts["cards"] == [{"card": first["card"], "tests": 2}]


def test_card_works_for_a_private_record(tmp_path: Path) -> None:
    _private(tmp_path)
    code, output = _cli(tmp_path, "card", "my-own-note", "--json")
    assert code == 0, output
    assert "my-own-note" in cards.load(tmp_path, json.loads(output)["card"]).claim
